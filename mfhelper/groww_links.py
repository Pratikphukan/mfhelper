"""Read and validate per-fund Groww page URLs from the private Fund Code Map sheet."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit

from mfhelper.groww_holdings_sheet import FUND_CODE_MAP_TAB_NAME, _validated_sheet_code

GROWW_MUTUAL_FUNDS_URL = "https://groww.in/mutual-funds"
GROWW_URL_HEADERS = ("Scheme Name", "AMFI Scheme Code", "Groww URL")
_GROWW_PATH_RE = re.compile(r"^/(?:mutual-funds|etfs)/[A-Za-z0-9._-]+/?$", re.IGNORECASE)


class GrowwUrlMapError(ValueError):
    """The Fund Code Map could not provide safe Groww links."""


def validate_groww_url(value: object) -> str:
    """Return a safe canonical Groww fund/ETF URL or raise ``ValueError``."""
    if not isinstance(value, str):
        raise ValueError("Groww URL must be text")
    url = value.strip()
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Groww URL is malformed") from exc
    if (
        parsed.scheme.lower() != "https"
        or host is None
        or host.lower() not in {"groww.in", "www.groww.in"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not _GROWW_PATH_RE.fullmatch(parsed.path)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("URL must be an HTTPS Groww mutual-fund or ETF page")
    clean_path = parsed.path.rstrip("/")
    return f"https://groww.in{clean_path}"


def parse_groww_url_map_rows(rows) -> dict[str, str]:
    """Validate Fund Code Map rows and return AMFI scheme code -> Groww URL."""
    values = [list(row) for row in rows]
    if not values or tuple(str(v or "").strip() for v in values[0][:3]) != GROWW_URL_HEADERS:
        raise GrowwUrlMapError(
            "Fund Code Map must have Scheme Name, AMFI Scheme Code, and Groww URL headers."
        )

    links: dict[str, str] = {}
    for row_number, row in enumerate(values[1:], start=2):
        name = str(row[0]).strip() if len(row) > 0 and row[0] is not None else ""
        raw_code = row[1] if len(row) > 1 else ""
        raw_url = row[2] if len(row) > 2 else ""
        url_text = str(raw_url).strip() if raw_url is not None else ""
        if not name and not str(raw_code or "").strip() and not url_text:
            continue
        if not name:
            raise GrowwUrlMapError(f"Fund Code Map row {row_number} is missing a scheme name.")
        try:
            code = _validated_sheet_code(raw_code)
        except ValueError as exc:
            raise GrowwUrlMapError(f"Fund Code Map row {row_number} has an invalid AMFI code.") from exc
        if not url_text:
            continue  # Missing individual URL uses the caller's general-page fallback.
        try:
            url = validate_groww_url(raw_url)
        except ValueError as exc:
            raise GrowwUrlMapError(f"Fund Code Map row {row_number} has an invalid Groww URL.") from exc
        prior = links.get(code)
        if prior is not None and prior != url:
            raise GrowwUrlMapError(f"Fund Code Map has conflicting Groww URLs for AMFI code {code}.")
        links[code] = url
    return links


def read_groww_url_map(
    *,
    spreadsheet_id: str,
    credentials_path: Path,
    token_path: Path,
    client_factory=None,
) -> dict[str, str]:
    """Read the Groww URL map using the same Google Sheets authorization as daily runs."""
    try:
        if client_factory is None:
            import gspread
            from mfhelper.sheets import _load_credentials

            credentials = _load_credentials(credentials_path, token_path)
            client = gspread.authorize(credentials)
        else:
            client = client_factory(credentials_path, token_path)
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(FUND_CODE_MAP_TAB_NAME)
        return parse_groww_url_map_rows(
            worksheet.get("A:C", value_render_option="UNFORMATTED_VALUE")
        )
    except GrowwUrlMapError:
        raise
    except Exception as exc:
        raise GrowwUrlMapError("Could not read the Fund Code Map from Google Sheets.") from exc
