"""Tests for mfhelper.mfapi cache logic.

All tests use a temporary directory for the cache so they never touch
data/mfapi_cache/ and never make real HTTP calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import mfhelper.mfapi as mfapi_module
from mfhelper.mfapi import (
    MfapiResult,
    NavHistoryPoint,
    _read_cache,
    _write_cache,
    _parse_history,
    fetch_history,
    CACHE_TTL_HOURS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RAW_DATA = [
    {"date": "24-10-2026", "nav": "112.21"},
    {"date": "23-10-2026", "nav": "110.20"},
    {"date": "22-10-2026", "nav": "108.57"},
]

SAMPLE_SCHEME_NAME = "JM Flexi Cap Fund - Direct Plan - Growth Option"
SAMPLE_CODE = "120492"


@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path, monkeypatch):
    """Redirect all cache reads/writes to a temp directory."""
    monkeypatch.setattr(mfapi_module, "CACHE_DIR", tmp_path)
    return tmp_path


def _make_cache_file(
    tmp_path: Path,
    code: str,
    raw_data: list[dict],
    scheme_name: str,
    age_hours: float = 0,
) -> Path:
    """Write a cache file with a controllable age."""
    fetched_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    payload = {
        "fetched_at": fetched_at.isoformat(),
        "scheme_name": scheme_name,
        "data": raw_data,
    }
    cache_path = tmp_path / f"{code}.json"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return cache_path


# ---------------------------------------------------------------------------
# _parse_history
# ---------------------------------------------------------------------------

class TestParseHistory:
    def test_parses_valid_entries(self):
        history = _parse_history(SAMPLE_RAW_DATA)
        assert len(history) == 3
        assert history[0].nav == 112.21
        assert history[0].nav_date.isoformat() == "2026-10-24"

    def test_skips_invalid_entries(self):
        raw = [
            {"date": "24-10-2026", "nav": "112.21"},
            {"date": "bad-date", "nav": "99.99"},
            {"date": "23-10-2026", "nav": "not-a-number"},
        ]
        history = _parse_history(raw)
        assert len(history) == 1
        assert history[0].nav == 112.21

    def test_empty_input(self):
        assert _parse_history([]) == []


# ---------------------------------------------------------------------------
# _write_cache / _read_cache
# ---------------------------------------------------------------------------

class TestWriteCache:
    def test_creates_cache_file(self, tmp_path):
        _write_cache(SAMPLE_CODE, SAMPLE_SCHEME_NAME, SAMPLE_RAW_DATA)
        cache_path = tmp_path / f"{SAMPLE_CODE}.json"
        assert cache_path.exists()

    def test_cache_file_content(self, tmp_path):
        _write_cache(SAMPLE_CODE, SAMPLE_SCHEME_NAME, SAMPLE_RAW_DATA)
        payload = json.loads((tmp_path / f"{SAMPLE_CODE}.json").read_text())
        assert payload["scheme_name"] == SAMPLE_SCHEME_NAME
        assert payload["data"] == SAMPLE_RAW_DATA
        assert "fetched_at" in payload

    def test_atomic_write_no_tmp_left(self, tmp_path):
        _write_cache(SAMPLE_CODE, SAMPLE_SCHEME_NAME, SAMPLE_RAW_DATA)
        assert not (tmp_path / f"{SAMPLE_CODE}.tmp").exists()


class TestReadCache:
    def test_returns_none_when_no_file(self):
        assert _read_cache("999999") is None

    def test_returns_result_for_fresh_cache(self, tmp_path):
        _make_cache_file(tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME, age_hours=1)
        result = _read_cache(SAMPLE_CODE)
        assert result is not None
        assert result.scheme_name == SAMPLE_SCHEME_NAME
        assert len(result.history) == 3

    def test_returns_none_for_stale_cache(self, tmp_path):
        _make_cache_file(
            tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME,
            age_hours=CACHE_TTL_HOURS + 1,
        )
        assert _read_cache(SAMPLE_CODE) is None

    def test_returns_none_for_exactly_ttl_boundary(self, tmp_path):
        # At exactly TTL hours it should be considered stale (> not >=).
        _make_cache_file(
            tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME,
            age_hours=CACHE_TTL_HOURS,
        )
        assert _read_cache(SAMPLE_CODE) is None

    def test_returns_none_for_corrupt_file(self, tmp_path):
        cache_path = tmp_path / f"{SAMPLE_CODE}.json"
        cache_path.write_text("not valid json", encoding="utf-8")
        assert _read_cache(SAMPLE_CODE) is None

    def test_returns_none_for_empty_history_in_cache(self, tmp_path):
        _make_cache_file(tmp_path, SAMPLE_CODE, [], SAMPLE_SCHEME_NAME, age_hours=0)
        assert _read_cache(SAMPLE_CODE) is None

    def test_history_order_preserved(self, tmp_path):
        _make_cache_file(tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME)
        result = _read_cache(SAMPLE_CODE)
        assert result.history[0].nav == 112.21  # newest first
        assert result.history[-1].nav == 108.57


# ---------------------------------------------------------------------------
# fetch_history (integration of cache + API mock)
# ---------------------------------------------------------------------------

MOCK_API_RESPONSE = {
    "status": "SUCCESS",
    "meta": {"scheme_name": SAMPLE_SCHEME_NAME},
    "data": SAMPLE_RAW_DATA,
}


def _mock_fetch_payload(url, **kwargs):
    return MOCK_API_RESPONSE


class TestFetchHistory:
    def test_cache_miss_calls_api(self, tmp_path):
        with patch.object(mfapi_module, "_fetch_payload", side_effect=_mock_fetch_payload) as mock_api:
            result = fetch_history(SAMPLE_CODE)
        mock_api.assert_called_once()
        assert result is not None
        assert len(result.history) == 3

    def test_cache_miss_writes_cache(self, tmp_path):
        with patch.object(mfapi_module, "_fetch_payload", side_effect=_mock_fetch_payload):
            fetch_history(SAMPLE_CODE)
        assert (tmp_path / f"{SAMPLE_CODE}.json").exists()

    def test_cache_hit_skips_api(self, tmp_path):
        _make_cache_file(tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME, age_hours=1)
        with patch.object(mfapi_module, "_fetch_payload", side_effect=_mock_fetch_payload) as mock_api:
            result = fetch_history(SAMPLE_CODE)
        mock_api.assert_not_called()
        assert result is not None
        assert len(result.history) == 3

    def test_stale_cache_calls_api(self, tmp_path):
        _make_cache_file(
            tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME,
            age_hours=CACHE_TTL_HOURS + 1,
        )
        with patch.object(mfapi_module, "_fetch_payload", side_effect=_mock_fetch_payload) as mock_api:
            result = fetch_history(SAMPLE_CODE)
        mock_api.assert_called_once()
        assert result is not None

    def test_limit_slices_from_cache(self, tmp_path):
        _make_cache_file(tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME, age_hours=1)
        result = fetch_history(SAMPLE_CODE, limit=2)
        assert len(result.history) == 2
        assert result.history[0].nav == 112.21  # still newest first

    def test_limit_slices_from_api(self, tmp_path):
        with patch.object(mfapi_module, "_fetch_payload", side_effect=_mock_fetch_payload):
            result = fetch_history(SAMPLE_CODE, limit=2)
        assert len(result.history) == 2

    def test_full_history_cached_even_with_limit(self, tmp_path):
        """A limited fetch must still cache the full history."""
        with patch.object(mfapi_module, "_fetch_payload", side_effect=_mock_fetch_payload):
            fetch_history(SAMPLE_CODE, limit=1)
        payload = json.loads((tmp_path / f"{SAMPLE_CODE}.json").read_text())
        assert len(payload["data"]) == 3  # full 3 points cached, not just 1

    def test_returns_none_when_api_fails(self, tmp_path):
        with patch.object(mfapi_module, "_fetch_payload", return_value=None):
            result = fetch_history(SAMPLE_CODE)
        assert result is None

    def test_returns_none_when_api_returns_empty_data(self, tmp_path):
        with patch.object(mfapi_module, "_fetch_payload", return_value={"data": [], "meta": {}}):
            result = fetch_history(SAMPLE_CODE)
        assert result is None

    def test_scheme_name_from_cache(self, tmp_path):
        _make_cache_file(tmp_path, SAMPLE_CODE, SAMPLE_RAW_DATA, SAMPLE_SCHEME_NAME, age_hours=1)
        result = fetch_history(SAMPLE_CODE)
        assert result.scheme_name == SAMPLE_SCHEME_NAME

    def test_second_call_is_cache_hit(self, tmp_path):
        """Simulate main.py then returns_main.py in the same run."""
        with patch.object(mfapi_module, "_fetch_payload", side_effect=_mock_fetch_payload) as mock_api:
            fetch_history(SAMPLE_CODE)          # main.py — cache miss
            fetch_history(SAMPLE_CODE)          # returns_main.py — cache hit
        assert mock_api.call_count == 1         # API called only once
