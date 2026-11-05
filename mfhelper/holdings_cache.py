"""Private, per-user holdings snapshot stored in the Codespaces repository."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from zoneinfo import ZoneInfo

from mfhelper.casl_import import ParsedCas


class CacheError(ValueError):
    """Safe user-facing cache or repository error."""


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOLDINGS_PATH = PROJECT_ROOT / "data" / "private_holdings.json"
_SAFE_REPO_PATH = "data/private_holdings.json"


def snapshot_payload(parsed: ParsedCas) -> dict[str, object]:
    holdings: list[dict[str, object]] = []
    for holding in parsed.holdings:
        holdings.append(
            {
                "isin": holding.isin,
                "scheme_code": holding.scheme_code,
                "scheme_name": holding.scheme_name,
                "units": _decimal_string(holding.units),
                "statement_value_inr": _decimal_string(holding.statement_value),
            }
        )
    return {
        "schema_version": 1,
        "source": "cdsl_cas",
        "statement_date": parsed.statement_date.isoformat(),
        "imported_at": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds"),
        "holdings": holdings,
    }


def save_snapshot_and_push(parsed: ParsedCas) -> str:
    """Atomically write and push the snapshot, returning a safe status string."""
    ensure_import_context()
    _ensure_repo_file_clean()

    payload = snapshot_payload(parsed)
    current = _read_current()
    if current is not None:
        prior_date = _parse_iso_date(current.get("statement_date"))
        if prior_date and parsed.statement_date < prior_date:
            raise CacheError(
                "This statement is older than the saved snapshot, so the cache was left unchanged."
            )
        if prior_date == parsed.statement_date and _holdings_equal(current, payload):
            _push_existing_commit_if_needed()
            return "This statement was already imported; the holdings cache is up to date."

    _ensure_branch_synchronized()
    previous_bytes = HOLDINGS_PATH.read_bytes() if HOLDINGS_PATH.exists() else None
    _atomic_write(payload)
    try:
        _git(["add", "--", _SAFE_REPO_PATH])
        _git(["commit", "--only", "-m", "Update private holdings snapshot", "--", _SAFE_REPO_PATH])
    except CacheError:
        _restore_previous_snapshot(previous_bytes)
        raise CacheError(
            "The holdings were parsed, but GitHub could not commit the snapshot. "
            "The previous snapshot was preserved."
        ) from None

    try:
        _git(["push", "origin", "HEAD"])
    except CacheError:
        # The user can retry by importing the same statement; the duplicate
        # path will push this already-created commit without parsing twice.
        raise CacheError(
            "The snapshot was committed in the Codespace, but could not be pushed to GitHub. "
            "Keep this Codespace open and retry the same statement."
        ) from None

    return f"Imported {len(parsed.holdings)} funds from the statement dated {parsed.statement_date.isoformat()}."


def ensure_import_context() -> None:
    """Reject uploads before handling sensitive input outside the intended repo."""
    _ensure_codespace()
    _ensure_private_repository()
    _ensure_private_codespace_port()


def _decimal_string(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _ensure_codespace() -> None:
    if os.environ.get("CODESPACES", "").lower() != "true":
        raise CacheError("Start this importer in the private Codespace created for this repository.")


def _git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CacheError("GitHub could not update the private repository.") from exc
    if result.returncode != 0:
        raise CacheError("GitHub could not update the private repository.")
    return result.stdout.strip()


def _ensure_private_repository() -> None:
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "visibility", "--jq", ".visibility"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CacheError("GitHub could not confirm this repository is private.") from exc
    if result.returncode != 0 or result.stdout.strip().upper() != "PRIVATE":
        raise CacheError(
            "For privacy, import is available only from a private GitHub repository."
        )


def _ensure_private_codespace_port() -> None:
    codespace_name = os.environ.get("CODESPACE_NAME", "").strip()
    if not codespace_name:
        raise CacheError("The Codespace port visibility could not be verified; no upload was accepted.")
    try:
        result = subprocess.run(
            [
                "gh", "codespace", "ports", "--codespace", codespace_name,
                "--json", "sourcePort,visibility",
                "--jq", '.[] | select(.sourcePort == 8765) | .visibility',
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CacheError("The Codespace port visibility could not be verified; no upload was accepted.") from exc
    if result.returncode != 0 or result.stdout.strip().lower() != "private":
        raise CacheError("Set Codespaces port 8765 to Private before uploading a statement.")


def _ensure_repo_file_clean() -> None:
    status = _git(["status", "--porcelain", "--untracked-files=all", "--", _SAFE_REPO_PATH])
    if status:
        raise CacheError(
            "The holdings snapshot has uncommitted changes. Commit or discard them before importing."
        )


def _branch_sync_counts() -> tuple[int, int]:
    try:
        counts = _git(["rev-list", "--left-right", "--count", "@{u}...HEAD"]).split()
    except CacheError:
        raise CacheError(
            "This Codespace branch has no GitHub upstream. Set one before importing holdings."
        ) from None
    if len(counts) != 2 or not all(value.isdigit() for value in counts):
        raise CacheError("The Codespace branch status could not be verified; no snapshot was changed.")
    behind, ahead = (int(value) for value in counts)
    return behind, ahead


def _ensure_branch_synchronized() -> None:
    behind, ahead = _branch_sync_counts()
    if behind or ahead:
        raise CacheError(
            "The Codespace branch has local or remote commits not synchronized with GitHub. "
            "Synchronize it before importing so no unrelated commits are pushed."
        )


def _push_existing_commit_if_needed() -> None:
    # A failed previous push can be retried only when HEAD is exactly one
    # snapshot-only commit on top of its upstream. Never push arbitrary commits.
    behind, ahead = _branch_sync_counts()
    if ahead == 0 and behind == 0:
        return
    if behind or ahead != 1:
        raise CacheError(
            "The Codespace branch has unrelated or divergent commits. "
            "Synchronize it manually before retrying the import."
        )

    upstream = _git(["rev-parse", "@{u}"])
    parent = _git(["rev-parse", "HEAD^"])
    changed_paths = _git(["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"]).splitlines()
    if parent != upstream or changed_paths != [_SAFE_REPO_PATH]:
        raise CacheError(
            "The unpushed commit is not limited to the holdings snapshot. "
            "Review and synchronize the branch manually before retrying."
        )
    _git(["push", "origin", "HEAD"])


def _read_current() -> dict[str, object] | None:
    if not HOLDINGS_PATH.exists():
        return None
    try:
        data = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheError("The existing holdings snapshot could not be read; it was left unchanged.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("holdings"), list):
        raise CacheError("The existing holdings snapshot has an unsupported format; it was left unchanged.")
    return data


def _parse_iso_date(value: object):
    if not isinstance(value, str):
        return None
    try:
        from datetime import date

        return date.fromisoformat(value)
    except ValueError:
        return None


def _holdings_equal(old: dict[str, object], new: dict[str, object]) -> bool:
    def canonical(payload: dict[str, object]) -> list[tuple[str, str, str, str, str]]:
        rows = payload.get("holdings")
        if not isinstance(rows, list):
            return []
        normalized: list[tuple[str, str, str, str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized.append(
                (
                    str(row.get("isin") or ""),
                    str(row.get("scheme_code") or ""),
                    re.sub(r"\s+", " ", str(row.get("scheme_name") or "")).strip().casefold(),
                    str(row.get("units") or ""),
                    str(row.get("statement_value_inr") or ""),
                )
            )
        return sorted(normalized)

    return canonical(old) == canonical(new)


def _atomic_write(payload: dict[str, object]) -> None:
    HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=HOLDINGS_PATH.parent,
            prefix=".private_holdings.", suffix=".tmp", delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(encoded)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, HOLDINGS_PATH)
    except OSError as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise CacheError("The holdings snapshot could not be saved; the previous one was preserved.") from exc


def _restore_previous_snapshot(previous: bytes | None) -> None:
    try:
        subprocess.run(
            ["git", "restore", "--staged", "--", _SAFE_REPO_PATH],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if previous is None:
            HOLDINGS_PATH.unlink(missing_ok=True)
        else:
            HOLDINGS_PATH.write_bytes(previous)
    except OSError:
        # Keep the primary error safe and user-facing. A failed rollback is
        # highly unusual; the repository status will make it visible.
        pass
