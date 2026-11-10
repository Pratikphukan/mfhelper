import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from mfhelper.upload_ticket import verify_ticket
from mfhelper.vercel_holdings_cache import SNAPSHOT_PATH, VercelHoldingsStore
from tests.test_casl_import import _make_encrypted_cdsl_pdf
from tests.test_vercel_holdings_cache import FakeBlob

BASE = "https://mfhelper.example.vercel.app"
TICKET_SECRET = "t" * 48


def _configure(monkeypatch):
    monkeypatch.setenv("MFHELPER_PUBLIC_URL", BASE)
    monkeypatch.setenv("MFHELPER_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("MFHELPER_TICKET_SECRET", TICKET_SECRET)
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GITHUB_ALLOWED_LOGIN", "mfhelper-owner")


def _app_modules():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import mfhelper.vercel_holdings_import_app as import_app

    return import_app, TestClient


def _signed_in_client(monkeypatch, fake_blob=None):
    """Return (client, form_token, fake_blob, import_app) for the allowlisted owner."""
    _configure(monkeypatch)
    import_app, TestClient = _app_modules()
    fake_blob = fake_blob or FakeBlob()
    monkeypatch.setattr(import_app, "_store", lambda: VercelHoldingsStore(fake_blob))
    monkeypatch.setattr(import_app, "_github_user_for_code", lambda _c, _cfg: {"login": "MFHelper-Owner"})
    client = TestClient(import_app.app, base_url=BASE)
    login = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    client.get(f"/oauth/callback?code=sample&state={state}", follow_redirects=False)
    page = client.get("/")
    token = re.search(r'name="form_token" value="([^"]+)"', page.text).group(1)
    return client, token, fake_blob, import_app


def _groww_workbook():
    openpyxl = pytest.importorskip("openpyxl")
    from io import BytesIO

    workbook = openpyxl.Workbook()
    details = workbook.active
    details.title = "Personal Details"
    details.append(["PAN", "ABCDE1234F"])
    sheet = workbook.create_sheet("Holdings")
    sheet.append(["HOLDINGS AS ON 2026-11-10"])
    sheet.append([
        "Scheme Name", "Category", "Sub-category", "Folio No.", "Units",
        "Invested Value", "Current Value", "Returns", "XIRR", "AMC", "Source",
    ])
    sheet.append([
        "Sample Direct Growth", "Equity", "Flexi Cap", "000123", 2,
        1000, 1200, 200, "10%", "Ignored AMC", "Ignored Source",
    ])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_import_page_requires_https_url_and_both_secrets(monkeypatch):
    _configure(monkeypatch)
    import_app, TestClient = _app_modules()

    for name, value in (
        ("MFHELPER_PUBLIC_URL", "http://mfhelper.example.vercel.app"),
        ("MFHELPER_TICKET_SECRET", "short"),
        ("MFHELPER_SESSION_SECRET", "short"),
    ):
        _configure(monkeypatch)
        monkeypatch.setenv(name, value)
        response = TestClient(import_app.app, base_url=BASE).get("/")
        assert response.status_code == 503
        assert "not fully configured" in response.text


def test_github_login_uses_state_read_user_scope_and_secure_cookie(monkeypatch):
    _configure(monkeypatch)
    import_app, TestClient = _app_modules()

    response = TestClient(import_app.app, base_url=BASE).get("/auth/login", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "scope=read%3Auser" in location
    assert "redirect_uri=https%3A%2F%2Fmfhelper.example.vercel.app%2Foauth%2Fcallback" in location
    assert "secure" in response.headers["set-cookie"].lower()


def test_wrong_oauth_state_and_other_github_users_are_rejected(monkeypatch):
    _configure(monkeypatch)
    import_app, TestClient = _app_modules()
    monkeypatch.setattr(import_app, "_github_user_for_code", lambda _c, _cfg: {"login": "someone-else"})
    client = TestClient(import_app.app, base_url=BASE)

    client.get("/auth/login", follow_redirects=False)
    assert client.get("/oauth/callback?code=x&state=wrong").status_code == 400

    login = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    denied = client.get(f"/oauth/callback?code=x&state={state}")
    assert denied.status_code == 403
    assert "not allowed" in denied.text


def test_unauthenticated_requests_never_touch_storage_or_parser(monkeypatch):
    _configure(monkeypatch)
    import_app, TestClient = _app_modules()

    def should_not_be_called(*_args, **_kwargs):
        raise AssertionError("storage/parser used before authentication")

    monkeypatch.setattr(import_app, "_store", should_not_be_called)
    monkeypatch.setattr(import_app, "parse_cdsl_cas", should_not_be_called)
    client = TestClient(import_app.app, base_url=BASE)

    ticket = client.post("/upload-ticket", json={"form_token": "x"})
    imported = client.post(
        "/import", json={"blob_pathname": "tmp/a.pdf", "pan": "ABCDE1234F", "form_token": "x"}
    )

    assert ticket.status_code == 403
    assert imported.status_code == 403
    assert "authorized GitHub account" in imported.json()["error"]


def test_signed_in_page_has_nonce_csp_and_no_third_party_scripts(monkeypatch):
    client, _token, _blob, _app = _signed_in_client(monkeypatch)

    page = client.get("/")
    csp = page.headers["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)

    assert f'<script nonce="{nonce}">' in page.text
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "connect-src 'self' https://vercel.com/api/blob/ https://*.blob.vercel-storage.com" in csp
    assert "frame-ancestors 'none'" in csp
    assert "src=" not in page.text.split("<script")[1].split(">")[0]  # inline script only
    assert page.headers["cache-control"] == "no-store"
    assert "Signed in as" in page.text


def test_upload_ticket_requires_csrf_and_returns_a_verifiable_scoped_ticket(monkeypatch):
    client, token, _blob, _app = _signed_in_client(monkeypatch)

    assert client.post("/upload-ticket", json={"form_token": "wrong"}).status_code == 400
    assert client.post("/upload-ticket", content=b"not json").status_code == 400

    response = client.post("/upload-ticket", json={"form_token": token})

    assert response.status_code == 200
    body = response.json()
    payload = verify_ticket(TICKET_SECRET, body["ticket"])
    assert payload["login"] == "MFHelper-Owner"
    assert body["presign_path"] == "/upload-token/presign"
    assert response.headers["cache-control"] == "no-store"


def test_groww_upload_ticket_requires_settings_and_is_scoped_to_xlsx(monkeypatch):
    client, token, _blob, _app = _signed_in_client(monkeypatch)
    missing = client.post("/upload-ticket", json={"form_token": token, "upload_type": "groww_xlsx"})
    assert missing.status_code == 503

    monkeypatch.setenv("MFHELPER_SPREADSHEET_ID", "spreadsheet-id")
    monkeypatch.setenv("MFHELPER_GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps({
        "client_email": "service@example.com", "private_key": "fake-key",
    }))
    monkeypatch.setenv("MFHELPER_FUND_CODE_MAP", '[{"name":"Sample Direct Growth","code":"123456"}]')
    response = client.post("/upload-ticket", json={"form_token": token, "upload_type": "groww_xlsx"})

    assert response.status_code == 200
    body = response.json()
    payload = verify_ticket(TICKET_SECRET, body["ticket"])
    assert payload["upload_type"] == "groww_xlsx"
    assert body["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_groww_import_updates_sheet_and_discards_workbook(monkeypatch):
    fake = FakeBlob()
    fake.objects["tmp/groww.xlsx"] = _groww_workbook()
    client, token, _blob, import_app = _signed_in_client(monkeypatch, fake)
    monkeypatch.setenv("MFHELPER_SPREADSHEET_ID", "spreadsheet-id")
    monkeypatch.setenv("MFHELPER_GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps({
        "client_email": "service@example.com", "private_key": "fake-key",
    }))
    monkeypatch.setenv("MFHELPER_FUND_CODE_MAP", '[{"name":"Sample Direct Growth","code":"123456"}]')
    captured = {}

    class FakeWriter:
        def __init__(self, **kwargs):
            captured["settings"] = kwargs

        def replace(self, values):
            captured["values"] = values

    monkeypatch.setattr(import_app, "CurrentHoldingsSheetWriter", FakeWriter)
    response = client.post("/import", json={
        "blob_pathname": "tmp/groww.xlsx", "upload_type": "groww_xlsx", "form_token": token,
    })

    assert response.status_code == 200
    assert "Updated 1 fund holdings" in response.json()["message"]
    assert "tmp/groww.xlsx" not in fake.objects
    assert captured["values"][1][1] == "123456"
    assert "Ignored AMC" not in repr(captured["values"])
    assert "Ignored Source" not in repr(captured["values"])
    assert "ABCDE1234F" not in repr(captured["values"])


