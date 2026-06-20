"""Writes per-fund returns JSON files atomically.

Each fund's metrics land in ``data/fund_returns/{code}.json``. The
write is atomic (write-to-tmp + rename) so an interrupted run never
leaves a half-written file behind, and a re-run never sees a torn
file mid-write.

The directory is created on demand. Callers don't need to mkdir first.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path


def _json_default(obj: object) -> object:
    """Serialize dates / datetimes as ISO strings; let everything else
    fall through to the default error path (so we don't silently swallow
    unexpected types)."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )


class FundReturnsWriter:
    """Writes one ``{code}.json`` per fund, atomically."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def write(self, code: str, payload: dict) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"{code}.json"
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(
                payload, f,
                indent=2, ensure_ascii=False,
                default=_json_default, sort_keys=False,
            )
            f.write("\n")
        tmp_path.replace(path)
        return path
