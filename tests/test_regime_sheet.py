"""RegimeSheetWriter against a fake worksheet. No real Google Sheet is ever touched."""

from datetime import date
from pathlib import Path
import re
from unittest.mock import Mock

import gspread
import pytest

from mfhelper import regime_sheet as rs
from mfhelper.market_regime import MarketContext, Regime, Valuation
from mfhelper.regime_sheet import HEADERS, RegimeSheetError, RegimeSheetWriter, build_row

AS_OF = date(2026, 11, 6)


def context(**overrides) -> MarketContext:
    base = dict(
        available=True, regime=Regime.NEUTRAL, valuation=Valuation(20.64, "fair", source="nse", as_of=AS_OF),
        as_of=AS_OF, index_close=23456.949, sma_short=22497.751, sma_long=22763.424, vix_avg=15.894,
    )
    base.update(overrides)
    return MarketContext(**base)


class FakeSpreadsheetApi:
    def __init__(self):
        self.batches: list[dict] = []
        self.fail = False

    def batch_update(self, body):
        if self.fail:
            raise RuntimeError("formatting boom")
        self.batches.append(body)


class FakeWorksheet:
    def __init__(self, rows=None, row_count=1000):
        self.rows: list[list] = [list(r) for r in (rows or [])]
        self.row_count = row_count
        self.spreadsheet = FakeSpreadsheetApi()
        self._properties = {"sheetId": 77}
        self.updates: list[tuple[str, list, str]] = []
        self.resizes: list[int] = []

    def row_values(self, n):
        return list(self.rows[n - 1]) if len(self.rows) >= n else []

    def col_values(self, n):
        return [str(r[n - 1]) if len(r) >= n else "" for r in self.rows]

    def update(self, a1, values, value_input_option=None):
        self.updates.append((a1, values, value_input_option))
        row = int(re.match(r"A(\d+)", a1).group(1))
        while len(self.rows) < row:
            self.rows.append([])
        self.rows[row - 1] = list(values[0])

    def resize(self, rows=None, cols=None):
        self.resizes.append(rows)
        self.row_count = rows


class FakeSpreadsheet:
    def __init__(self, tabs=None):
        self.tabs: dict[str, FakeWorksheet] = dict(tabs or {})
        self.added: list[str] = []

    def worksheet(self, name):
        if name not in self.tabs:
            raise gspread.WorksheetNotFound(name)
        return self.tabs[name]

    def add_worksheet(self, title, rows, cols):
        self.added.append(title)
        self.tabs[title] = FakeWorksheet(row_count=rows)
        return self.tabs[title]


@pytest.fixture
def writer_for(monkeypatch):
    def make(tabs=None, name="Market Regime"):
        spreadsheet = FakeSpreadsheet(tabs)
        monkeypatch.setattr(rs, "_load_credentials", lambda *_a: object())
        monkeypatch.setattr(rs.gspread, "authorize", lambda _c: Mock(open_by_key=lambda _id: spreadsheet))
        monkeypatch.setattr(rs.time, "sleep", lambda _s: None)
        return RegimeSheetWriter("sheet-id", name, Path("c.json"), Path("t.json")), spreadsheet

    return make


# --- build_row ------------------------------------------------------------------------


def test_row_matches_the_headers_and_rounds_numbers():
    row = build_row("2026-11-06 10:30:02", context())
    assert len(row) == len(HEADERS)
    assert row == [
        "2026-11-06 10:30:02", "NEUTRAL", 23456.95, 22497.75, 22763.42, 15.89, 20.6, "fair", "nse",
        "2026-11-06", "",
    ]


def test_unavailable_context_gives_blank_numbers_not_zeros():
    ctx = MarketContext(False, Regime.NEUTRAL, Valuation(None, "unknown"), notes=("no ^CRSLDX data", "x"))
    row = build_row("2026-11-06 10:30:02", ctx)
    assert row[1] == "NEUTRAL" and row[2:7] == [""] * 5
    assert row[7] == "unknown" and row[8] == "" and row[9] == ""
    assert row[10] == "no ^CRSLDX data; x"


@pytest.mark.parametrize(
    "valuation,expected",
    [
        (Valuation(21.0, "fair", source="nse", as_of=AS_OF), "nse"),
        (Valuation(21.0, "fair", source="nse_cache", as_of=date(2026, 11, 3)), "nse_cache (2026-11-03)"),
        (Valuation(21.0, "fair", source="manual", as_of=date(2026, 11, 1)), "manual (2026-11-01)"),
        (Valuation(21.0, "fair", source="manual", as_of=date(2026, 10, 1), stale=True), "manual (2026-10-01, STALE)"),
        (Valuation(21.0, "fair", source="manual", as_of=None, stale=True), "manual (no date, STALE)"),
        (Valuation(None, "unknown"), ""),
    ],
)
def test_pe_source_text(valuation, expected):
    assert build_row("2026-11-06 10:30:02", context(valuation=valuation))[8] == expected


# --- writing --------------------------------------------------------------------------


