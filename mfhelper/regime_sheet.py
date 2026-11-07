"""Google Sheets writer for the "Market Regime" tab.

One row per run date: the market regime and the numbers behind it. The tab is separate from
the Daily NAV tab and never touches it. Rules:

* The tab and its header are created if missing. A new tab is placed immediately to the right of
  the Daily NAV tab (``place_after``); an existing tab is never moved.
* If the tab already has a *different* header, nothing is written (``RegimeSheetError``), so
  someone else's data is never overwritten.
* A re-run on the same date replaces that date's row; other rows are never rewritten.
* After each write, rows whose date is ``keep_days`` or more days older than the run are removed
  from this tab. The header row and rows whose timestamp is not a date are never removed.
"""

from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
import time

import gspread

from mfhelper.market_regime import MarketContext
from mfhelper.sheets import _load_credentials

log = logging.getLogger(__name__)

REGIME_TAB_DEFAULT = "Market Regime"
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0
GROW_ROWS = 500
DEFAULT_KEEP_DAYS = 180

HEADERS = (
    "Run Timestamp (IST)",
    "Regime",
    "NIFTY 500",
    "Short SMA",
    "Long SMA",
    "VIX (smoothed)",
    "Nifty 50 P/E",
    "P/E state",
    "P/E source",
    "Market data as of",
    "Notes",
)

# 0-based column indexes used for number formats.
PRICE_COLUMNS = (2, 3, 4, 5)  # index close, two SMAs, VIX: 2 decimals
PE_COLUMN = 6                 # 1 decimal


def stale_row_ranges(timestamps: list[str], run_date: date, keep_days: int) -> list[tuple[int, int]]:
    """1-based inclusive ``(first, last)`` row ranges older than ``keep_days``, oldest first.

    ``timestamps`` is column A including the header (row 1, never returned). Rows whose first
    word is not an ISO date are left alone.
    """
    stale: list[int] = []
    for index, value in enumerate(timestamps):
        if index == 0:
            continue
        try:
            row_date = date.fromisoformat(value.split(" ", 1)[0])
        except ValueError:
            continue
        if (run_date - row_date).days >= keep_days:
            stale.append(index + 1)
    ranges: list[tuple[int, int]] = []
    for row in stale:
        if ranges and ranges[-1][1] == row - 1:
            ranges[-1] = (ranges[-1][0], row)
        else:
            ranges.append((row, row))
    return ranges


class RegimeSheetError(RuntimeError):
    """The tab cannot be written safely (for example its header is not ours)."""


def _round_or_blank(value: float | None, digits: int) -> float | str:
    return "" if value is None else round(value, digits)


def _pe_source(context: MarketContext) -> str:
    valuation = context.valuation
    if valuation.source is None:
        return ""
    when = valuation.as_of.isoformat() if valuation.as_of else "no date"
    if valuation.source == "nse":
        return "nse"
    if valuation.source == "nse_cache":
        return f"nse_cache ({when})"
    return f"manual ({when}{', STALE' if valuation.stale else ''})"


def build_row(run_timestamp: str, context: MarketContext) -> list[object]:
    """The sheet row for ``context``. Missing numbers are blank cells, never zeros."""
    valuation = context.valuation
    return [
        run_timestamp,
        context.regime.value,
        _round_or_blank(context.index_close, 2),
        _round_or_blank(context.sma_short, 2),
        _round_or_blank(context.sma_long, 2),
        _round_or_blank(context.vix_avg, 2),
        _round_or_blank(valuation.pe, 1),
        valuation.state,
        _pe_source(context),
        context.as_of.isoformat() if context.as_of else "",
        "; ".join(context.notes),
    ]


