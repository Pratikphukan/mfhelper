"""Google Sheets integration: wide-format layout with merged two-row header.

Sheet layout (5 sub-columns per fund):

    Row 1 (header):  | Run Timestamp | Fund A name (merged across 5 cols)                                      | Fund B name ... |
    Row 2 (labels):  |               |  NAV  | Day Change % | Dist 52W H% | Dist 200D SMA % | RSI (14) |  NAV  ... |
    Row 3 onwards:   | 2026-05-11 ...| 83.15 |    0.29%     |   -2.84%    |      1.43%      |  62.40   | 118.12... |

- ``Run Timestamp (IST)`` in A1 is merged across A1:A2 so it spans both header rows.
- Each fund name in row 1 is merged across its five sub-columns.
- Column layout for fund at 0-based index ``i``:
    NAV col index             = 2 + 5 * i      (1-based, so fund 0 is column 2 = B)
    Day Change % col index    = 3 + 5 * i
    Dist 52W H% col index     = 4 + 5 * i
    Dist 200D SMA % col index = 5 + 5 * i
    RSI (14) col index        = 6 + 5 * i

Backwards compatibility: :meth:`SheetAppender.sync_columns` auto-migrates
older layouts in place, preserving every existing data row:

- 2-sub-col legacy layout (NAV + Day Change % only) -> chained 2->3->4->5
  by inserting a Dist 52W High %, then a Dist 200D SMA %, then an RSI (14)
  column for each fund group.
- 3-sub-col layout (NAV + Day Change % + Dist 52W H%) -> chained 3->4->5.
- 4-sub-col layout (... + Dist 200D SMA %) -> single 4->5 step inserting an
  RSI (14) column.

Each structural migration processes fund groups right-to-left so column
indices to the left don't shift mid-loop, unmerges and re-merges the
fund-name header to span the wider range, applies the appropriate number
format to the new column, and is idempotent at the layout level.

Separately, :meth:`SheetAppender.migrate_sma_50d_to_200d` handles the
"50D SMA -> 200D SMA" relabel for sheets that ran with the older 50-day
SMA window. It detects the legacy header text in row 2, renames it to
``Dist from 200D SMA %``, and (via a caller-supplied callable) recomputes
every historical SMA cell with the proper 200-day value -- all in a single
``batch_update``. Idempotent: a no-op once the header reads "200D".

Fund columns are append-only -- see :mod:`mfhelper.columns`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import logging
import time
from typing import Callable, Mapping

import gspread
from gspread.utils import rowcol_to_a1
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

log = logging.getLogger(__name__)

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADER_ROWS = 2
DATA_START_ROW = HEADER_ROWS + 1
RUN_TIMESTAMP_LABEL = "Run Timestamp (IST)"
NAV_LABEL = "NAV"
DAY_CHANGE_LABEL = "Day Change %"
DIST_52W_LABEL = "Dist from 52W High %"
DIST_SMA_LABEL = "Dist from 200D SMA %"
LEGACY_DIST_50D_SMA_LABEL = "Dist from 50D SMA %"  # detection-only, for one-time relabel
RSI_LABEL = "RSI (14)"

SUB_COLS_PER_FUND = 5
SUB_LABELS = [
    NAV_LABEL,
    DAY_CHANGE_LABEL,
    DIST_52W_LABEL,
    DIST_SMA_LABEL,
    RSI_LABEL,
]
_SMA_LABELS = (DIST_SMA_LABEL, LEGACY_DIST_50D_SMA_LABEL)

_NAV_NUMBER_FORMAT = {"type": "NUMBER", "pattern": "0.0000"}
_PERCENT_NUMBER_FORMAT = {"type": "NUMBER", "pattern": '0.00"%"'}
_RSI_NUMBER_FORMAT = {"type": "NUMBER", "pattern": "0.00"}

_SUB_COL_FORMATS = (
    _NAV_NUMBER_FORMAT,
    _PERCENT_NUMBER_FORMAT,
    _PERCENT_NUMBER_FORMAT,
    _PERCENT_NUMBER_FORMAT,
    _RSI_NUMBER_FORMAT,
)


@dataclass(frozen=True)
class NavValue:
    nav: float | None
    day_change_pct: float | None
    dist_52w_pct: float | None = None
    dist_200d_sma_pct: float | None = None
    rsi: float | None = None


def _load_credentials(credentials_path: Path, token_path: Path) -> Credentials:
    """Return a valid Sheets API ``Credentials`` object.

    Order of preference:

    1. Use the cached token at ``token_path`` if it's still valid.
    2. Otherwise, refresh it. If the refresh fails with ``RefreshError``
       (Google's catch-all for expired/revoked/unknown refresh tokens --
       most commonly hit when the OAuth client is in *Testing* status in
       Google Cloud Console, which forces refresh tokens to expire after
       seven days), discard the dead token and fall through to the
       desktop flow instead of crashing the run.
    3. Otherwise, run the desktop OAuth flow (a browser window opens).

    The cached token is rewritten on every successful auth, so the next
    run resumes silently.
    """
    creds: Credentials | None = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SHEETS_SCOPES)
        except ValueError as exc:
            log.warning(
                "Cached OAuth token at %s is malformed (%s); discarding it",
                token_path,
                exc,
            )
            creds = None

    if creds and creds.valid:
        return creds

    refreshed = False
    if creds and creds.expired and creds.refresh_token:
        try:
            log.info("Refreshing expired OAuth token")
            creds.refresh(Request())
            refreshed = True
        except RefreshError as exc:
            # The refresh token is expired/revoked/unknown to Google.
            # Most common cause: the GCP OAuth client is in "Testing"
            # status, which caps refresh tokens at 7 days. Other causes:
            # account password change, scope change, or hitting the
            # 50-active-tokens-per-client limit. None are recoverable
            # without a fresh consent grant -- so discard the stale
            # token file and fall through to the desktop flow.
            log.warning(
                "Stored OAuth refresh token is no longer valid (%s). "
                "Deleting %s and re-running the desktop OAuth consent "
                "flow. A browser window will open.",
                exc,
                token_path,
            )
            try:
                token_path.unlink()
            except FileNotFoundError:
                pass
            creds = None

    if not refreshed:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"OAuth client file not found at {credentials_path}. "
                "Download it from Google Cloud Console (OAuth client -> Desktop) "
                "and save it there."
            )
        log.info("Running OAuth desktop flow (browser window will open)")
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SHEETS_SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    with token_path.open("w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def _group_first_col(group_index: int, *, sub_cols: int = SUB_COLS_PER_FUND) -> int:
    """1-based column index of the leftmost cell of fund group ``group_index`` (0-based)."""
    return 2 + sub_cols * group_index


def _group_last_col(group_index: int, *, sub_cols: int = SUB_COLS_PER_FUND) -> int:
    return _group_first_col(group_index, sub_cols=sub_cols) + sub_cols - 1


def _col_letter(col_index: int) -> str:
    return "".join(ch for ch in rowcol_to_a1(1, col_index) if ch.isalpha())


@dataclass(frozen=True)
class _LayoutInfo:
    sub_cols: int          # 0 = empty header, 2 = legacy NAV+DC, 3 = +52W, 4 = +SMA, 5 = current (+RSI)
    group_count: int
    legacy_sma_50d: bool = False  # True if SMA column header still reads "Dist from 50D SMA %"


class SheetAppender:
    def __init__(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        credentials_path: Path,
        token_path: Path,
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._client: gspread.Client | None = None
        self._worksheet: gspread.Worksheet | None = None

    def _connect(self) -> gspread.Worksheet:
        if self._worksheet is not None:
            return self._worksheet

        creds = _load_credentials(self._credentials_path, self._token_path)
        self._client = gspread.authorize(creds)
        spreadsheet = self._client.open_by_key(self._spreadsheet_id)

        try:
            worksheet = spreadsheet.worksheet(self._worksheet_name)
        except gspread.WorksheetNotFound:
            log.info("Worksheet %r not found; creating it", self._worksheet_name)
            worksheet = spreadsheet.add_worksheet(
                title=self._worksheet_name, rows=1000, cols=30
            )

        self._worksheet = worksheet
        return worksheet

    def _inspect_layout(self, worksheet: gspread.Worksheet) -> _LayoutInfo:
        row2 = self._run_with_retry(lambda: worksheet.row_values(2))
        if not row2 or len(row2) < 2:
            return _LayoutInfo(sub_cols=0, group_count=0)

        labels = [c.strip() for c in row2[1:]]
        if not labels:
            return _LayoutInfo(sub_cols=0, group_count=0)

        if labels[0] != NAV_LABEL:
            raise RuntimeError(
                f"Unexpected label at row 2 column B: got {labels[0]!r}, expected {NAV_LABEL!r}. "
                "This worksheet may contain data from an unrelated layout. "
                "Either clear it or pick a different worksheet in config/settings.yaml."
            )

        legacy_sma_50d = False

        if len(labels) < 3:
            sub_cols = 2
        elif labels[2] == NAV_LABEL:
            sub_cols = 2
        elif labels[2] == DIST_52W_LABEL:
            if len(labels) < 4 or labels[3] == NAV_LABEL:
                sub_cols = 3
            elif labels[3] in _SMA_LABELS:
                if labels[3] == LEGACY_DIST_50D_SMA_LABEL:
                    legacy_sma_50d = True
                if len(labels) < 5 or labels[4] == NAV_LABEL:
                    sub_cols = 4
                elif labels[4] == RSI_LABEL:
                    sub_cols = 5
                else:
                    raise RuntimeError(
                        f"Unexpected label at row 2 column F: got {labels[4]!r}, "
                        f"expected {NAV_LABEL!r} (4-sub-col layout) or "
                        f"{RSI_LABEL!r} (5-sub-col layout)."
                    )
            else:
                raise RuntimeError(
                    f"Unexpected label at row 2 column E: got {labels[3]!r}, "
                    f"expected {NAV_LABEL!r} (3-sub-col layout) or "
                    f"{DIST_SMA_LABEL!r} (4- or 5-sub-col layout)."
                )
        else:
            raise RuntimeError(
                f"Unexpected label at row 2 column D: got {labels[2]!r}, "
                f"expected {NAV_LABEL!r} (legacy 2-sub-col layout) or "
                f"{DIST_52W_LABEL!r} (3-, 4- or 5-sub-col layout)."
            )

        if len(labels) % sub_cols != 0:
            raise RuntimeError(
                f"Row 2 has {len(labels)} label cells (excluding A2), which is not a "
                f"multiple of {sub_cols}. Header is corrupted."
            )

        group_count = len(labels) // sub_cols
        for g in range(group_count):
            for s in range(sub_cols):
                idx = g * sub_cols + s
                got = labels[idx]
                expected_label = SUB_LABELS[s]
                if s == 3 and got in _SMA_LABELS:
                    if got == LEGACY_DIST_50D_SMA_LABEL:
                        legacy_sma_50d = True
                    continue  # SMA column accepts either current or legacy label
                if got != expected_label:
                    raise RuntimeError(
                        f"Header row 2 mismatch at column {idx + 2}: got "
                        f"{got!r}, expected {expected_label!r}."
                    )
        return _LayoutInfo(
            sub_cols=sub_cols,
            group_count=group_count,
            legacy_sma_50d=legacy_sma_50d,
        )

    def sync_columns(
        self,
        ordered_codes: list[str],
        display_names: Mapping[str, str],
    ) -> int:
        """Ensure the worksheet matches ``ordered_codes`` in the 5-sub-column layout.

        Auto-migrates older 2-, 3-, or 4-sub-column layouts in place
        (preserving rows). Returns the number of new fund groups appended
        (excluding migration).
        """
        worksheet = self._run_with_retry(self._connect)
        layout = self._inspect_layout(worksheet)
        target = len(ordered_codes)

        if layout.sub_cols in (2, 3, 4) and target < layout.group_count:
            raise RuntimeError(
                f"Worksheet has {layout.group_count} fund group(s) but state knows "
                f"only {target}. Sheet and data/sheet_columns.json are out of sync."
            )

        if layout.sub_cols == 2:
            self._migrate_2col_to_3col(worksheet, layout.group_count)
            layout = _LayoutInfo(sub_cols=3, group_count=layout.group_count)

        if layout.sub_cols == 3:
            self._migrate_3col_to_4col(worksheet, layout.group_count)
            layout = _LayoutInfo(sub_cols=4, group_count=layout.group_count)

        if layout.sub_cols == 4:
            self._migrate_4col_to_5col(worksheet, layout.group_count)
            layout = _LayoutInfo(sub_cols=5, group_count=layout.group_count)

        if target < layout.group_count:
            raise RuntimeError(
                f"Worksheet has {layout.group_count} fund group(s) but state knows "
                f"only {target}. Sheet and data/sheet_columns.json are out of sync."
            )

        if layout.sub_cols == 0 and target == 0:
            return 0

        if layout.sub_cols == 0:
            self._write_initial_header(worksheet, ordered_codes, display_names)
            return target

        if target > layout.group_count:
            new_codes = ordered_codes[layout.group_count :]
            self._append_header_groups(
                worksheet, layout.group_count, new_codes, display_names
            )
            return len(new_codes)

        return 0

    def _migrate_2col_to_3col(
        self, worksheet: gspread.Worksheet, group_count: int
    ) -> None:
        """Insert a Dist 52W H% column right after each fund's Day Change %."""
        if group_count == 0:
            return
        log.info(
            "Migrating worksheet from 2-sub-col layout to 3-sub-col layout "
            "(%d fund group(s))",
            group_count,
        )
        new_total_cols = 1 + 3 * group_count
        self._ensure_col_count(worksheet, new_total_cols)

        for i in range(group_count, 0, -1):
            old_nav_col = 2 * i
            old_dc_col = old_nav_col + 1
            new_dist_col = old_dc_col + 1
            self._extend_group_with_one_column(
                worksheet,
                old_first_col=old_nav_col,
                old_last_col=old_dc_col,
                new_col=new_dist_col,
                new_label=DIST_52W_LABEL,
                new_format=_PERCENT_NUMBER_FORMAT,
            )

        log.info("In-place migration complete: %d group(s) now have 3 sub-columns", group_count)

    def _migrate_3col_to_4col(
        self, worksheet: gspread.Worksheet, group_count: int
    ) -> None:
        """Insert a Dist 200D SMA % column right after each fund's Dist 52W H%."""
        if group_count == 0:
            return
        log.info(
            "Migrating worksheet from 3-sub-col layout to 4-sub-col layout "
            "(%d fund group(s))",
            group_count,
        )
        new_total_cols = 1 + 4 * group_count
        self._ensure_col_count(worksheet, new_total_cols)

        for i in range(group_count, 0, -1):
            old_nav_col = 3 * i - 1
            old_d52w_col = 3 * i + 1
            new_dist_col = old_d52w_col + 1
            self._extend_group_with_one_column(
                worksheet,
                old_first_col=old_nav_col,
                old_last_col=old_d52w_col,
                new_col=new_dist_col,
                new_label=DIST_SMA_LABEL,
                new_format=_PERCENT_NUMBER_FORMAT,
            )

        log.info("In-place migration complete: %d group(s) now have 4 sub-columns", group_count)

    def _migrate_4col_to_5col(
        self, worksheet: gspread.Worksheet, group_count: int
    ) -> None:
        """Insert an RSI (14) column right after each fund's Dist ... SMA %."""
        if group_count == 0:
            return
        log.info(
            "Migrating worksheet from 4-sub-col layout to 5-sub-col layout "
            "(%d fund group(s))",
            group_count,
        )
        new_total_cols = 1 + 5 * group_count
        self._ensure_col_count(worksheet, new_total_cols)

        for i in range(group_count, 0, -1):
            old_nav_col = 4 * i - 2
            old_d50d_col = 4 * i + 1
            new_rsi_col = old_d50d_col + 1
            self._extend_group_with_one_column(
                worksheet,
                old_first_col=old_nav_col,
                old_last_col=old_d50d_col,
                new_col=new_rsi_col,
                new_label=RSI_LABEL,
                new_format=_RSI_NUMBER_FORMAT,
            )

        log.info("In-place migration complete: %d group(s) now have 5 sub-columns", group_count)

    def migrate_sma_50d_to_200d(
        self,
        ordered_codes: list[str],
        compute_sma: Callable[[str, date, float], float | None],
    ) -> bool:
        """Rename the SMA column header from '50D' to '200D' and backfill cells.

        Idempotent: if the SMA column already reads ``Dist from 200D SMA %``,
        this is a no-op and returns False.

        ``compute_sma(code, run_date, nav_in_sheet)`` is invoked for every
        existing data row and every fund in ``ordered_codes`` to produce the
        new SMA distance value (or ``None`` to leave the cell blank). The
        callback is responsible for owning the per-fund history; the
        SheetAppender intentionally does not fetch any market data itself.

        Caller is expected to:
          - have already run :meth:`sync_columns` (so the sheet is in the
            current 5-sub-col layout, possibly with a legacy SMA header),
          - call this *before* :meth:`append_run_row` so today's row is
            written under the renamed header.

        Returns True if the rename ran (and a backfill was attempted),
        False if no work was needed.
        """
        worksheet = self._run_with_retry(self._connect)
        layout = self._inspect_layout(worksheet)

        if not layout.legacy_sma_50d:
            return False
        if layout.sub_cols not in (4, 5):
            return False

        n = len(ordered_codes)
        if n != layout.group_count:
            raise RuntimeError(
                f"SMA migration: ordered_codes has {n} entries but worksheet has "
                f"{layout.group_count} fund group(s)."
            )

        log.info(
            "Migrating SMA column header from %r to %r and backfilling values "
            "across %d fund group(s)",
            LEGACY_DIST_50D_SMA_LABEL,
            DIST_SMA_LABEL,
            n,
        )

        all_values = self._run_with_retry(lambda: worksheet.get_all_values())
        data_rows = all_values[HEADER_ROWS:] if len(all_values) > HEADER_ROWS else []

        batch: list[dict] = []

        for i, code in enumerate(ordered_codes):
            sma_col = _group_first_col(i) + 3
            sma_letter = _col_letter(sma_col)
            label_cell = rowcol_to_a1(2, sma_col)
            batch.append(
                {"range": label_cell, "values": [[DIST_SMA_LABEL]]}
            )

            if not data_rows:
                continue

            nav_col_zero_based = _group_first_col(i) - 1  # row list is 0-based
            sma_col_zero_based = nav_col_zero_based + 3
            column_values: list[list[object]] = []

            for row in data_rows:
                ts = row[0] if row else ""
                nav_str = row[nav_col_zero_based] if len(row) > nav_col_zero_based else ""

                try:
                    run_date_str = ts.split(" ", 1)[0] if ts else ""
                    run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
                except ValueError:
                    column_values.append([""])
                    continue

                try:
                    current_nav = (
                        float(nav_str.replace(",", "")) if nav_str else None
                    )
                except ValueError:
                    current_nav = None
                if current_nav is None:
                    column_values.append([""])
                    continue

                value = compute_sma(code, run_date, current_nav)
                column_values.append([value if value is not None else ""])

            start_row = HEADER_ROWS + 1
            end_row = HEADER_ROWS + len(data_rows)
            batch.append(
                {
                    "range": f"{sma_letter}{start_row}:{sma_letter}{end_row}",
                    "values": column_values,
                }
            )

        if batch:
            self._run_with_retry(
                lambda: worksheet.batch_update(
                    batch, value_input_option="USER_ENTERED"
                )
            )

        log.info("SMA 50D->200D migration complete (%d row(s) backfilled per fund)",
                 len(data_rows))
        return True

    def _extend_group_with_one_column(
        self,
        worksheet: gspread.Worksheet,
        *,
        old_first_col: int,
        old_last_col: int,
        new_col: int,
        new_label: str,
        new_format: dict,
    ) -> None:
        """Insert one empty column at ``new_col`` and re-merge the fund-name header.

        ``old_first_col``..``old_last_col`` is the existing merge range for this
        fund in row 1 (in the OLD column numbering, i.e. before insertion).
        ``new_col`` is the position to insert at, which must equal
        ``old_last_col + 1`` -- i.e. immediately to the right of the existing
        group, OUTSIDE the current merge.
        """
        old_merge_range = f"{rowcol_to_a1(1, old_first_col)}:{rowcol_to_a1(1, old_last_col)}"
        try:
            self._run_with_retry(lambda r=old_merge_range: worksheet.unmerge_cells(r))
        except gspread.exceptions.APIError as exc:
            log.warning("Unmerge of %s failed (continuing): %s", old_merge_range, exc)

        self._run_with_retry(lambda c=new_col: worksheet.insert_cols([[""]], col=c))

        new_merge_range = f"{rowcol_to_a1(1, old_first_col)}:{rowcol_to_a1(1, new_col)}"
        self._run_with_retry(
            lambda r=new_merge_range: worksheet.merge_cells(r, merge_type="MERGE_ALL")
        )

        label_cell = rowcol_to_a1(2, new_col)
        self._run_with_retry(
            lambda c=label_cell: worksheet.update(values=[[new_label]], range_name=c)
        )

        col_letter = _col_letter(new_col)
        range_name = f"{col_letter}{DATA_START_ROW}:{col_letter}"
        self._run_with_retry(
            lambda r=range_name: worksheet.format(r, {"numberFormat": new_format})
        )

    def _write_initial_header(
        self,
        worksheet: gspread.Worksheet,
        ordered_codes: list[str],
        display_names: Mapping[str, str],
    ) -> None:
        n = len(ordered_codes)
        total_cols = 1 + SUB_COLS_PER_FUND * n
        self._ensure_col_count(worksheet, total_cols)

        row1: list[str] = [RUN_TIMESTAMP_LABEL]
        row2: list[str] = [""]
        for code in ordered_codes:
            display = display_names.get(code) or code
            row1.append(display)
            row1.extend([""] * (SUB_COLS_PER_FUND - 1))
            row2.extend(SUB_LABELS)

        range_name = f"A1:{_col_letter(total_cols)}2"
        self._run_with_retry(
            lambda: worksheet.update(values=[row1, row2], range_name=range_name)
        )

        self._run_with_retry(
            lambda: worksheet.merge_cells("A1:A2", merge_type="MERGE_ALL")
        )
        for i in range(n):
            start_a1 = rowcol_to_a1(1, _group_first_col(i))
            end_a1 = rowcol_to_a1(1, _group_last_col(i))
            merge_range = f"{start_a1}:{end_a1}"
            self._run_with_retry(
                lambda r=merge_range: worksheet.merge_cells(r, merge_type="MERGE_ALL")
            )

        self._apply_number_formats(worksheet, start_group_index=0, count=n)
        self._run_with_retry(lambda: worksheet.freeze(rows=HEADER_ROWS))

    def _append_header_groups(
        self,
        worksheet: gspread.Worksheet,
        existing_group_count: int,
        new_codes: list[str],
        display_names: Mapping[str, str],
    ) -> None:
        new_n = len(new_codes)
        current_total_cols = 1 + SUB_COLS_PER_FUND * existing_group_count
        new_total_cols = current_total_cols + SUB_COLS_PER_FUND * new_n
        self._ensure_col_count(worksheet, new_total_cols)

        row1_values: list[str] = []
        row2_values: list[str] = []
        for code in new_codes:
            display = display_names.get(code) or code
            row1_values.append(display)
            row1_values.extend([""] * (SUB_COLS_PER_FUND - 1))
            row2_values.extend(SUB_LABELS)

        start_col = current_total_cols + 1
        range_name = f"{rowcol_to_a1(1, start_col)}:{rowcol_to_a1(2, new_total_cols)}"
        self._run_with_retry(
            lambda: worksheet.update(
                values=[row1_values, row2_values], range_name=range_name
            )
        )

        for i in range(new_n):
            group_index = existing_group_count + i
            start_a1 = rowcol_to_a1(1, _group_first_col(group_index))
            end_a1 = rowcol_to_a1(1, _group_last_col(group_index))
            merge_range = f"{start_a1}:{end_a1}"
            self._run_with_retry(
                lambda r=merge_range: worksheet.merge_cells(r, merge_type="MERGE_ALL")
            )

        self._apply_number_formats(
            worksheet, start_group_index=existing_group_count, count=new_n
        )

    def _ensure_col_count(self, worksheet: gspread.Worksheet, required: int) -> None:
        if worksheet.col_count >= required:
            return
        delta = required - worksheet.col_count
        self._run_with_retry(lambda: worksheet.add_cols(delta))

    def _apply_number_formats(
        self,
        worksheet: gspread.Worksheet,
        *,
        start_group_index: int,
        count: int,
    ) -> None:
        if count == 0:
            return
        batch: list[dict] = []
        for i in range(count):
            group_index = start_group_index + i
            first = _group_first_col(group_index)
            for offset, fmt in enumerate(_SUB_COL_FORMATS):
                col_letter = _col_letter(first + offset)
                batch.append(
                    {
                        "range": f"{col_letter}{DATA_START_ROW}:{col_letter}",
                        "format": {"numberFormat": fmt},
                    }
                )
        self._run_with_retry(lambda: worksheet.batch_format(batch))

    def append_run_row(
        self,
        run_timestamp: str,
        ordered_codes: list[str],
        values_by_code: Mapping[str, NavValue],
    ) -> int:
        worksheet = self._run_with_retry(self._connect)
        row: list[object] = [run_timestamp]
        for code in ordered_codes:
            value = values_by_code.get(code)
            if value is None:
                row.extend([""] * SUB_COLS_PER_FUND)
            else:
                row.extend(
                    [
                        "" if value.nav is None else value.nav,
                        "" if value.day_change_pct is None else value.day_change_pct,
                        "" if value.dist_52w_pct is None else value.dist_52w_pct,
                        "" if value.dist_200d_sma_pct is None else value.dist_200d_sma_pct,
                        "" if value.rsi is None else value.rsi,
                    ]
                )
        self._run_with_retry(
            lambda: worksheet.append_rows([row], value_input_option="USER_ENTERED")
        )
        return 1

    def trim_to_window(self, history_days: int) -> int:
        """Keep only the most recent ``history_days`` distinct run-dates.

        Returns the number of data rows deleted.
        """
        if history_days < 1:
            raise ValueError("history_days must be >= 1")

        worksheet = self._run_with_retry(self._connect)
        timestamps = self._run_with_retry(lambda: worksheet.col_values(1))
        data_timestamps = (
            timestamps[HEADER_ROWS:] if len(timestamps) > HEADER_ROWS else []
        )

        seen: list[str] = []
        for ts in data_timestamps:
            run_date = ts.split(" ", 1)[0]
            if not seen or seen[-1] != run_date:
                seen.append(run_date)

        if len(seen) <= history_days:
            return 0

        cutoff_date = seen[-history_days]
        rows_to_delete = 0
        for ts in data_timestamps:
            if ts.split(" ", 1)[0] == cutoff_date:
                break
            rows_to_delete += 1

        if rows_to_delete == 0:
            return 0

        start_row = DATA_START_ROW
        end_row = start_row + rows_to_delete - 1
        log.info(
            "Trimming %d old data row(s) (rows %d..%d)", rows_to_delete, start_row, end_row
        )
        self._run_with_retry(lambda: worksheet.delete_rows(start_row, end_row))
        return rows_to_delete

    @staticmethod
    def _run_with_retry(action, *, attempts: int = 2, backoff_seconds: float = 2.0):
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return action()
            except gspread.exceptions.APIError as exc:
                last_exc = exc
                if attempt == attempts:
                    break
                log.warning(
                    "Sheets API error (attempt %d/%d): %s", attempt, attempts, exc
                )
                time.sleep(backoff_seconds)
        assert last_exc is not None
        raise last_exc
