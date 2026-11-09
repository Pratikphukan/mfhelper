"""AMFI Quarterly Scheme-wise Average AUM (AAUM) Fetcher and Cache.

Fetches the newest quarterly scheme-wise AAUM from AMFI's official API
(https://www.amfiindia.com/api/average-aum-schemewise) and returns
the exact Direct Growth plan AUM in Crore rupees alongside the formatted
calendar quarter label (e.g. "Jul-Sep 2026").
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import tempfile
from typing import Any

import requests

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "amfi_cache"
DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "quarterly_aaum.json"

AMFI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.amfiindia.com/aum-data/average-aum",
}

MONTH_ABBR = {
    "january": "Jan", "jan": "Jan",
    "february": "Feb", "feb": "Feb",
    "march": "Mar", "mar": "Mar",
    "april": "Apr", "apr": "Apr",
    "may": "May",
    "june": "Jun", "jun": "Jun",
    "july": "Jul", "jul": "Jul",
    "august": "Aug", "aug": "Aug",
    "september": "Sep", "sep": "Sep",
    "october": "Oct", "oct": "Oct",
    "november": "Nov", "nov": "Nov",
    "december": "Dec", "dec": "Dec",
}


def format_quarter_calendar(period_str: str) -> str:
    """Convert AMFI period text to short calendar format.

    Examples:
        "July - September 2026" -> "Jul-Sep 2026"
        "April-June 2025"       -> "Apr-Jun 2025"
        "January - March 2024"  -> "Jan-Mar 2024"
    """
    if not period_str or not isinstance(period_str, str):
        return ""

    text = period_str.strip()
    match = re.search(r"([A-Za-z]+)\s*[-–—]\s*([A-Za-z]+)\s+(\d{4})", text)
    if not match:
        return text

    start_m, end_m, year = match.groups()
    s_abbr = MONTH_ABBR.get(start_m.lower(), start_m[:3].title())
    e_abbr = MONTH_ABBR.get(end_m.lower(), end_m[:3].title())
    return f"{s_abbr}-{e_abbr} {year}"


def fetch_amfi_quarterly_aaum(
    timeout: float = 25.0,
    session: requests.Session | None = None,
) -> tuple[dict[str, float], str]:
    """Fetch the newest quarterly scheme-wise AAUM from AMFI.

    Returns:
        tuple of (aum_by_scheme_code, quarter_label)
        where aum_by_scheme_code maps AMFI code string to AUM in Crore rupees.
    """
    http = session or requests.Session()

    # 1. Discover available financial years and the newest period
    years_url = "https://www.amfiindia.com/api/average-aum-fundwise"
    res_years = http.get(years_url, headers=AMFI_HEADERS, timeout=timeout)
    res_years.raise_for_status()
    years_data = res_years.json()

    periods_data = years_data.get("data", [])
    if isinstance(periods_data, list) and periods_data:
        # data contains the list of financial years, first item is newest
        latest_fy_id = periods_data[0].get("id", 1)
    elif isinstance(periods_data, dict):
        latest_fy_id = 1
    else:
        raise ValueError("Unexpected AMFI financial years response structure")

    # 2. Get the quarters/periods for this newest financial year
    period_url = f"https://www.amfiindia.com/api/average-aum-fundwise?fyId={latest_fy_id}"
    res_period = http.get(period_url, headers=AMFI_HEADERS, timeout=timeout)
    res_period.raise_for_status()
    period_json = res_period.json()

    p_info = period_json.get("data", {})
    periods = p_info.get("periods", [])
    if not periods:
        raise ValueError(f"No quarterly periods found for financial year ID {latest_fy_id}")

    # First period in the list is the newest published quarter
    latest_period = periods[0]
    period_id = latest_period.get("id", 1)
    raw_period_name = latest_period.get("period", "")
    quarter_label = format_quarter_calendar(raw_period_name)

    # 3. Fetch scheme-wise data for all mutual funds in this quarter
    schemewise_url = (
        f"https://www.amfiindia.com/api/average-aum-schemewise"
        f"?strType=Categorywise&fyId={latest_fy_id}&periodId={period_id}&MF_ID=0"
    )
    res_schemes = http.get(schemewise_url, headers=AMFI_HEADERS, timeout=timeout)
    res_schemes.raise_for_status()
    schemes_json = res_schemes.json()

    categories = schemes_json.get("data", [])
    if not isinstance(categories, list):
        raise ValueError("Unexpected schemewise response format from AMFI")

    aum_by_code: dict[str, float] = {}
    for cat in categories:
        for s in cat.get("schemes", []):
            code = s.get("AMFI_Code")
            if not code:
                continue
            code_str = str(code).strip()
            aum_dict = s.get("AverageAumForTheMonth", {})
            if isinstance(aum_dict, dict):
                # AMFI values are reported in ₹ Lakhs. Convert to ₹ Crore (1 Crore = 100 Lakhs).
                excl_dom = float(aum_dict.get("ExcludingFundOfFundsDomesticButIncludingFundOfFundsOverseas", 0.0) or 0.0)
                fof_dom = float(aum_dict.get("FundOfFundsDomestic", 0.0) or 0.0)
                total_lakhs = excl_dom + fof_dom
                if total_lakhs > 0:
                    aum_by_code[code_str] = round(total_lakhs / 100.0, 2)

    return aum_by_code, quarter_label


def get_quarterly_aaum(
    cache_path: Path | None = None,
    max_age_days: int = 7,
    force_refresh: bool = False,
) -> tuple[dict[str, float], str | None]:
    """Load quarterly AAUM mapping from cache or fetch live from AMFI.

    Returns:
        tuple of (aum_by_code, quarter_label).
        If both live fetch and cache are unavailable, returns ({}, None).
    """
    target_cache = cache_path or DEFAULT_CACHE_FILE
    cached_data = _load_cache(target_cache)

    if not force_refresh and cached_data is not None:
        fetched_at_str = cached_data.get("fetched_at")
        if fetched_at_str:
            try:
                fetched_at = datetime.fromisoformat(fetched_at_str)
                age = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 86400.0
                if age < max_age_days:
                    return cached_data.get("aum_by_code", {}), cached_data.get("quarter_label")
            except Exception:
                pass

    # Fetch live
    try:
        aum_by_code, quarter_label = fetch_amfi_quarterly_aaum()
        _save_cache(target_cache, aum_by_code, quarter_label)
        return aum_by_code, quarter_label
    except Exception as exc:
        log.warning("Could not fetch live AMFI quarterly AAUM: %s", exc)
        if cached_data is not None:
            log.info("Using cached AMFI quarterly AAUM from %s", cached_data.get("fetched_at"))
            return cached_data.get("aum_by_code", {}), cached_data.get("quarter_label")
        return {}, None


def _load_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read AAUM cache %s: %s", path, exc)
        return None


def _save_cache(path: Path, aum_by_code: dict[str, float], quarter_label: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "quarter_label": quarter_label,
            "aum_by_code": aum_by_code,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            json.dump(payload, tmp, indent=2)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
    except Exception as exc:
        log.warning("Could not save AAUM cache %s: %s", path, exc)