def test_first_run_creates_the_tab_header_and_formats(writer_for):
    writer, spreadsheet = writer_for()
    assert writer.record("2026-11-06 10:30:02", context()) == 2

    assert spreadsheet.added == ["Market Regime"]
    ws = spreadsheet.tabs["Market Regime"]
    assert ws.rows[0] == list(HEADERS)
    assert ws.rows[1][:2] == ["2026-11-06 10:30:02", "NEUTRAL"]
    assert all(mode == "RAW" for _a, _v, mode in ws.updates)  # timestamps stay text
    (batch,) = ws.spreadsheet.batches
    kinds = {next(iter(r)) for r in batch["requests"]}
    assert kinds == {"repeatCell", "updateSheetProperties"}
    assert any(r.get("updateSheetProperties", {}).get("properties", {}).get("gridProperties") == {"frozenRowCount": 1}
               for r in batch["requests"])


def test_a_new_day_appends_below_and_leaves_old_rows_alone(writer_for):
    writer, spreadsheet = writer_for()
    writer.record("2026-11-05 10:30:02", context(regime=Regime.BEAR))
    old_row = list(spreadsheet.tabs["Market Regime"].rows[1])
    assert writer.record("2026-11-06 10:30:02", context()) == 3
    ws = spreadsheet.tabs["Market Regime"]
    assert len(ws.rows) == 3 and ws.rows[1] == old_row and ws.rows[2][0] == "2026-11-06 10:30:02"


def test_rerun_on_the_same_day_replaces_that_days_row(writer_for):
    writer, spreadsheet = writer_for()
    writer.record("2026-11-05 10:30:02", context())
    writer.record("2026-11-06 10:30:02", context(regime=Regime.BEAR))
    assert writer.record("2026-11-06 15:00:00", context(regime=Regime.UPTREND)) == 3

    ws = spreadsheet.tabs["Market Regime"]
    assert len(ws.rows) == 3
    assert ws.rows[2][:2] == ["2026-11-06 15:00:00", "UPTREND"]
    assert ws.rows[1][0] == "2026-11-05 10:30:02"


def test_existing_tab_with_our_header_is_reused_without_reformatting(writer_for):
    ws = FakeWorksheet(rows=[list(HEADERS)])
    writer, spreadsheet = writer_for({"Market Regime": ws})
    assert writer.record("2026-11-06 10:30:02", context()) == 2
    assert spreadsheet.added == [] and ws.spreadsheet.batches == []


def test_a_foreign_header_is_never_overwritten(writer_for):
    ws = FakeWorksheet(rows=[["Date", "Something else"], ["2026-01-01", "keep me"]])
    writer, _ = writer_for({"Market Regime": ws})
    with pytest.raises(RegimeSheetError, match="different header"):
        writer.record("2026-11-06 10:30:02", context())
    assert ws.updates == [] and ws.rows == [["Date", "Something else"], ["2026-01-01", "keep me"]]


def test_writes_only_the_target_tab(writer_for):
    nav = FakeWorksheet(rows=[["Run Timestamp (IST)", "NAV"], ["2026-11-06 10:30:02", 12.3]])
    writer, spreadsheet = writer_for({"Sheet1": nav}, name="Market Regime (Dev)")
    writer.record("2026-11-06 10:30:02", context())
    assert nav.updates == [] and spreadsheet.added == ["Market Regime (Dev)"]


def test_tab_grows_before_writing_past_the_last_row(writer_for):
    ws = FakeWorksheet(rows=[list(HEADERS)] + [[f"2020-01-{i:02d} 10:00:00"] for i in range(1, 6)], row_count=6)
    writer, _ = writer_for({"Market Regime": ws})
    assert writer.record("2026-11-06 10:30:02", context()) == 7
    assert ws.resizes == [7 + rs.GROW_ROWS]


def test_formatting_failure_does_not_stop_the_data_write(writer_for):
    writer, spreadsheet = writer_for()
    original_add = spreadsheet.add_worksheet

    def add_with_broken_formatting(title, rows, cols):
        ws = original_add(title, rows, cols)
        ws.spreadsheet.fail = True
        return ws

    spreadsheet.add_worksheet = add_with_broken_formatting
    assert writer.record("2026-11-06 10:30:02", context()) == 2
    assert spreadsheet.tabs["Market Regime"].rows[1][1] == "NEUTRAL"


def test_transient_api_errors_are_retried(writer_for):
    writer, spreadsheet = writer_for()
    writer.record("2026-11-05 10:30:02", context())
    ws = spreadsheet.tabs["Market Regime"]
    real_update = ws.update
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            response = Mock(status_code=429, text="quota")
            response.json.return_value = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
            raise gspread.exceptions.APIError(response)
        return real_update(*args, **kwargs)

    ws.update = flaky
    assert writer.record("2026-11-06 10:30:02", context()) == 3
    assert calls["n"] == 2


def test_non_retryable_errors_propagate(writer_for):
    writer, spreadsheet = writer_for()
    writer.record("2026-11-05 10:30:02", context())
    ws = spreadsheet.tabs["Market Regime"]

    def denied(*_a, **_k):
        response = Mock(status_code=403, text="no")
        response.json.return_value = {"error": {"code": 403, "message": "no", "status": "PERMISSION_DENIED"}}
        raise gspread.exceptions.APIError(response)

    ws.update = denied
    with pytest.raises(gspread.exceptions.APIError):
        writer.record("2026-11-06 10:30:02", context())
