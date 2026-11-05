from datetime import date
from decimal import Decimal
import io
import json
from types import SimpleNamespace

import pytest

from mfhelper.casl_import import Holding, ParsedCas
from mfhelper.oci_holdings_cache import OBJECT_NAME, OCIHoldingsCache, OCIStorageError


class FakeNotFound(Exception):
    status = 404


class FakeObjectStorage:
    def __init__(self, *, public_access_type="NoPublicAccess", versioning="Disabled", current=None):
        self.bucket = SimpleNamespace(public_access_type=public_access_type, versioning=versioning)
        self.current = current
        self.put_calls = []

    def get_bucket(self, namespace, bucket_name):
        return SimpleNamespace(data=self.bucket)

    def get_object(self, namespace, bucket_name, object_name):
        if self.current is None:
            raise FakeNotFound()
        return SimpleNamespace(data=SimpleNamespace(content=io.BytesIO(self.current)))

    def put_object(self, namespace, bucket_name, object_name, body, **kwargs):
        self.put_calls.append((namespace, bucket_name, object_name, kwargs))
        self.current = body.read()


def _cas(statement_date=date(2026, 9, 30), units="12.34"):
    return ParsedCas(
        statement_date=statement_date,
        holdings=(
            Holding(
                scheme_name="Example Fund Direct Growth",
                units=Decimal(units),
                statement_value=Decimal("1234.50"),
                isin="INF200K01RP8",
            ),
        ),
    )


def test_private_bucket_without_versioning_is_required():
    for fake in (
        FakeObjectStorage(public_access_type="ObjectRead"),
        FakeObjectStorage(versioning="Enabled"),
    ):
        cache = OCIHoldingsCache(fake, "namespace", "bucket")
        with pytest.raises(OCIStorageError):
            cache.ensure_private_bucket()


def test_snapshot_is_written_to_one_private_object_and_only_minimal_data_is_kept():
    fake = FakeObjectStorage()
    cache = OCIHoldingsCache(fake, "namespace", "bucket")

    result = cache.save_snapshot(_cas())

    assert "Imported 1 funds" in result
    assert fake.put_calls[0][2] == OBJECT_NAME
    payload = json.loads(fake.current)
    assert payload["statement_date"] == "2026-09-30"
    assert payload["holdings"][0]["units"] == "12.34"
    assert "pan" not in str(payload).lower()
    assert "folio" not in str(payload).lower()


def test_duplicate_statement_does_not_rewrite_current_object():
    fake = FakeObjectStorage()
    cache = OCIHoldingsCache(fake, "namespace", "bucket")
    cache.save_snapshot(_cas())
    fake.put_calls.clear()

    status = cache.save_snapshot(_cas())

    assert status.startswith("This statement was already imported")
    assert fake.put_calls == []


def test_older_statement_is_rejected_without_overwriting_snapshot():
    fake = FakeObjectStorage()
    cache = OCIHoldingsCache(fake, "namespace", "bucket")
    cache.save_snapshot(_cas())
    previous = fake.current

    with pytest.raises(OCIStorageError, match="older than the saved snapshot"):
        cache.save_snapshot(_cas(date(2026, 8, 31)))

    assert fake.current == previous


def test_invalid_existing_snapshot_is_left_unchanged():
    fake = FakeObjectStorage(current=b"not-json")
    cache = OCIHoldingsCache(fake, "namespace", "bucket")

    with pytest.raises(OCIStorageError, match="existing holdings snapshot"):
        cache.save_snapshot(_cas())

    assert fake.put_calls == []
