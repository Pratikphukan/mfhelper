from urllib.parse import parse_qs, urlparse

import pytest


def _configure(monkeypatch):
    monkeypatch.setenv("MFHELPER_PUBLIC_URL", "https://203.0.113.10")
    monkeypatch.setenv("MFHELPER_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GITHUB_ALLOWED_LOGIN", "mfhelper-owner")
    monkeypatch.setenv("OCI_REGION", "ap-hyderabad-1")
    monkeypatch.setenv("OCI_NAMESPACE", "namespace")
    monkeypatch.setenv("OCI_BUCKET_NAME", "holdings")


def test_import_page_requires_https_url_and_oauth_configuration(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    _configure(monkeypatch)
    monkeypatch.setenv("MFHELPER_PUBLIC_URL", "http://203.0.113.10")
    from fastapi.testclient import TestClient
    from mfhelper.oci_holdings_import_app import app

    response = TestClient(app, base_url="https://203.0.113.10").get("/")

    assert response.status_code == 503
    assert "not fully configured" in response.text


def test_github_login_uses_state_and_only_read_user_scope(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    _configure(monkeypatch)
    from fastapi.testclient import TestClient
    from mfhelper.oci_holdings_import_app import app

    response = TestClient(app, base_url="https://203.0.113.10").get("/auth/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("https://github.com/login/oauth/authorize?")
    assert "scope=read%3Auser" in response.headers["location"]
    assert "redirect_uri=https%3A%2F%2F203.0.113.10%2Foauth%2Fcallback" in response.headers["location"]
    assert "secure" in response.headers["set-cookie"].lower()


def test_wrong_oauth_state_is_rejected(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    _configure(monkeypatch)
    from fastapi.testclient import TestClient
    from mfhelper.oci_holdings_import_app import app

    client = TestClient(app, base_url="https://203.0.113.10")
    client.get("/auth/login", follow_redirects=False)
    response = client.get("/oauth/callback?code=sample&state=wrong")

    assert response.status_code == 400
    assert "could not be verified" in response.text


def test_non_allowlisted_github_user_cannot_sign_in(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    _configure(monkeypatch)
    import mfhelper.oci_holdings_import_app as import_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(import_app, "_github_user_for_code", lambda _code, _config: {"login": "someone-else"})
    client = TestClient(import_app.app, base_url="https://203.0.113.10")
    login_response = client.get("/auth/login", follow_redirects=False)
    oauth_state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    response = client.get(f"/oauth/callback?code=sample&state={oauth_state}")

    assert response.status_code == 403
    assert "not allowed" in response.text


def test_allowed_github_user_gets_session_without_retaining_oauth_token(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    _configure(monkeypatch)
    import mfhelper.oci_holdings_import_app as import_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(import_app, "_github_user_for_code", lambda _code, _config: {"login": "MFHelper-Owner"})
    client = TestClient(import_app.app, base_url="https://203.0.113.10")
    login_response = client.get("/auth/login", follow_redirects=False)
    oauth_state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    callback = client.get(f"/oauth/callback?code=sample&state={oauth_state}", follow_redirects=False)
    page = client.get("/")

    assert callback.status_code == 303
    assert page.status_code == 200
    assert "Signed in as" in page.text
    assert "access_token" not in (client.cookies.get(import_app._SESSION_COOKIE) or "")


def test_unauthenticated_upload_is_rejected_before_storage_or_parser(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    _configure(monkeypatch)
    import mfhelper.oci_holdings_import_app as import_app
    from fastapi.testclient import TestClient

    def should_not_create_store():
        raise AssertionError("storage should not be checked before authentication")

    monkeypatch.setattr(import_app, "_store", should_not_create_store)
    client = TestClient(import_app.app, base_url="https://203.0.113.10")
    response = client.post(
        "/import",
        data={"pan": "ABCDE1234F", "form_token": "unused"},
        files={"file": ("cas.pdf", b"%PDF-test", "application/pdf")},
    )

    assert response.status_code == 403
    assert "authorized GitHub account" in response.text
