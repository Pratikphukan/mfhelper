"""Tests for fund YAML configuration validation."""

from __future__ import annotations

import pytest

from mfhelper.config import load_funds


def _load_funds(tmp_path, content: str):
    config_path = tmp_path / "funds.yaml"
    config_path.write_text(content, encoding="utf-8")
    return load_funds(config_path)


def test_load_funds_accepts_boolean_active_and_valid_numbers(tmp_path):
    funds = _load_funds(
        tmp_path,
        """
funds:
  - code: "12345"
    active: false
    weight: 0
    expense_ratio: 0.75
  - code: "67890"
    active: true
    weight: 12.5
    expense_ratio: 0
""",
    )

    assert [fund.active for fund in funds] == [False, True]
    assert [fund.weight for fund in funds] == [0.0, 12.5]
    assert [fund.expense_ratio_pct for fund in funds] == [0.75, 0.0]


def test_load_funds_defaults_active_and_optional_numbers(tmp_path):
    funds = _load_funds(tmp_path, 'funds:\n  - code: "12345"\n')

    assert funds[0].active is True
    assert funds[0].weight is None
    assert funds[0].expense_ratio_pct is None


@pytest.mark.parametrize("yaml_value", ['"false"', '"true"', "null", "1"])
def test_load_funds_rejects_non_boolean_active(tmp_path, yaml_value):
    with pytest.raises(ValueError, match="field 'active' must be a YAML boolean"):
        _load_funds(
            tmp_path,
            f'funds:\n  - code: "12345"\n    active: {yaml_value}\n',
        )


@pytest.mark.parametrize("field", ["weight", "expense_ratio"])
@pytest.mark.parametrize("yaml_value", ["-1", ".nan", ".inf", '"not-a-number"', "true"])
def test_load_funds_rejects_invalid_numeric_values(tmp_path, field, yaml_value):
    with pytest.raises(ValueError, match=f"field '{field}' must be a finite, non-negative number"):
        _load_funds(
            tmp_path,
            f'funds:\n  - code: "12345"\n    {field}: {yaml_value}\n',
        )


@pytest.mark.parametrize("field", ["weight", "expense_ratio"])
def test_load_funds_accepts_numeric_strings(tmp_path, field):
    funds = _load_funds(
        tmp_path,
        f'funds:\n  - code: "12345"\n    {field}: "1.25"\n',
    )

    value = funds[0].weight if field == "weight" else funds[0].expense_ratio_pct
    assert value == 1.25


def test_load_funds_prefers_private_override(tmp_path):
    public_file = tmp_path / "funds.yaml"
    public_file.write_text('funds:\n  - code: "11111"\n', encoding="utf-8")
    private_file = tmp_path / "funds.private.yaml"
    private_file.write_text('funds:\n  - code: "22222"\n', encoding="utf-8")

    funds = load_funds(public_file)
    assert len(funds) == 1
    assert funds[0].code == "22222"