class RegimeSheetWriter:
    def __init__(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        credentials_path: Path,
        token_path: Path,
        keep_days: int = DEFAULT_KEEP_DAYS,
        place_after: str | None = None,
    ) -> None:
        self._keep_days = keep_days
        self._place_after = place_after
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._worksheet: gspread.Worksheet | None = None

    @staticmethod
    def _run_with_retry(call):
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                return call()
            except gspread.exceptions.APIError as exc:
                status = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
                if attempt < RETRY_ATTEMPTS and (status is None or status in (429, 500, 502, 503, 504)):
                    sleep_s = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    log.info(
                        "Sheets API attempt %d/%d failed (HTTP %s); retry in %.1fs",
                        attempt, RETRY_ATTEMPTS, status, sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                raise

    def _connect(self) -> gspread.Worksheet:
        if self._worksheet is not None:
            return self._worksheet
        creds = _load_credentials(self._credentials_path, self._token_path)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self._spreadsheet_id)
        try:
            ws = spreadsheet.worksheet(self._worksheet_name)
        except gspread.WorksheetNotFound:
            index = self._index_after(spreadsheet)
            log.info("Worksheet %r not found; creating at position %s", self._worksheet_name,
                     "end" if index is None else index)
            ws = spreadsheet.add_worksheet(
                title=self._worksheet_name, rows=1000, cols=len(HEADERS), index=index
            )
        self._worksheet = ws
        return ws

    def _index_after(self, spreadsheet) -> int | None:
        """Tab position just right of ``place_after``, or ``None`` (end of the tab bar) if unknown."""
        if not self._place_after:
            return None
        try:
            return spreadsheet.worksheet(self._place_after).index + 1
        except Exception as exc:  # the neighbour is missing or unreadable: placement is cosmetic
            log.info("Could not find tab %r to place %r next to it: %s", self._place_after,
                     self._worksheet_name, exc)
            return None

    def _ensure_header(self, ws: gspread.Worksheet) -> None:
        existing = [str(cell).strip() for cell in self._run_with_retry(lambda: ws.row_values(1))]
        if not existing:
            self._run_with_retry(
                lambda: ws.update("A1", [list(HEADERS)], value_input_option="RAW")
            )
            self._format(ws)
            return
        if tuple(existing) != HEADERS:
            raise RegimeSheetError(
                f"Worksheet {self._worksheet_name!r} already has a different header "
                f"({existing[:4]}...). Refusing to write. Rename or delete that tab, or set "
                "regime.sheet_name to another name."
            )

    def _format(self, ws: gspread.Worksheet) -> None:
        sheet_id = ws._properties["sheetId"]
        n_cols = len(HEADERS)

        def number_format(column: int, pattern: str) -> dict:
            return {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": column,
                              "endColumnIndex": column + 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            }

        requests = [
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": n_cols},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER",
                        "backgroundColor": {"red": 0.91, "green": 0.94, "blue": 0.98},
                    }},
                    "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.horizontalAlignment,"
                              "userEnteredFormat.backgroundColor",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]
        requests += [number_format(c, "#,##0.00") for c in PRICE_COLUMNS]
        requests.append(number_format(PE_COLUMN, "0.0"))
        try:
            self._run_with_retry(lambda: ws.spreadsheet.batch_update({"requests": requests}))
        except Exception as exc:  # cosmetic only; the data is what matters
            log.warning("Could not apply formatting to %r: %s", self._worksheet_name, exc)

    def record(self, run_timestamp: str, context: MarketContext) -> int:
        """Write (or replace) the row for ``run_timestamp``'s date. Returns the 1-based row number."""
        ws = self._run_with_retry(self._connect)
        self._ensure_header(ws)

        row = build_row(run_timestamp, context)
        run_date = run_timestamp.split(" ", 1)[0]
        timestamps = self._run_with_retry(lambda: ws.col_values(1))
        same_day = [i + 1 for i, ts in enumerate(timestamps) if i > 0 and ts.split(" ", 1)[0] == run_date]
        target = same_day[-1] if same_day else len(timestamps) + 1
        if len(same_day) > 1:
            log.warning("Found %d rows for %s in %r; updating the last one", len(same_day), run_date,
                        self._worksheet_name)

        if target > ws.row_count:  # a new tab starts with 1000 rows; grow it before writing past the end
            self._run_with_retry(lambda: ws.resize(rows=target + GROW_ROWS))

        end_col = chr(ord("A") + len(HEADERS) - 1)
        self._run_with_retry(
            lambda: ws.update(f"A{target}:{end_col}{target}", [row], value_input_option="RAW")
        )
        log.info("%s %r row %d for %s", "Replaced" if same_day else "Appended", self._worksheet_name,
                 target, run_date)
        return target - self._trim(ws, run_date, target)

    def _trim(self, ws: gspread.Worksheet, run_date: str, target_row: int) -> int:
        """Remove rows older than ``keep_days``. Returns how many rows above ``target_row`` went away.

        A failure here is logged and ignored: the row for today is already written.
        """
        try:
            timestamps = self._run_with_retry(lambda: ws.col_values(1))
            ranges = stale_row_ranges(timestamps, date.fromisoformat(run_date), self._keep_days)
            removed_above = 0
            for first, last in reversed(ranges):  # bottom-up, so earlier row numbers stay valid
                self._run_with_retry(lambda f=first, l=last: ws.delete_rows(f, l))
                if last < target_row:
                    removed_above += last - first + 1
            if ranges:
                total = sum(last - first + 1 for first, last in ranges)
                log.info("Removed %d row(s) older than %d days from %r", total, self._keep_days,
                         self._worksheet_name)
            return removed_above
        except Exception as exc:
            log.warning("Could not trim old rows from %r: %s", self._worksheet_name, exc)
            return 0
