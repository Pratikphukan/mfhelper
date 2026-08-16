"""Portfolio overlap analyzer for Mutual Funds.

Matches AMFI scheme codes to Tickertape fund IDs using a secure,
fast, sitemap-based ISIN lookup, fetches live stock-level holdings,
and calculates pairwise intersection percentages.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import requests

log = logging.getLogger(__name__)

MAPPINGS_FILE_NAME = "tickertape_mappings.json"


@dataclass(frozen=True)
class HoldingItem:
    company_name: str
    allocation_pct: float
    sid: str | None
    ticker: str | None
    instrument_type: str


def get_tickertape_mappings_path() -> Path:
    """Return the path to save cached tickertape ID mappings."""
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / MAPPINGS_FILE_NAME


def load_cached_mappings(path: Path) -> dict[str, str]:
    """Load cached ISIN-to-mfId mappings from disk."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("Failed to load cached Tickertape mappings: %s", e)
        return {}


def save_cached_mappings(path: Path, mappings: dict[str, str]) -> None:
    """Save ISIN-to-mfId mappings to disk."""
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(mappings, f, indent=2, sort_keys=True)
    except Exception as e:
        log.warning("Failed to save Tickertape mappings: %s", e)


def fetch_isin_from_amfi(codes: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Parse AMFI NAVAll.txt to map AMFI scheme codes to ISINs and names."""
    log.info("Downloading AMFI master file to map scheme codes to ISINs...")
    r = requests.get("https://www.amfiindia.com/spages/NAVAll.txt", timeout=30)
    r.raise_for_status()
    
    code_to_isin = {}
    code_to_name = {}
    
    for line in r.text.splitlines():
        parts = line.strip().split(";")
        if len(parts) == 6:
            c = parts[0].strip()
            if c in codes:
                code_to_isin[c] = parts[1].strip().upper()
                code_to_name[c] = parts[3].strip()
                
    return code_to_isin, code_to_name


def fetch_tickertape_sitemap_urls() -> list[str]:
    """Retrieve all mutual fund page URLs from Tickertape's official sitemap."""
    log.info("Downloading Tickertape mutual funds sitemap...")
    url = "https://www.tickertape.in/sitemaps/mutualfunds/sitemap.xml"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return re.findall(r"<loc>(https://www\.tickertape\.in/mutualfunds/[^<]+)</loc>", r.text)


def resolve_mfid_by_isin(isin: str, fund_name: str, sitemap_urls: list[str]) -> str | None:
    """Find the exact mfId for an ISIN using name fuzzy sorting + /summary validation."""
    import difflib
    
    # Clean and tokenize the fund name
    cleaned_name = fund_name.lower().replace("-", " ").replace("direct", "").replace("plan", "").replace("growth", "").replace("option", "").strip()
    words = [w for w in cleaned_name.split() if len(w) > 2]
    
    candidates = []
    for u in sitemap_urls:
        slug = u.split("/")[-1]
        matches_count = sum(1 for w in words if w in slug.replace("-", " "))
        if matches_count > 0:
            # Tie breaker: string similarity ratio
            ratio = difflib.SequenceMatcher(None, cleaned_name, slug.replace("-", " ")).ratio()
            candidates.append((u, matches_count, ratio))
            
    # Sort descending by matching word count first, then by spelling ratio
    candidates.sort(key=lambda x: (-x[1], -x[2]))
    
    # Validate candidates (test top 12)
    for cand_url, _, _ in candidates[:12]:
        mf_id = cand_url.split("-")[-1]
        try:
            summary_url = f"https://api.tickertape.in/mutualfunds/{mf_id}/summary"
            summary = requests.get(summary_url, timeout=10).json()
            cand_isin = summary.get("data", {}).get("meta", {}).get("isin")
            if cand_isin and cand_isin.strip().upper() == isin.strip().upper():
                log.info("Successfully matched ISIN %s to Tickertape ID %s", isin, mf_id)
                return mf_id
        except Exception:
            continue
            
    return None


def fetch_fund_holdings(mf_id: str) -> list[HoldingItem]:
    """Fetch live stock holdings and allocations for a Tickertape mfId."""
    log.info("Fetching holdings for Tickertape ID %s...", mf_id)
    url = f"https://api.tickertape.in/mutualfunds/{mf_id}/holdings"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    
    raw_holdings = r.json().get("data", {}).get("currentAllocation", [])
    holdings = []
    
    for item in raw_holdings:
        title = item.get("title")
        latest = item.get("latest", 0)
        if title and latest > 0:
            holdings.append(
                HoldingItem(
                    company_name=title,
                    allocation_pct=float(latest),
                    sid=item.get("sid"),
                    ticker=item.get("ticker"),
                    instrument_type=item.get("type", "Equity"),
                )
            )
            
    return holdings


def calculate_overlap_percentage(holdings_a: list[HoldingItem], holdings_b: list[HoldingItem]) -> tuple[float, list[dict]]:
    """Compute the mutual fund portfolio overlap percentage using minimum weights intersection.
    
    Returns the total overlap percent (0-100) and the list of overlapping holdings.
    """
    # Create lookup map for Fund B
    map_b: dict[str, HoldingItem] = {}
    for h in holdings_b:
        # Match by sid if present, else by company_name
        key = h.sid if h.sid else h.company_name.lower().strip()
        map_b[key] = h
        
    overlap_pct = 0.0
    overlapping_details = []
    
    for h_a in holdings_a:
        key_a = h_a.sid if h_a.sid else h_a.company_name.lower().strip()
        if key_a in map_b:
            h_b = map_b[key_a]
            # Minimum allocation intersection
            intersection = min(h_a.allocation_pct, h_b.allocation_pct)
            overlap_pct += intersection
            overlapping_details.append({
                "company_name": h_a.company_name,
                "ticker": h_a.ticker,
                "alloc_a": h_a.allocation_pct,
                "alloc_b": h_b.allocation_pct,
                "intersection": intersection,
            })
            
    # Sort overlapping details descending by intersection
    overlapping_details.sort(key=lambda x: -x["intersection"])
    return round(overlap_pct, 2), overlapping_details