def test_invalid_groww_workbook_does_not_write_and_is_deleted(monkeypatch):
    fake = FakeBlob()
    fake.objects["tmp/bad.xlsx"] = b"not a workbook"
    client, token, _blob, import_app = _signed_in_client(monkeypatch, fake)
    monkeypatch.setenv("MFHELPER_SPREADSHEET_ID", "spreadsheet-id")
    monkeypatch.setenv("MFHELPER_GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps({
        "client_email": "service@example.com", "private_key": "fake-key",
    }))
    monkeypatch.setenv("MFHELPER_FUND_CODE_MAP", '[{"name":"Fund","code":"123"}]')
    monkeypatch.setattr(import_app, "CurrentHoldingsSheetWriter", lambda **_kwargs: pytest.fail("invalid workbook touched Sheets"))

    response = client.post("/import", json={
        "blob_pathname": "tmp/bad.xlsx", "upload_type": "groww_xlsx", "form_token": token,
    })

    assert response.status_code == 400
    assert "tmp/bad.xlsx" not in fake.objects


def test_upload_ticket_cleans_up_stale_temp_pdfs(monkeypatch):
    from datetime import datetime, timedelta, timezone

    fake = FakeBlob()
    fake.objects["tmp/stale.pdf"] = b"x"
    fake.uploaded_at["tmp/stale.pdf"] = datetime.now(timezone.utc) - timedelta(hours=2)
    client, token, _blob, _app = _signed_in_client(monkeypatch, fake)

    client.post("/upload-ticket", json={"form_token": token})

    assert "tmp/stale.pdf" not in fake.objects


