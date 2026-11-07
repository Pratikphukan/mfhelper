import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from mfhelper.casl_import import Holding, ParsedCas
from mfhelper.upload_ticket import MAX_UPLOAD_BYTES
from mfhelper.vercel_holdings_cache import (
    SNAPSHOT_PATH,
    VercelHoldingsStore,
    VercelStorageError,
)


class FakeNotFound(Exception):
    pass


class FakeBlob:
    """In-memory stand-in for the ``vercel.blob`` async module."""

    BlobNotFoundError = FakeNotFound

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.uploaded_at: dict[str, datetime] = {}
        self.put_calls: list[dict] = []
        self.delete_calls: list[str] = []
        self.fail_put = False

    async def head_blob(self, pathname):
        if pathname not in self.objects:
            raise FakeNotFound(pathname)
        return SimpleNamespace(size=len(self.objects[pathname]), pathname=pathname)

    async def get_blob(self, pathname, *, access):
        assert access == "private"
        if pathname not in self.objects:
            raise FakeNotFound(pathname)
        return SimpleNamespace(body=self.objects[pathname])

    async def put_blob(self, pathname, body, **kwargs):
        if self.fail_put:
            raise RuntimeError("boom")
        self.put_calls.append({"pathname": pathname, **kwargs})
        self.objects[pathname] = bytes(body)

    async def delete_blob(self, pathname):
        self.delete_calls.append(pathname)
        self.objects.pop(pathname, None)

    async def query_blobs(self, *, prefix):
        for pathname in list(self.objects):
            if pathname.startswith(prefix):
                yield SimpleNamespace(
                    pathname=pathname,
                    size=len(self.objects[pathname]),
                    uploaded_at=self.uploaded_at.get(pathname, datetime.now(timezone.utc)),
                )


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


def run(coro):
    return asyncio.run(coro)


def test_snapshot_is_one_private_overwritable_object_with_minimal_data():
    blob = FakeBlob()
    store = VercelHoldingsStore(blob)

    status = run(store.save_snapshot(_cas()))

    assert "Imported 1 funds" in status
    call = blob.put_calls[0]
    assert call["pathname"] == SNAPSHOT_PATH
    assert call["access"] == "private"
    assert call["allow_overwrite"] is True
    assert call["add_random_suffix"] is False
    payload = json.loads(blob.objects[SNAPSHOT_PATH])
    assert payload["statement_date"] == "2026-09-30"
    assert payload["holdings"][0]["units"] == "12.34"
    assert "pan" not in str(payload).lower()
    assert "folio" not in str(payload).lower()


def test_duplicate_statement_does_not_rewrite_snapshot():
    blob = FakeBlob()
    store = VercelHoldingsStore(blob)
    run(store.save_snapshot(_cas()))
    blob.put_calls.clear()

    status = run(store.save_snapshot(_cas()))

    assert status.startswith("This statement was already imported")
    assert blob.put_calls == []


def test_same_date_with_changed_units_replaces_snapshot():
    blob = FakeBlob()
    store = VercelHoldingsStore(blob)
    run(store.save_snapshot(_cas()))

    run(store.save_snapshot(_cas(units="20")))

    assert json.loads(blob.objects[SNAPSHOT_PATH])["holdings"][0]["units"] == "20"


def test_older_statement_is_rejected_without_overwriting():
    blob = FakeBlob()
    store = VercelHoldingsStore(blob)
    run(store.save_snapshot(_cas()))
    previous = blob.objects[SNAPSHOT_PATH]

    with pytest.raises(VercelStorageError, match="older than the saved snapshot"):
        run(store.save_snapshot(_cas(date(2026, 8, 31))))

    assert blob.objects[SNAPSHOT_PATH] == previous


@pytest.mark.parametrize("existing", [b"not-json", b'{"holdings": "nope"}', b"[]"])
def test_unreadable_existing_snapshot_is_left_unchanged(existing):
    blob = FakeBlob()
    blob.objects[SNAPSHOT_PATH] = existing
    store = VercelHoldingsStore(blob)

    with pytest.raises(VercelStorageError, match="existing holdings snapshot"):
        run(store.save_snapshot(_cas()))

    assert blob.put_calls == []
    assert blob.objects[SNAPSHOT_PATH] == existing


