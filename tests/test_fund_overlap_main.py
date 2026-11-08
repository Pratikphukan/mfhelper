import pytest

from fund_overlap_main import compare_target_holdings, select_target_and_comparison_funds
from mfhelper.config import FundConfig
from mfhelper.overlap import HoldingItem


def holding(name, weight, sid):
    return HoldingItem(name, weight, sid, None, "Equity")


def test_selects_active_configured_peers_and_removes_target_from_peers():
    funds = [
        FundConfig("1001", "Target", active=True),
        FundConfig("1002", "Peer", active=True),
        FundConfig("1003", "Old fund", active=False),
    ]

    target, peers = select_target_and_comparison_funds(funds, "1001")

    assert target.code == "1001"
    assert [fund.code for fund in peers] == ["1002"]


def test_target_can_be_absent_from_yaml():
    funds = [
        FundConfig("1001", "Target", active=True),
        FundConfig("1002", "Inactive", active=False),
    ]

    target, peers = select_target_and_comparison_funds(funds, "9999")

    assert target.code == "9999"
    assert target.name is None
    assert [fund.code for fund in peers] == ["1001"]


def test_inactive_configured_target_can_still_be_selected():
    funds = [
        FundConfig("1001", "Inactive target", active=False),
        FundConfig("1002", "Active peer", active=True),
    ]

    target, peers = select_target_and_comparison_funds(funds, "1001")

    assert target.code == "1001"
    assert [fund.code for fund in peers] == ["1002"]


def test_select_target_requires_at_least_one_active_peer():
    funds = [
        FundConfig("1001", "Target", active=True),
        FundConfig("1002", "Inactive", active=False),
    ]

    with pytest.raises(ValueError, match="At least one active comparison fund"):
        select_target_and_comparison_funds(funds, "1001")


def test_comparisons_are_ranked_and_missing_holdings_are_reported():
    funds = [
        FundConfig("1001", "Target", active=True),
        FundConfig("1002", "Higher overlap", active=True),
        FundConfig("1003", "Lower overlap", active=True),
        FundConfig("1004", "Unavailable", active=True),
        FundConfig("1005", "Inactive", active=False),
    ]
    holdings = {
        "1001": [holding("Stock A", 10.0, "A"), holding("Stock B", 4.0, "B")],
        "1002": [holding("Stock A", 7.0, "A"), holding("Stock B", 2.0, "B")],
        "1003": [holding("Stock A", 3.0, "A")],
    }

    comparisons, unavailable = compare_target_holdings(
        "1001", funds, holdings, {fund.code: fund.name for fund in funds}
    )

    assert [(row.code, row.overlap_pct, row.shared_count) for row in comparisons] == [
        ("1002", 9.0, 2),
        ("1003", 3.0, 1),
    ]
    assert unavailable == [("1004", "Unavailable")]
    assert all(row.code != "1005" for row in comparisons)


def test_comparison_requires_target_holdings():
    funds = [FundConfig("1001", "Target"), FundConfig("1002", "Peer")]
    with pytest.raises(ValueError, match="No holdings are available for target"):
        compare_target_holdings("1001", funds, {}, {})
