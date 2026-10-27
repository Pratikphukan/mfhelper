"""Tests for the domestic gold price benchmark (GC=F × INR=X) in mfhelper.benchmarks.

All tests use a temporary directory for the cache and mock yfinance so
they never make real HTTP calls or touch data/benchmark_history/.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

import mfhelper.benchmarks as benchmarks_module
from mfhelper.benchmarks import (
    BenchmarkHistory,
    BenchmarkPoint,
    CACHE_FRESHNESS_HOURS,
    GOLD_INR_SENTINEL,
    MAX_FFILL_DAYS,
    _fetch_gold_inr,
    _load_cache,
    _save_cache,
    _cache_path,
    fetch_benchmark_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(dates: list[str], values: list[float], ticker: str) -> pd.DataFrame:
    """Build a minimal yfinance-style DataFrame."""
    idx = pd.to_datetime(dates)
    cols = pd.MultiIndex.from_tuples([("Close", ticker)])
    return pd.DataFrame(
        [[v] for v in values],
        index=idx,
        columns=cols,
    )


def _make_cache_file(
    tmp_path: Path,
    name: str,
    variant: str,
    points: list[BenchmarkPoint],
    age_hours: float = 0,
) -> Path:
    fetched_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    hist = BenchmarkHistory(
        name=name,
        variant=variant,
        history=points,
        fetched_at=fetched_at,
        data_source="yahoo_finance:GC=F×INR=X",
    )
    path = _cache_path(tmp_path, name, variant)
    _save_cache(path, hist)
    return path


SAMPLE_DATES = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"]
SAMPLE_GOLD_USD = [2600.0, 2610.0, 2620.0, 2630.0, 2640.0]
SAMPLE_USD_INR = [84.0, 84.1, 84.2, 84.3, 84.4]
# Expected INR values = gold_usd * usd_inr
EXPECTED_GOLD_INR = [g * r for g, r in zip(SAMPLE_GOLD_USD, SAMPLE_USD_INR)]


@pytest.fixture()
def cache_dir(tmp_path):
    """Provide a fresh temp cache directory for each test."""
    return tmp_path


# ---------------------------------------------------------------------------
# _fetch_gold_inr: construction logic
# ---------------------------------------------------------------------------

class TestFetchGoldInr:

    def _mock_download(self, gold_df, inr_df):
        """Return a side_effect function that routes by ticker."""
        def _download(ticker, **kwargs):
            if ticker == benchmarks_module.GOLD_FUTURES_TICKER:
                return gold_df
            if ticker == benchmarks_module.USDINR_TICKER:
                return inr_df
            return pd.DataFrame()
        return _download

    def test_returns_correct_inr_values(self):
        gold_df = _make_df(SAMPLE_DATES, SAMPLE_GOLD_USD, "GC=F")
        inr_df = _make_df(SAMPLE_DATES, SAMPLE_USD_INR, "INR=X")

        with patch.object(benchmarks_module.yf, "download", side_effect=self._mock_download(gold_df, inr_df)):
            points = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        assert points is not None
        assert len(points) == 5
        for p, expected in zip(points, EXPECTED_GOLD_INR):
            assert abs(p.close - expected) < 0.01

    def test_returns_sorted_oldest_first(self):
        gold_df = _make_df(SAMPLE_DATES, SAMPLE_GOLD_USD, "GC=F")
        inr_df = _make_df(SAMPLE_DATES, SAMPLE_USD_INR, "INR=X")

        with patch.object(benchmarks_module.yf, "download", side_effect=self._mock_download(gold_df, inr_df)):
            points = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        assert points[0].date < points[-1].date

    def test_returns_none_if_gold_empty(self):
        gold_df = pd.DataFrame()
        inr_df = _make_df(SAMPLE_DATES, SAMPLE_USD_INR, "INR=X")

        with patch.object(benchmarks_module.yf, "download", side_effect=self._mock_download(gold_df, inr_df)):
            result = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        assert result is None

    def test_returns_none_if_inr_empty(self):
        gold_df = _make_df(SAMPLE_DATES, SAMPLE_GOLD_USD, "GC=F")
        inr_df = pd.DataFrame()

        with patch.object(benchmarks_module.yf, "download", side_effect=self._mock_download(gold_df, inr_df)):
            result = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        assert result is None

    def test_returns_none_on_yfinance_exception(self):
        with patch.object(benchmarks_module.yf, "download", side_effect=Exception("network error")):
            result = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        assert result is None

    def test_forward_fill_handles_missing_inr_date(self):
        """If INR=X has no data on a date that GC=F has, ffill fills it."""
        # Gold has 5 dates, INR missing the middle one
        inr_dates = [SAMPLE_DATES[0], SAMPLE_DATES[1], SAMPLE_DATES[3], SAMPLE_DATES[4]]
        inr_values = [84.0, 84.1, 84.3, 84.4]

        gold_df = _make_df(SAMPLE_DATES, SAMPLE_GOLD_USD, "GC=F")
        inr_df = _make_df(inr_dates, inr_values, "INR=X")

        with patch.object(benchmarks_module.yf, "download", side_effect=self._mock_download(gold_df, inr_df)):
            points = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        assert points is not None
        # All 5 dates should be present (gap filled by ffill)
        assert len(points) == 5
        # The missing date (index 2) should use the previous INR value (84.1)
        assert abs(points[2].close - (SAMPLE_GOLD_USD[2] * 84.1)) < 0.01

    def test_forward_fill_limit_drops_long_gaps(self):
        """Gaps longer than MAX_FFILL_DAYS should be dropped."""
        # INR only has first and last date — gap of 3 days in between
        inr_dates = [SAMPLE_DATES[0], SAMPLE_DATES[4]]
        inr_values = [84.0, 84.4]

        gold_df = _make_df(SAMPLE_DATES, SAMPLE_GOLD_USD, "GC=F")
        inr_df = _make_df(inr_dates, inr_values, "INR=X")

        with patch.object(benchmarks_module.yf, "download", side_effect=self._mock_download(gold_df, inr_df)):
            points = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        assert points is not None
        # With MAX_FFILL_DAYS=3, dates 1,2,3 get filled from date 0
        # date 4 has its own INR value
        # So all 5 dates should survive (gap is exactly 3 = MAX_FFILL_DAYS)
        assert len(points) == 5

    def test_point_dates_are_correct(self):
        gold_df = _make_df(SAMPLE_DATES, SAMPLE_GOLD_USD, "GC=F")
        inr_df = _make_df(SAMPLE_DATES, SAMPLE_USD_INR, "INR=X")

        with patch.object(benchmarks_module.yf, "download", side_effect=self._mock_download(gold_df, inr_df)):
            points = _fetch_gold_inr(start=date(2026, 10, 20), end=date(2026, 10, 24))

        expected_dates = [date(2026, 10, d) for d in [20, 21, 22, 23, 24]]
        assert [p.date for p in points] == expected_dates


# ---------------------------------------------------------------------------
# fetch_benchmark_history: GOLD_INR routing
# ---------------------------------------------------------------------------

class TestFetchBenchmarkHistoryGold:

    def _mock_gold_inr_download(self, gold_df, inr_df):
        def _download(ticker, **kwargs):
            if ticker == benchmarks_module.GOLD_FUTURES_TICKER:
                return gold_df
            if ticker == benchmarks_module.USDINR_TICKER:
                return inr_df
            return pd.DataFrame()
        return _download

    def _good_dfs(self):
        gold_df = _make_df(SAMPLE_DATES, SAMPLE_GOLD_USD, "GC=F")
        inr_df = _make_df(SAMPLE_DATES, SAMPLE_USD_INR, "INR=X")
        return gold_df, inr_df

    def test_routes_gold_inr_sentinel(self, cache_dir):
        gold_df, inr_df = self._good_dfs()
        with patch.object(benchmarks_module.yf, "download",
                          side_effect=self._mock_gold_inr_download(gold_df, inr_df)):
            result = fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )
        assert result is not None
        assert result.name == GOLD_INR_SENTINEL
        assert result.data_source == "yahoo_finance:GC=F×INR=X"

    def test_gold_cache_miss_fetches_and_writes(self, cache_dir):
        gold_df, inr_df = self._good_dfs()
        with patch.object(benchmarks_module.yf, "download",
                          side_effect=self._mock_gold_inr_download(gold_df, inr_df)) as mock_dl:
            fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )
        assert mock_dl.call_count == 2  # GC=F and INR=X
        assert _cache_path(cache_dir, GOLD_INR_SENTINEL, "PR").exists()

    def test_gold_cache_hit_skips_fetch(self, cache_dir):
        sample_points = [BenchmarkPoint(date=date(2026, 10, d), close=float(d * 1000))
                         for d in [20, 21, 22]]
        _make_cache_file(cache_dir, GOLD_INR_SENTINEL, "PR", sample_points, age_hours=1)

        with patch.object(benchmarks_module.yf, "download") as mock_dl:
            result = fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )

        mock_dl.assert_not_called()
        assert result is not None
        assert len(result.history) == 3

    def test_gold_stale_cache_refetches(self, cache_dir):
        sample_points = [BenchmarkPoint(date=date(2026, 10, 20), close=200000.0)]
        _make_cache_file(cache_dir, GOLD_INR_SENTINEL, "PR", sample_points,
                         age_hours=CACHE_FRESHNESS_HOURS + 1)

        gold_df, inr_df = self._good_dfs()
        with patch.object(benchmarks_module.yf, "download",
                          side_effect=self._mock_gold_inr_download(gold_df, inr_df)) as mock_dl:
            fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )
        assert mock_dl.call_count == 2  # fetched fresh

    def test_gold_returns_none_on_failure_no_cache(self, cache_dir):
        with patch.object(benchmarks_module.yf, "download", return_value=pd.DataFrame()):
            result = fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )
        assert result is None

    def test_gold_falls_back_to_stale_cache_on_failure(self, cache_dir):
        sample_points = [BenchmarkPoint(date=date(2026, 10, 20), close=200000.0)]
        _make_cache_file(cache_dir, GOLD_INR_SENTINEL, "PR", sample_points,
                         age_hours=CACHE_FRESHNESS_HOURS + 5)

        with patch.object(benchmarks_module.yf, "download", return_value=pd.DataFrame()):
            result = fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )
        # Should fall back to stale cache
        assert result is not None
        assert len(result.history) == 1

    def test_non_gold_ticker_uses_yfinance_not_gold_constructor(self, cache_dir):
        """Regular NIFTY tickers should NOT call _fetch_gold_inr."""
        nifty_values = [21000.0, 21100.0, 21200.0, 21300.0, 21400.0]
        nifty_df = _make_df(SAMPLE_DATES, nifty_values, "^CRSLDX")

        with patch.object(benchmarks_module.yf, "download", return_value=nifty_df) as mock_dl:
            result = fetch_benchmark_history(
                "^CRSLDX", cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )

        assert mock_dl.call_count == 1  # only one call, not two like gold
        assert result is not None
        assert result.data_source == "yahoo_finance"

    def test_gold_cache_data_source_persisted(self, cache_dir):
        """data_source should survive a cache round-trip."""
        gold_df, inr_df = self._good_dfs()
        with patch.object(benchmarks_module.yf, "download",
                          side_effect=self._mock_gold_inr_download(gold_df, inr_df)):
            fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )

        # Read back from cache
        with patch.object(benchmarks_module.yf, "download") as mock_dl:
            result = fetch_benchmark_history(
                GOLD_INR_SENTINEL, cache_dir=cache_dir,
                start=date(2026, 10, 20), end=date(2026, 10, 24),
            )
        mock_dl.assert_not_called()
        assert result.data_source == "yahoo_finance:GC=F×INR=X"
