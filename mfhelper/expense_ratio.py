"""Expense-ratio lookup for Indian mutual funds.

Source: Groww's public fund pages, which embed the full fund payload
(including the current TER) in a ``__NEXT_DATA__`` JSON ``<script>`` tag.
We parse that JSON properly rather than scraping raw HTML, so the only
brittle step is constructing the page URL from a scheme name.

The page URL pattern is ``https://groww.in/mutual-funds/<slug>``. There's
no public API that takes an AMFI scheme code directly, so we synthesize a
slug from the scheme's ``meta.scheme_name`` (returned by ``mfapi.in``)
and try a small set of common variants.

**Critical safety check**: every scraped page is validated by matching its
``direct_scheme_code`` (or ``scheme_code``) field against the AMFI code we
asked for. This prevents slug-collision bugs where a wrong-fund page
("regular" instead of "direct" plan, similarly-named fund, etc.) would
otherwise return a plausible-but-wrong number.

Why this is acceptable: ValueResearch is gated by Cloudflare's anti-bot
JavaScript challenge (HTTP 403 without a real browser). Moneycontrol's
URL-to-fund mapping is opaque (their internal IDs aren't derivable from
AMFI codes). AMFI's own monthly TER disclosure is published as scattered
PDFs/XLS files that change schema between months.

Returns a percent (float). 0.26 means 0.26% annual TER.

Tolerant of failure: returns ``None`` for any error (network, 404,
mis-validation, missing field), and the caller leaves the sheet cell blank.
The user can always paste the value manually in ``analytics_funds.yaml``
via the optional ``expense_ratio:`` key per fund -- that takes precedence
over scraping.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time

import requests

GROWW_FUND_URL = "https://groww.in/mutual-funds/{slug}"
HTTP_TIMEOUT = (10, 20)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL,
)

# Words to strip from a scheme name when generating a URL slug. Groww
# generally drops these from its slugs but keeps them in the displayed
# scheme_name. Order matters: longer phrases first.
_SLUG_NOISE_PHRASES = (
    "growth option",
    "dividend reinvestment",
    "dividend payout",
    "income distribution cum capital withdrawal",
    "idcw",
    "(g)",
    "(d)",
)
_SLUG_NOISE_WORDS = (
    "plan",
    "option",
    "scheme",
    "regular",
    "payout",
    "reinvestment",
)

# Compound-word fixes Groww applies in slugs that simple slugify won't.
_SLUG_COMPOUND_FIXES = (
    ("flexi-cap", "flexicap"),
    ("multi-cap", "multicap"),
    ("mid-cap", "midcap"),
    ("small-cap", "smallcap"),
    ("large-cap", "largecap"),
    ("mid-and-small-cap", "mid-and-smallcap"),
    ("large-and-mid-cap", "large-and-midcap"),
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpenseRatioResult:
    expense_ratio_pct: float
    source: str            # e.g. "groww:<slug>" or "manual"
    fund_name_seen: str    # the scheme_name field on the page we trusted
    aum_crore: float | None = None


# --- slug candidates ---------------------------------------------------------


def _base_slugify(name: str) -> str:
    """Lowercase, strip noise phrases/words, slugify."""
    s = name.lower()
    for phrase in _SLUG_NOISE_PHRASES:
        s = s.replace(phrase, " ")
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _SLUG_NOISE_WORDS]
    return "-".join(tokens)


def _slug_candidates(scheme_name: str) -> list[str]:
    """Generate ordered slug candidates for ``scheme_name``.

    Empirically Groww uses one of a few patterns; we try them in
    descending order of likelihood. The list is de-duplicated while
    preserving order.
    """
    base = _base_slugify(scheme_name)
    candidates = [base]

    for src, dst in _SLUG_COMPOUND_FIXES:
        if src in base:
            candidates.append(base.replace(src, dst))

    if "direct-growth" not in base and "growth-direct" in base:
        candidates.append(base.replace("growth-direct", "direct-growth"))
    if "direct-growth" in base:
        # some pages drop trailing "-fund-" before "-direct-growth"
        candidates.append(re.sub(r"-fund-direct-growth$", "-direct-growth", base))

    seen = set()
    unique: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


# --- fetch & parse -----------------------------------------------------------


def _fetch_groww_page(slug: str) -> str | None:
    url = GROWW_FUND_URL.format(slug=slug)
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt < RETRY_ATTEMPTS:
                wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                log.info(
                    "Groww fetch %s attempt %d/%d failed (%s); retry in %.1fs",
                    slug, attempt, RETRY_ATTEMPTS, type(exc).__name__, wait,
                )
                time.sleep(wait)
                continue
            log.warning("Groww fetch %s failed: %s", slug, exc)
            return None
        if r.status_code == 404:
            return None
        if r.status_code == 200:
            return r.text
        if 500 <= r.status_code < 600 and attempt < RETRY_ATTEMPTS:
            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            log.info(
                "Groww %s HTTP %d (attempt %d/%d); retry in %.1fs",
                slug, r.status_code, attempt, RETRY_ATTEMPTS, wait,
            )
            time.sleep(wait)
            continue
        log.warning("Groww %s returned HTTP %d", slug, r.status_code)
        return None
    return None


def _parse_next_data(html: str) -> dict | None:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (ValueError, json.JSONDecodeError) as exc:
        log.warning("__NEXT_DATA__ JSON parse failed: %s", exc)
        return None


def _extract_from_next_data(
    next_data: dict, *, expected_code: str,
) -> ExpenseRatioResult | None:
    """Return the expense ratio if the page belongs to ``expected_code``."""
    try:
        pp = next_data["props"]["pageProps"]["mfServerSideData"]
    except (KeyError, TypeError):
        return None

    page_codes = {
        str(pp.get(k)).strip()
        for k in ("scheme_code", "direct_scheme_code")
        if pp.get(k) is not None
    }
    if expected_code not in page_codes:
        return None

    raw = pp.get("expense_ratio")
    if raw is None:
        # Fall back to the most recent entry in historic_fund_expense.
        history = pp.get("historic_fund_expense") or []
        if history and isinstance(history, list):
            raw = (history[0] or {}).get("expense_ratio")
    if raw is None:
        return None

    try:
        value = float(str(raw))
    except (TypeError, ValueError):
        return None

    aum_raw = pp.get("aum")
    aum_crore: float | None = None
    if aum_raw is not None:
        try:
            aum_crore = round(float(str(aum_raw)), 2)
        except (TypeError, ValueError):
            pass

    return ExpenseRatioResult(
        expense_ratio_pct=round(value, 2),
        source=f"groww:{pp.get('search_id') or ''}",
        fund_name_seen=str(pp.get("scheme_name") or "").strip(),
        aum_crore=aum_crore,
    )


# --- public API --------------------------------------------------------------


def lookup_expense_ratio(
    *,
    scheme_code: str,
    scheme_name: str,
    slug_hint: str | None = None,
) -> ExpenseRatioResult | None:
    """Look up the current expense ratio for a fund by AMFI scheme code.

    Tries a few URL-slug variants derived from ``scheme_name``. Validates
    each candidate page's ``direct_scheme_code`` / ``scheme_code`` matches
    ``scheme_code`` so a slug collision can't return the wrong fund's data.

    ``slug_hint`` is checked first if provided -- pass the literal Groww
    URL fragment (e.g. ``"jm-multi-strategy-fund-direct-growth"``) for
    funds whose Groww slug uses an old/legacy name that isn't derivable
    from the current AMFI scheme name.

    Returns ``None`` if no candidate yields a code-validated page.
    """
    code = str(scheme_code).strip()
    if not code:
        return None

    candidates = _slug_candidates(scheme_name)
    if slug_hint:
        hint = str(slug_hint).strip()
        if hint:
            candidates = [hint] + [c for c in candidates if c != hint]

    for slug in candidates:
        html = _fetch_groww_page(slug)
        if html is None:
            continue
        next_data = _parse_next_data(html)
        if next_data is None:
            continue
        result = _extract_from_next_data(next_data, expected_code=code)
        if result is not None:
            log.info(
                "Expense ratio for %s = %.2f%% (slug=%r, name='%s')",
                code, result.expense_ratio_pct, slug, result.fund_name_seen,
            )
            return result

    log.info(
        "Could not auto-fetch expense ratio for %s (%s) -- "
        "add 'expense_ratio: <pct>' to analytics_funds.yaml to override.",
        code, scheme_name,
    )
    return None
