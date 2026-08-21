"""Fetch and parse AMFI's daily NAV file.

Source: https://www.amfiindia.com/spages/NAVAll.txt

The file is a semicolon-delimited text dump with AMC and scheme-category
section headers interspersed between data rows. A data row has 6 fields:

    Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;\
Scheme Name;Net Asset Value;Date

Dates are formatted like "02-May-2026". NAV can be "N.A." for funds that
didn't publish on a given day -- those rows are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging

import requests

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
HTTP_TIMEOUT_SECONDS = 30

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NavRecord:
    scheme_code: str
    scheme_name: str
    nav: float
    nav_date: date


def fetch_nav_text(url: str = AMFI_NAV_URL, timeout: int = HTTP_TIMEOUT_SECONDS) -> str:
    log.info("Downloading AMFI NAV file from %s", url)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_nav_text(text: str) -> dict[str, NavRecord]:
    records: dict[str, NavRecord] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(";")
        if len(parts) < 6:
            continue
        scheme_code = parts[0].strip()
        if not scheme_code.isdigit():
            continue

        scheme_name = parts[3].strip()
        nav_str = parts[-2].strip()
        date_str = parts[-1].strip()

        try:
            nav = float(nav_str)
        except ValueError:
            continue

        try:
            nav_date = datetime.strptime(date_str, "%d-%b-%Y").date()
        except ValueError:
            log.warning("Skipping scheme %s: could not parse date %r", scheme_code, date_str)
            continue

        records[scheme_code] = NavRecord(
            scheme_code=scheme_code,
            scheme_name=scheme_name,
            nav=nav,
            nav_date=nav_date,
        )
    return records


def fetch_and_parse() -> dict[str, NavRecord]:
    return parse_nav_text(fetch_nav_text())