def test_import_parses_saves_snapshot_and_deletes_the_temporary_pdf(monkeypatch):
    pytest.importorskip("pdfplumber")
    fake = FakeBlob()
    fake.objects["tmp/upload-1.pdf"] = _make_encrypted_cdsl_pdf()
    client, token, _blob, _app = _signed_in_client(monkeypatch, fake)

    response = client.post(
        "/import",
        json={"blob_pathname": "tmp/upload-1.pdf", "pan": "abcde1234f", "form_token": token},
    )

    assert response.status_code == 200
    assert "Imported 1 funds" in response.json()["message"]
    assert "tmp/upload-1.pdf" not in fake.objects
    snapshot = json.loads(fake.objects[SNAPSHOT_PATH])
    assert snapshot["statement_date"] == "2026-09-30"
    assert snapshot["holdings"][0]["units"] == "12.5"
    assert "ABCDE1234F" not in json.dumps(snapshot).upper()
    assert fake.put_calls[0]["access"] == "private"


def test_wrong_pan_is_rejected_and_the_temporary_pdf_is_still_deleted(monkeypatch):
    pytest.importorskip("pdfplumber")
    fake = FakeBlob()
    fake.objects["tmp/upload-2.pdf"] = _make_encrypted_cdsl_pdf()
    client, token, _blob, _app = _signed_in_client(monkeypatch, fake)

    response = client.post(
        "/import",
        json={"blob_pathname": "tmp/upload-2.pdf", "pan": "ZZZZZ9999Z", "form_token": token},
    )

    assert response.status_code == 400
    assert "PAN did not unlock" in response.json()["error"]
    assert "tmp/upload-2.pdf" not in fake.objects
    assert SNAPSHOT_PATH not in fake.objects
    assert "ZZZZZ9999Z" not in response.text


def test_expired_csrf_token_is_rejected_but_temporary_pdf_is_deleted(monkeypatch):
    fake = FakeBlob()
    fake.objects["tmp/upload-3.pdf"] = b"%PDF"
    client, _token, _blob, _app = _signed_in_client(monkeypatch, fake)

    response = client.post(
        "/import",
        json={"blob_pathname": "tmp/upload-3.pdf", "pan": "ABCDE1234F", "form_token": "stale"},
    )

    assert response.status_code == 400
    assert "expired" in response.json()["error"]
    assert "tmp/upload-3.pdf" not in fake.objects


@pytest.mark.parametrize("pathname", [SNAPSHOT_PATH, "tmp/../holdings/current.json", "https://evil.example/a.pdf", None])
def test_import_never_reads_or_deletes_non_temporary_blobs(monkeypatch, pathname):
    fake = FakeBlob()
    fake.objects[SNAPSHOT_PATH] = b'{"holdings": []}'
    client, token, _blob, _app = _signed_in_client(monkeypatch, fake)

    response = client.post(
        "/import",
        json={"blob_pathname": pathname, "pan": "ABCDE1234F", "form_token": token},
    )

    assert response.status_code == 400
    assert SNAPSHOT_PATH in fake.objects
    assert fake.delete_calls == []


def test_import_rejects_missing_password_and_oversized_json(monkeypatch):
    fake = FakeBlob()
    client, token, _blob, _app = _signed_in_client(monkeypatch, fake)

    no_pan = client.post("/import", json={"blob_pathname": "tmp/a.pdf", "pan": "", "form_token": token})
    huge = client.post("/import", json={"blob_pathname": "tmp/a.pdf", "pan": "A" * 20000, "form_token": token})

    assert no_pan.status_code == 400
    assert huge.status_code == 400


def test_unexpected_storage_failure_returns_generic_error_and_still_deletes(monkeypatch):
    fake = FakeBlob()
    fake.objects["tmp/upload-4.pdf"] = b"%PDF"
    client, token, _blob, import_app = _signed_in_client(monkeypatch, fake)

    def explode(*_args, **_kwargs):
        raise RuntimeError("secret-internal-detail ABCDE1234F")

    monkeypatch.setattr(import_app, "parse_cdsl_cas", explode)
    response = client.post(
        "/import",
        json={"blob_pathname": "tmp/upload-4.pdf", "pan": "ABCDE1234F", "form_token": token},
    )

    assert response.status_code == 500
    assert response.json() == {"error": "The statement could not be imported. No holdings were saved."}
    assert "tmp/upload-4.pdf" not in fake.objects
