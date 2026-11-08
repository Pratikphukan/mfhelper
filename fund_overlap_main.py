"""Compare one fund with active comparison funds in config/funds.yaml.

Run locally with:

    .venv/bin/python fund_overlap_main.py --fund 120492

The report is printed to the terminal. It does not write to Google Sheets.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from typing import NamedTuple

from mfhelper.config import FundConfig, load_funds
from mfhelper.overlap import (
    HoldingItem,
    calculate_overlap_percentage,
    fetch_fund_holdings,
    fetch_isin_from_amfi,
    fetch_tickertape_sitemap_urls,
    get_tickertape_mappings_path,
    load_cached_mappings,
    resolve_mfid_by_isin,
    save_cached_mappings,
)

PROJECT_ROOT = Path(__file__).resolve().parent
FUNDS_PATH_DEFAULT = PROJECT_ROOT / "config" / "funds.yaml"


class FundComparison(NamedTuple):
    code: str
    name: str
    overlap_pct: float
    shared_count: int
    details: list[dict]


def select_target_and_comparison_funds(
    funds: list[FundConfig], target_code: str
) -> tuple[FundConfig, list[FundConfig]]:
    """Return the requested target and active configured peers.

    The target is selected independently by AMFI code, so it need not be in
    the YAML or active there. The YAML only supplies funds to compare against.
    """
    by_code = {str(fund.code): fund for fund in funds}
    target = by_code.get(target_code) or FundConfig(code=target_code, name=None)

    comparison_funds = [
        fund for fund in funds if fund.active and str(fund.code) != target_code
    ]
    if not comparison_funds:
        raise ValueError("At least one active comparison fund is required.")
    return target, comparison_funds


def compare_target_holdings(
    target_code: str,
    funds: list[FundConfig],
    holdings_by_code: dict[str, list[HoldingItem]],
    names_by_code: dict[str, str],
) -> tuple[list[FundComparison], list[tuple[str, str]]]:
    """Compare available active-fund holdings and return results plus unavailable funds."""
    target_holdings = holdings_by_code.get(target_code)
    if not target_holdings:
        raise ValueError(f"No holdings are available for target AMFI code {target_code}.")

    comparisons: list[FundComparison] = []
    unavailable: list[tuple[str, str]] = []
    for fund in funds:
        code = str(fund.code)
        if code == target_code or not fund.active:
            continue
        other_holdings = holdings_by_code.get(code)
        name = names_by_code.get(code) or fund.name or code
        if not other_holdings:
            unavailable.append((code, name))
            continue
        overlap_pct, details = calculate_overlap_percentage(target_holdings, other_holdings)
        comparisons.append(FundComparison(code, name, overlap_pct, len(details), details[:10]))

    comparisons.sort(key=lambda result: (-result.overlap_pct, result.name.casefold(), result.code))
    return comparisons, unavailable


def print_report(
    target: FundConfig,
    target_name: str,
    active_count: int,
    comparisons: list[FundComparison],
    unavailable: list[tuple[str, str]],
) -> None:
    print(f"Overlap for {target_name} ({target.code})")
    print("Overlap is the shared portfolio weight: for each common stock, MFHelper adds the smaller fund allocation.")
    print(f"Compared with {active_count} active fund(s).\n")

    if comparisons:
        print(f"{'Other fund':<58} {'Overlap':>9} {'Shared stocks':>14}")
        print("-" * 84)
        for result in comparisons:
            label = f"{result.name} ({result.code})"
            print(f"{label[:58]:<58} {result.overlap_pct:>8.2f}% {result.shared_count:>14}")

        print("\nLargest shared-stock contributions:")
        for result in comparisons:
            label = f"{result.name} ({result.code})"
            print(f"\n{label}: {result.overlap_pct:.2f}% total overlap")
            if not result.details:
                print("  No common stock holdings found.")
                continue
            for item in result.details:
                print(
                    f"  {item['company_name']}: {item['intersection']:.2f}% overlap "
                    f"(target {item['alloc_a']:.2f}%, other fund {item['alloc_b']:.2f}%)"
                )
    else:
        print("No other active fund holdings were available for comparison.")

    if unavailable:
        print("\nHoldings unavailable (not counted as 0% overlap):")
        for code, name in unavailable:
            print(f"  {name} ({code})")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fund-overlap",
        description="Compare one AMFI fund code with active funds in funds.yaml.",
    )
    parser.add_argument("--fund", required=True, help="Target fund's AMFI scheme code.")
    parser.add_argument(
        "--funds",
        default=str(FUNDS_PATH_DEFAULT),
        help="Path to funds YAML (default: config/funds.yaml).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args(argv)
    funds_path = Path(args.funds)
    if not funds_path.exists():
        print(f"Funds file not found: {funds_path}", file=sys.stderr)
        return 2

    try:
        all_funds = load_funds(funds_path)
        target, comparison_funds = select_target_and_comparison_funds(
            all_funds, str(args.fund).strip()
        )
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    target_code = str(target.code)
    lookup_funds = [target, *comparison_funds]
    codes = list(dict.fromkeys(str(fund.code) for fund in lookup_funds))
    try:
        code_to_isin, code_to_name = fetch_isin_from_amfi(codes)
    except Exception as exc:
        print(f"Could not fetch the AMFI scheme list: {exc}", file=sys.stderr)
        return 3

    if not code_to_isin.get(target_code):
        print(f"Could not find target AMFI code {target_code} in the AMFI scheme list.", file=sys.stderr)
        return 3

    mappings_path = get_tickertape_mappings_path()
    cached_mappings = load_cached_mappings(mappings_path)
    mapped_ids: dict[str, str] = {}
    sitemap_urls: list[str] | None = None
    unresolved: set[str] = set()

    for fund in lookup_funds:
        code = str(fund.code)
        isin = code_to_isin.get(code)
        if not isin:
            unresolved.add(code)
            continue
        mf_id = cached_mappings.get(isin)
        if not mf_id:
            if sitemap_urls is None:
                try:
                    sitemap_urls = fetch_tickertape_sitemap_urls()
                except Exception as exc:
                    print(f"Could not fetch the Tickertape fund list: {exc}", file=sys.stderr)
                    return 3
            name = fund.name or code_to_name.get(code, code)
            mf_id = resolve_mfid_by_isin(isin, name, sitemap_urls)
            if mf_id:
                cached_mappings[isin] = mf_id
        if mf_id:
            mapped_ids[code] = mf_id
        else:
            unresolved.add(code)

    save_cached_mappings(mappings_path, cached_mappings)

    holdings_by_code: dict[str, list[HoldingItem]] = {}
    for fund in lookup_funds:
        code = str(fund.code)
        mf_id = mapped_ids.get(code)
        if not mf_id:
            continue
        try:
            holdings = fetch_fund_holdings(mf_id)
            if holdings:
                holdings_by_code[code] = holdings
            else:
                unresolved.add(code)
        except Exception as exc:
            logging.warning("Could not fetch holdings for %s (%s): %s", fund.name or code, code, exc)
            unresolved.add(code)

    if not holdings_by_code.get(target_code):
        print(f"Could not fetch holdings for target fund {target.name or target.code} ({target.code}).", file=sys.stderr)
        return 3

    names_by_code = {
        str(fund.code): fund.name or code_to_name.get(str(fund.code), str(fund.code))
        for fund in lookup_funds
    }
    comparisons, unavailable = compare_target_holdings(
        target_code, comparison_funds, holdings_by_code, names_by_code
    )
    unavailable_codes = {code for code, _name in unavailable}
    unavailable.extend(
        (code, names_by_code.get(code, code))
        for code in sorted(unresolved - unavailable_codes - {target_code})
    )
    print_report(target, names_by_code.get(str(target.code), target.name or str(target.code)),
                 len(comparison_funds), comparisons, unavailable)
    return 0 if comparisons else 2


if __name__ == "__main__":
    sys.exit(main())
