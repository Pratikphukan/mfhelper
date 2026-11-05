"""Private OCI Object Storage cache for one user's current CAS snapshot."""

from __future__ import annotations

from io import BytesIO
import json
import os

from mfhelper.casl_import import ParsedCas
from mfhelper.holdings_cache import _holdings_equal, _parse_iso_date, snapshot_payload


class OCIStorageError(ValueError):
    """Safe user-facing OCI storage error."""


OBJECT_NAME = "holdings/current.json"


class OCIHoldingsCache:
    def __init__(self, client, namespace: str, bucket_name: str):
        self.client = client
        self.namespace = namespace
        self.bucket_name = bucket_name

    @classmethod
    def from_environment(cls) -> "OCIHoldingsCache":
        """Build an OCI client using the VM's instance principal (no API key file)."""
        region = os.environ.get("OCI_REGION", "").strip()
        namespace = os.environ.get("OCI_NAMESPACE", "").strip()
        bucket_name = os.environ.get("OCI_BUCKET_NAME", "").strip()
        if not region or not namespace or not bucket_name:
            raise OCIStorageError("OCI Object Storage is not configured on this worker.")
        try:
            import oci

            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            client = oci.object_storage.ObjectStorageClient({"region": region}, signer=signer)
        except Exception as exc:
            raise OCIStorageError("The worker could not authenticate with OCI Object Storage.") from exc
        return cls(client, namespace, bucket_name)

    def ensure_private_bucket(self) -> None:
        """Require a private bucket with versioning disabled before accepting uploads."""
        try:
            bucket = self.client.get_bucket(self.namespace, self.bucket_name).data
        except Exception as exc:
            raise OCIStorageError("The private holdings bucket could not be verified.") from exc
        if getattr(bucket, "public_access_type", None) != "NoPublicAccess":
            raise OCIStorageError("Make the OCI holdings bucket private before importing a statement.")
        if getattr(bucket, "versioning", None) != "Disabled":
            raise OCIStorageError(
                "Disable Object Storage versioning so only the latest holdings snapshot is retained."
            )

    def save_snapshot(self, parsed: ParsedCas) -> str:
        self.ensure_private_bucket()
        payload = snapshot_payload(parsed)
        current = self._read_current()
        if current is not None:
            prior_date = _parse_iso_date(current.get("statement_date"))
            if prior_date and parsed.statement_date < prior_date:
                raise OCIStorageError(
                    "This statement is older than the saved snapshot, so the cache was left unchanged."
                )
            if prior_date == parsed.statement_date and _holdings_equal(current, payload):
                return "This statement was already imported; the holdings snapshot is up to date."

        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        try:
            self.client.put_object(
                self.namespace,
                self.bucket_name,
                OBJECT_NAME,
                BytesIO(encoded),
                content_type="application/json; charset=utf-8",
            )
        except Exception as exc:
            raise OCIStorageError(
                "The holdings snapshot could not be saved; the previous snapshot was preserved."
            ) from exc
        return f"Imported {len(parsed.holdings)} funds from the statement dated {parsed.statement_date.isoformat()}."

    def _read_current(self) -> dict[str, object] | None:
        try:
            response = self.client.get_object(self.namespace, self.bucket_name, OBJECT_NAME)
        except Exception as exc:
            if getattr(exc, "status", None) == 404:
                return None
            raise OCIStorageError("The existing holdings snapshot could not be read; it was left unchanged.") from exc
        try:
            data = response.data.content
            raw = data.read() if hasattr(data, "read") else data
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except Exception as exc:
            raise OCIStorageError("The existing holdings snapshot has an unsupported format; it was left unchanged.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("holdings"), list):
            raise OCIStorageError("The existing holdings snapshot has an unsupported format; it was left unchanged.")
        return payload
