"""Short-lived signed tickets that authorize one scoped PDF upload.

The Python importer mints a ticket after the allowlisted GitHub login is
verified. The separate Node upload-token service verifies it without needing
the session cookie, GitHub credentials, or any parser code. The format is
``base64url(payload_json) + "." + base64url(hmac_sha256(secret, payload_b64))``.
``deploy/vercel/upload-token/ticket.js`` implements the same verification.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

AUDIENCE = "mfhelper-upload"
TICKET_TTL_SECONDS = 120
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MIN_SECRET_LENGTH = 32
UPLOAD_TYPES = {
    "cas_pdf": "application/pdf",
    "groww_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class TicketError(ValueError):
    """The upload ticket is missing, malformed, expired, or not authentic."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _signature(secret: str, payload_b64: str) -> str:
    return _b64encode(hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest())


def _require_secret(secret: str) -> None:
    if not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
        raise TicketError("The upload ticket secret is not configured.")


def mint_ticket(
    secret: str,
    login: str,
    *,
    now: float | None = None,
    ttl_seconds: int = TICKET_TTL_SECONDS,
    max_bytes: int = MAX_UPLOAD_BYTES,
    upload_type: str = "cas_pdf",
) -> str:
    _require_secret(secret)
    if not isinstance(upload_type, str) or upload_type not in UPLOAD_TYPES:
        raise TicketError("The selected upload type is not supported.")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "aud": AUDIENCE,
        "login": login,
        "exp": issued_at + int(ttl_seconds),
        "nonce": secrets.token_urlsafe(16),
        "max_bytes": int(max_bytes),
        "upload_type": upload_type,
    }
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{payload_b64}.{_signature(secret, payload_b64)}"


def verify_ticket(secret: str, ticket: object, *, now: float | None = None) -> dict[str, object]:
    _require_secret(secret)
    if not isinstance(ticket, str) or ticket.count(".") != 1 or len(ticket) > 2048:
        raise TicketError("The upload ticket is invalid.")
    payload_b64, supplied = ticket.split(".")
    if not hmac.compare_digest(_signature(secret, payload_b64), supplied):
        raise TicketError("The upload ticket is invalid.")
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception as exc:
        raise TicketError("The upload ticket is invalid.") from exc
    if not isinstance(payload, dict) or payload.get("aud") != AUDIENCE:
        raise TicketError("The upload ticket is invalid.")
    exp = payload.get("exp")
    current = time.time() if now is None else now
    if not isinstance(exp, int) or isinstance(exp, bool) or current >= exp:
        raise TicketError("The upload ticket has expired. Reload the page and try again.")
    max_bytes = payload.get("max_bytes")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 0 < max_bytes <= MAX_UPLOAD_BYTES:
        raise TicketError("The upload ticket is invalid.")
    upload_type = payload.get("upload_type", "cas_pdf")
    if not isinstance(upload_type, str) or upload_type not in UPLOAD_TYPES:
        raise TicketError("The upload ticket is invalid.")
    return payload