def test_failed_write_reports_previous_snapshot_preserved():
    blob = FakeBlob()
    blob.fail_put = True
    store = VercelHoldingsStore(blob)

    with pytest.raises(VercelStorageError, match="previous snapshot was preserved"):
        run(store.save_snapshot(_cas()))


@pytest.mark.parametrize(
    "pathname",
    ["holdings/current.json", "tmp/../holdings/current.json", "tmp/a/b.pdf", "tmp/x.txt", "tmp/", None, 5, "/tmp/a.pdf"],
)
def test_only_server_style_temp_pathnames_are_accepted(pathname):
    with pytest.raises(VercelStorageError):
        VercelHoldingsStore.validate_temp_pathname(pathname)


def test_reads_temp_pdf_and_rejects_missing_or_oversized_files():
    blob = FakeBlob()
    blob.objects["tmp/ok.pdf"] = b"%PDF-1.7 data"
    store = VercelHoldingsStore(blob)

    assert run(store.read_temp_pdf("tmp/ok.pdf")) == b"%PDF-1.7 data"
    with pytest.raises(VercelStorageError, match="not found"):
        run(store.read_temp_pdf("tmp/missing.pdf"))

    blob.objects["tmp/big.pdf"] = b"x" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(VercelStorageError, match="too large"):
        run(store.read_temp_pdf("tmp/big.pdf"))


def test_delete_temp_never_raises_and_refuses_non_temp_paths():
    blob = FakeBlob()
    blob.objects["tmp/a.pdf"] = b"x"
    blob.objects[SNAPSHOT_PATH] = b"{}"
    store = VercelHoldingsStore(blob)

    assert run(store.delete_temp("tmp/a.pdf")) is True
    assert run(store.delete_temp(SNAPSHOT_PATH)) is False
    assert run(store.delete_temp("tmp/used-tickets/nonce_for_testing_1234.json")) is False
    assert SNAPSHOT_PATH in blob.objects

    async def broken(_pathname):
        raise RuntimeError("down")

    blob.delete_blob = broken
    assert run(store.delete_temp("tmp/a.pdf")) is False


def test_cleanup_removes_only_stale_temp_pdfs_and_ticket_claims():
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    stale_claim = "tmp/used-tickets/nonce_for_testing_1234.json"
    recent_claim = "tmp/used-tickets/recent_nonce_123456.json"
    blob = FakeBlob()
    blob.objects.update({
        "tmp/old.pdf": b"x",
        "tmp/new.pdf": b"x",
        stale_claim: b"used",
        recent_claim: b"used",
        "tmp/used-tickets/invalid!.json": b"keep",
        SNAPSHOT_PATH: b"{}",
    })
    blob.uploaded_at["tmp/old.pdf"] = now - timedelta(minutes=16)
    blob.uploaded_at["tmp/new.pdf"] = now - timedelta(minutes=2)
    blob.uploaded_at[stale_claim] = now - timedelta(minutes=16)
    blob.uploaded_at[recent_claim] = now - timedelta(minutes=2)
    blob.uploaded_at["tmp/used-tickets/invalid!.json"] = now - timedelta(hours=1)
    store = VercelHoldingsStore(blob)

    removed = run(store.cleanup_stale(now=now))

    assert removed == 2
    assert set(blob.objects) == {
        "tmp/new.pdf",
        recent_claim,
        "tmp/used-tickets/invalid!.json",
        SNAPSHOT_PATH,
    }


def test_cleanup_is_best_effort_when_listing_fails():
    class Broken(FakeBlob):
        async def query_blobs(self, *, prefix):
            raise RuntimeError("down")
            yield  # pragma: no cover

    store = VercelHoldingsStore(Broken())

    assert run(store.cleanup_stale()) == 0
