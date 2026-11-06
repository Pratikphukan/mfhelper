"""Private Vercel Blob storage for one user's temporary CAS PDF and current snapshot.

Authentication is OIDC (``BLOB_STORE_ID`` + the Vercel-issued token) by default,
so no long-lived read-write token is needed in the Python service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re

from mfhelper.casl_import import ParsedCas
from mfhelper.holdings_cache import _holdings_equal, _parse_iso_date, snapshot_payload
from mfhelper.upload_ticket import MAX_UPLOAD_BYTES


class VercelStorageError(ValueError):
    """Safe user-facing Vercel Blob storage error."""


ACCESS = "private"
SNAPSHOT_PATH = "holdings/current.json"
TEMP_PREFIX = "tmp/"
TEMP_PATHNAME_RE = re.compile(r"^tmp/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.pdf$")
CLAIM_PATHNAME_RE = re.compile(r"^tmp/used-tickets/[A-Za-z0-9_-]{16,64}\.json$")
STALE_AFTER = timedelta(minutes=15)
# Vercel Blob's minimum cache lifetime; limits how long a stale snapshot can be read.
SNAPSHOT_CACHE_SECONDS = 60


def _load_blob():
    try:
        from vercel import blob
    except Exception as exc:  # pragma: no cover - depends on deployment packaging
        raise VercelStorageError("The Vercel Blob client is not installed on this worker.") from exc
    return blob


class VercelHoldingsStore:
    def __init__(self, blob=None):
        self.blob = blob if blob is not None else _load_blob()

    @staticmethod
    def validate_temp_pathname(pathname: object) -> str:
        """Accept only server-issued ``tmp/<name>.pdf`` pathnames."""
        if not isinstance(pathname, str) or not TEMP_PATHNAME_RE.fullmatch(pathname):
            raise VercelStorageError("The uploaded file reference is invalid. Upload the statement again.")
        return pathname

    async def read_temp_pdf(self, pathname: str) -> bytes:
        pathname = self.validate_temp_pathname(pathname)
        try:
            head = await self.blob.head_blob(pathname)
        except Exception as exc:
            if self._is_not_found(exc):
                raise VercelStorageError("The uploaded statement was not found. Upload it again.") from exc
            raise VercelStorageError("The uploaded statement could not be read.") from exc
        size = getattr(head, "size", None)
        if not isinstance(size, int) or size <= 0 or size > MAX_UPLOAD_BYTES:
            raise VercelStorageError("The PDF is too large (maximum 25 MB) or empty.")
        try:
            result = await self.blob.get_blob(pathname, access=ACCESS)
        except Exception as exc:
            raise VercelStorageError("The uploaded statement could not be read.") from exc
        body = bytes(result.body)
        if len(body) > MAX_UPLOAD_BYTES:
            raise VercelStorageError("The PDF is too large (maximum 25 MB) or empty.")
        return body

    async def delete_temp(self, pathname: object) -> bool:
        """Best-effort delete of a temporary PDF; never raises."""
        try:
            await self.blob.delete_blob(self.validate_temp_pathname(pathname))
            return True
        except Exception:
            return False

    async def delete_claim_marker(self, pathname: object) -> bool:
        """Best-effort delete of a temporary upload-ticket claim marker."""
        if not isinstance(pathname, str) or not CLAIM_PATHNAME_RE.fullmatch(pathname):
            return False
        try:
            await self.blob.delete_blob(pathname)
            return True
        except Exception:
            return False

    async def cleanup_stale(self, *, now: datetime | None = None) -> int:
        """Delete stale temporary PDFs and ticket claims. Best effort; never raises."""
        cutoff = (now or datetime.now(timezone.utc)) - STALE_AFTER
        removed = 0
        try:
            stale_pdfs: list[str] = []
            stale_claims: list[str] = []
            async for item in self.blob.query_blobs(prefix=TEMP_PREFIX):
                uploaded_at = getattr(item, "uploaded_at", None)
                pathname = getattr(item, "pathname", None)
                if not isinstance(pathname, str) or not isinstance(uploaded_at, datetime):
                    continue
                if uploaded_at.tzinfo is None:
                    uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
                if uploaded_at >= cutoff:
                    continue
                if TEMP_PATHNAME_RE.fullmatch(pathname):
                    stale_pdfs.append(pathname)
                elif CLAIM_PATHNAME_RE.fullmatch(pathname):
                    stale_claims.append(pathname)
            for pathname in stale_pdfs:
                if await self.delete_temp(pathname):
                    removed += 1
            for pathname in stale_claims:
                if await self.delete_claim_marker(pathname):
                    removed += 1
        except Exception:
            return removed
        return removed

    async def save_snapshot(self, parsed: ParsedCas) -> str:
        payload = snapshot_payload(parsed)
        current = await self._read_current()
        if current is not None:
            prior_date = _parse_iso_date(current.get("statement_date"))
            if prior_date and parsed.statement_date < prior_date:
                raise VercelStorageError(
                    "This statement is older than the saved snapshot, so the cache was left unchanged."
                )
            if prior_date == parsed.statement_date and _holdings_equal(current, payload):
                return "This statement was already imported; the holdings snapshot is up to date."

        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        try:
            await self.blob.put_blob(
                SNAPSHOT_PATH,
                encoded,
                access=ACCESS,
                content_type="application/json; charset=utf-8",
                allow_overwrite=True,
                add_random_suffix=False,
                cache_control_max_age=SNAPSHOT_CACHE_SECONDS,
            )
        except Exception as exc:
            raise VercelStorageError(
                "The holdings snapshot could not be saved; the previous snapshot was preserved."
            ) from exc
        return f"Imported {len(parsed.holdings)} funds from the statement dated {parsed.statement_date.isoformat()}."

    async def _read_current(self) -> dict[str, object] | None:
        try:
            result = await self.blob.get_blob(SNAPSHOT_PATH, access=ACCESS)
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise VercelStorageError(
                "The existing holdings snapshot could not be read; it was left unchanged."
            ) from exc
        try:
            payload = json.loads(bytes(result.body).decode("utf-8"))
        except Exception as exc:
            raise VercelStorageError(
                "The existing holdings snapshot has an unsupported format; it was left unchanged."
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("holdings"), list):
            raise VercelStorageError(
                "The existing holdings snapshot has an unsupported format; it was left unchanged."
            )
        return payload

    def _is_not_found(self, exc: Exception) -> bool:
        not_found = getattr(self.blob, "BlobNotFoundError", None)
        return isinstance(not_found, type) and isinstance(exc, not_found)
