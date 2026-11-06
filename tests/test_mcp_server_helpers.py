"""Offline tests for the MFHelper MCP adapter helpers."""
from datetime import date
from dataclasses import dataclass

import pytest

from agent.mfhelper_mcp_server import _dump, _jsonable, _validated_code


@dataclass
class Example:
    name: str
    as_of: date


def test_validated_code_preserves_leading_zeroes():
    assert _validated_code(" 001234 ") == "001234"


@pytest.mark.parametrize("value", ["", "12", "abc123", "123456789", "12 345"])
def test_validated_code_rejects_invalid_codes(value):
    with pytest.raises(ValueError):
        _validated_code(value)


def test_jsonable_converts_dataclasses_and_dates():
    assert _jsonable(Example("fund", date(2026, 10, 30))) == {
        "name": "fund",
        "as_of": "2026-10-30",
    }


def test_dump_is_valid_json():
    payload = {"date": date(2026, 10, 30), "metric": None}
    assert '"date": "2026-10-30"' in _dump(payload)
