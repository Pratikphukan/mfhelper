"""Ordered list of scheme codes represented in the Google Sheet.

The sheet stores fund display names in its merged header -- not scheme codes.
To know which column pair belongs to which scheme code across runs, we keep
a small sidecar state file at ``data/sheet_columns.json``:

    {"columns": ["120503", "118989"]}

The list order matches the sheet's column order. The list is append-only:
new funds are added at the tail, existing positions never move. This keeps
historical data-row cells aligned even as the fund list in ``funds.yaml``
changes over time.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ColumnReconciliation:
    updated: list[str]
    added: list[str]


class SheetColumnStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[str]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        cols = raw.get("columns") or []
        if not isinstance(cols, list):
            raise ValueError(
                f"{self._path}: expected 'columns' to be a list, got {type(cols).__name__}"
            )
        return [str(c) for c in cols]

    def save(self, columns: list[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump({"columns": list(columns)}, f, indent=2)
        tmp_path.replace(self._path)


def reconcile(current: list[str], desired: list[str]) -> ColumnReconciliation:
    """Append codes from ``desired`` that aren't already in ``current``.

    The existing order of ``current`` is preserved exactly. Duplicates in
    ``desired`` are ignored beyond their first occurrence.
    """
    existing = set(current)
    added: list[str] = []
    seen_in_desired: set[str] = set()
    for code in desired:
        if code in existing or code in seen_in_desired:
            continue
        added.append(code)
        seen_in_desired.add(code)
    return ColumnReconciliation(updated=current + added, added=added)
