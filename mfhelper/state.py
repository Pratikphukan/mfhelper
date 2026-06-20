"""Persistent state for day-change computation.

Stores the most recent NAV observed for each scheme code so that the next
run can compute today's delta without depending on what's in the Google Sheet.

File format (data/last_nav.json):

    {
        "120503": {"nav": 82.4521, "nav_date": "2026-05-05"},
        "118989": {"nav": 118.3402, "nav_date": "2026-05-05"}
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path


@dataclass(frozen=True)
class PrevNav:
    nav: float
    nav_date: date


class LastNavStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, PrevNav]:
        if not self._path.exists():
            return {}
        with self._path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        result: dict[str, PrevNav] = {}
        for code, entry in raw.items():
            result[str(code)] = PrevNav(
                nav=float(entry["nav"]),
                nav_date=date.fromisoformat(entry["nav_date"]),
            )
        return result

    def save(self, snapshot: dict[str, PrevNav]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            code: {"nav": prev.nav, "nav_date": prev.nav_date.isoformat()}
            for code, prev in snapshot.items()
        }
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, sort_keys=True)
        tmp_path.replace(self._path)
