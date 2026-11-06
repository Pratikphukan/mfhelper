"""GitHub-authenticated CAS importer for the user's own Vercel project.

Flow: signed-in owner -> ``POST /upload-ticket`` -> Node service presigns a
private Blob PUT -> browser uploads the PDF straight to Blob -> ``POST /import``
parses it in memory, stores only the snapshot, and deletes the temporary PDF.
"""

from __future__ import annotations

import asyncio
import hmac
import html
import json
import os
import secrets
from urllib.parse import urlencode, urlparse

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from mfhelper.casl_import import CasImportError, parse_cdsl_cas
from mfhelper.upload_ticket import MAX_UPLOAD_BYTES, MIN_SECRET_LENGTH, TicketError, mint_ticket
from mfhelper.vercel_holdings_cache import VercelHoldingsStore, VercelStorageError

PRESIGN_PATH = "/upload-token/presign"
MAX_JSON_BYTES = 8 * 1024
_SESSION_SECRET = os.environ.get("MFHELPER_SESSION_SECRET") or secrets.token_urlsafe(48)
_SESSION_COOKIE = "mfhelper_session"
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class AppConfigurationError(ValueError):
    """Missing or invalid deployment configuration."""


def _config() -> dict[str, str]:
    values = {
        "base_url": os.environ.get("MFHELPER_PUBLIC_URL", "").strip().rstrip("/"),
        "client_id": os.environ.get("GITHUB_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "").strip(),
        "allowed_login": os.environ.get("GITHUB_ALLOWED_LOGIN", "").strip().casefold(),
        "session_secret": os.environ.get("MFHELPER_SESSION_SECRET", "").strip(),
        "ticket_secret": os.environ.get("MFHELPER_TICKET_SECRET", "").strip(),
    }
    parsed = urlparse(values["base_url"])
    if (
        not values["client_id"]
        or not values["client_secret"]
        or not values["allowed_login"]
        or len(values["session_secret"]) < MIN_SECRET_LENGTH
        or len(values["ticket_secret"]) < MIN_SECRET_LENGTH
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise AppConfigurationError("The Vercel import page is not fully configured.")
    return values


def _store() -> VercelHoldingsStore:
    return VercelHoldingsStore()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response


# SessionMiddleware must wrap the headers middleware so request.session is populated.
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    session_cookie=_SESSION_COOKIE,
    max_age=60 * 60,
    same_site="lax",
    https_only=True,
)


@app.get("/", response_class=HTMLResponse)
async def import_page(request: Request) -> HTMLResponse:
    try:
        config = _config()
    except AppConfigurationError as exc:
        return _page(str(exc), error=True, status_code=503)
    login = request.session.get("github_login", "")
    if login.casefold() != config["allowed_login"]:
        return _login_page()
    form_token = request.session.get("form_token")
    if not isinstance(form_token, str):
        form_token = secrets.token_urlsafe(32)
        request.session["form_token"] = form_token
    return _upload_page(login=login, form_token=form_token)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    try:
        _config()
    except AppConfigurationError as exc:
        return _page(str(exc), error=True, status_code=503)
    return _login_page()


@app.get("/auth/login")
async def github_login(request: Request):
    try:
        config = _config()
    except AppConfigurationError as exc:
        return _page(str(exc), error=True, status_code=503)
    state = secrets.token_urlsafe(32)
    request.session.clear()
    request.session["oauth_state"] = state
    query = urlencode(
        {
            "client_id": config["client_id"],
            "redirect_uri": f"{config['base_url']}/oauth/callback",
            "scope": "read:user",
            "state": state,
        }
    )
    return RedirectResponse(f"{_GITHUB_AUTHORIZE_URL}?{query}", status_code=303)


@app.get("/oauth/callback", response_class=HTMLResponse)
async def github_callback(request: Request, code: str = "", state: str = "") -> HTMLResponse:
    try:
        config = _config()
    except AppConfigurationError as exc:
        return _page(str(exc), error=True, status_code=503)
    expected_state = request.session.pop("oauth_state", "")
    if not code or not expected_state or not hmac.compare_digest(str(expected_state), state):
        request.session.clear()
        return _page("GitHub sign-in could not be verified. Start again from the import page.", error=True, status_code=400)

    try:
        user = await asyncio.to_thread(_github_user_for_code, code, config)
    except Exception:
        request.session.clear()
        return _page("GitHub sign-in failed. Please try again.", error=True, status_code=502)
    login = str(user.get("login") or "").strip()
    if login.casefold() != config["allowed_login"]:
        request.session.clear()
        return _page("This GitHub account is not allowed to use this private importer.", error=True, status_code=403)

    request.session.clear()
    request.session["github_login"] = login
    request.session["form_token"] = secrets.token_urlsafe(32)
    return RedirectResponse("/", status_code=303)


@app.post("/logout", response_class=HTMLResponse)
async def logout(request: Request, form_token: str = Form(...)) -> HTMLResponse:
    expected = request.session.get("form_token", "")
    if not expected or not hmac.compare_digest(str(expected), form_token):
        return _page("This page expired. Reload it and try again.", error=True, status_code=400)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


def _json_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _authorize_owner(request: Request) -> tuple[dict[str, str] | None, JSONResponse | None]:
    """Check configuration and the allowlisted session before reading any request body."""
    try:
        config = _config()
    except AppConfigurationError as exc:
        return None, _json_error(str(exc), 503)
    if request.session.get("github_login", "").casefold() != config["allowed_login"]:
        return None, _json_error("Sign in with the authorized GitHub account before importing.", 403)
    return config, None


async def _read_json(request: Request) -> dict[str, object] | None:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_JSON_BYTES:
        return None
    raw = await request.body()
    if len(raw) > MAX_JSON_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _csrf_ok(request: Request, supplied: object) -> bool:
    expected = request.session.get("form_token", "")
    return bool(expected) and isinstance(supplied, str) and hmac.compare_digest(str(expected), supplied)


@app.post("/upload-ticket")
async def upload_ticket(request: Request) -> JSONResponse:
    config, denied = _authorize_owner(request)
    if denied is not None:
        return denied
    body = await _read_json(request)
    if body is None:
        return _json_error("The request was not valid.", 400)
    if not _csrf_ok(request, body.get("form_token")):
        return _json_error("This page expired. Reload it and try again.", 400)

    try:
        await _store().cleanup_stale()
    except Exception:
        pass  # Cleanup is opportunistic; never block the owner on it.
    try:
        ticket = mint_ticket(config["ticket_secret"], str(request.session.get("github_login", "")))
    except TicketError as exc:
        return _json_error(str(exc), 503)
    return JSONResponse({"ticket": ticket, "presign_path": PRESIGN_PATH, "max_bytes": MAX_UPLOAD_BYTES})


@app.post("/import")
async def import_statement(request: Request) -> JSONResponse:
    config, denied = _authorize_owner(request)
    if denied is not None:
        return denied
    body = await _read_json(request)
    if body is None:
        return _json_error("The request was not valid.", 400)

    pathname = body.get("blob_pathname")
    pan = body.get("pan")
    store: VercelHoldingsStore | None = None
    pdf_bytes: bytes | None = None
    try:
        store = _store()
        if not _csrf_ok(request, body.get("form_token")):
            return _json_error("This page expired. Reload it and try again.", 400)
        if not isinstance(pan, str) or not pan.strip() or len(pan) > 32:
            return _json_error("Enter the PDF password.", 400)
        pathname = store.validate_temp_pathname(pathname)
        await store.cleanup_stale()

        pdf_bytes = await store.read_temp_pdf(pathname)
        parsed = await asyncio.to_thread(parse_cdsl_cas, pdf_bytes, pan)
        status = await store.save_snapshot(parsed)
        return JSONResponse({"message": status})
    except (CasImportError, VercelStorageError) as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("The statement could not be imported. No holdings were saved.", 500)
    finally:
        pdf_bytes = None
        pan = ""
        body = {}
        # Always remove the temporary PDF for an authorized request, success or failure.
        if store is not None and isinstance(pathname, str):
            await store.delete_temp(pathname)


def _github_user_for_code(code: str, config: dict[str, str]) -> dict[str, object]:
    token_response = requests.post(
        _GITHUB_TOKEN_URL,
        json={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "redirect_uri": f"{config['base_url']}/oauth/callback",
        },
        headers={"Accept": "application/json"},
        timeout=(5, 15),
    )
    if not token_response.ok:
        raise ValueError("OAuth token exchange failed")
    token = token_response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("OAuth token missing")
    user_response = requests.get(
        _GITHUB_USER_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=(5, 15),
    )
    if not user_response.ok:
        raise ValueError("GitHub identity lookup failed")
    return user_response.json()


def _login_page(message: str = "") -> HTMLResponse:
    notice = f'<div class="notice">{html.escape(message)}</div>' if message else ""
    return _page_html(
        f"""{notice}
        <h1>Sign in to import holdings</h1>
        <p class="intro">Only the authorized GitHub account can use this private importer.</p>
        <a class="button" href="/auth/login">Continue with GitHub</a>
        <p class="privacy">The PDF is kept in a private Vercel Blob only until it is parsed, then deleted. Only the holdings snapshot is kept.</p>"""
    )


_UPLOAD_SCRIPT = """
const form = document.getElementById('import-form');
const statusBox = document.getElementById('status');
const submit = document.getElementById('submit');
const MAX_BYTES = %(max_bytes)d;
function show(message, isError) {
  statusBox.className = 'notice ' + (isError ? 'error' : 'success');
  statusBox.textContent = message;
  statusBox.hidden = false;
}
async function postJson(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) { throw new Error(data.error || 'The request failed. Please try again.'); }
  return data;
}
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = document.getElementById('cas-file').files[0];
  const panInput = document.getElementById('pan');
  const formToken = form.elements['form_token'].value;
  if (!file) { show('Choose the original CDSL CAS PDF file.', true); return; }
  if (file.size > MAX_BYTES) { show('The PDF is too large (maximum 25 MB).', true); return; }
  submit.disabled = true;
  let pathname = '';
  try {
    show('Preparing a private upload...', false);
    const ticket = await postJson('/upload-ticket', { form_token: formToken });
    const presign = await postJson(ticket.presign_path, { ticket: ticket.ticket });
    pathname = presign.pathname;
    show('Uploading the statement...', false);
    const put = await fetch(presign.url, {
      method: 'PUT',
      headers: { 'content-type': 'application/pdf' },
      body: file,
    });
    if (!put.ok) { throw new Error('The statement could not be uploaded. Please try again.'); }
    show('Reading the statement...', false);
    const result = await postJson('/import', { blob_pathname: pathname, pan: panInput.value, form_token: formToken });
    show(result.message, false);
    form.reset();
  } catch (error) {
    show(error.message, true);
  } finally {
    panInput.value = '';
    submit.disabled = false;
  }
});
""" % {"max_bytes": MAX_UPLOAD_BYTES}


def _upload_page(
    *, login: str, form_token: str, message: str = "", error: bool = False
) -> HTMLResponse:
    alert = ""
    if message:
        tone = "error" if error else "success"
        alert = f'<div class="notice {tone}" role="status">{html.escape(message)}</div>'
    return _page_html(
        f"""<div class="account">Signed in as <strong>{html.escape(login)}</strong>
        <form method="post" action="/logout"><input type="hidden" name="form_token" value="{html.escape(form_token, quote=True)}"><button class="link" type="submit">Sign out</button></form></div>
        <h1>Import mutual-fund holdings</h1>
        <p class="intro">Choose your CDSL CAS PDF. MFHelper will extract the holdings and save the latest snapshot in your private Vercel Blob store.</p>
        {alert}
        <div id="status" class="notice" role="status" hidden></div>
        <form id="import-form" autocomplete="off">
          <input type="hidden" name="form_token" value="{html.escape(form_token, quote=True)}">
          <label for="cas-file">CDSL CAS PDF</label>
          <input id="cas-file" name="file" type="file" accept="application/pdf,.pdf" required>
          <label for="pan">PDF password</label>
          <input id="pan" name="pan" type="password" inputmode="text" autocapitalize="characters" autocomplete="new-password" spellcheck="false" maxlength="10" required>
          <div class="hint">For CDSL CAS, enter the first or sole holder’s PAN. It is used only to unlock this statement.</div>
          <button id="submit" type="submit">Import statement</button>
        </form>
        <noscript><div class="notice error">JavaScript is required to upload the statement.</div></noscript>
        <p class="privacy">The PDF is stored in a private Vercel Blob only until it is parsed, then deleted. The password is never stored. Only the extracted snapshot is kept, and each successful import replaces the previous one.</p>""",
        script=_UPLOAD_SCRIPT,
    )


def _page(message: str, *, error: bool, status_code: int) -> HTMLResponse:
    tone = "error" if error else "success"
    return _page_html(
        f'<div class="notice {tone}" role="status">{html.escape(message)}</div>',
        status_code=status_code,
    )


_STYLE = """
:root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172033; background: #f4f7fb; }
body { margin: 0; padding: 36px 16px; } main { max-width: 620px; margin: 0 auto; } .card { background: white; border: 1px solid #dbe3ee; border-radius: 18px; padding: 28px; box-shadow: 0 12px 32px rgba(20,40,75,.08); }
h1 { margin: 0 0 8px; font-size: 1.55rem; } .intro { color: #536178; line-height: 1.5; margin: 0 0 24px; } label { display:block; margin:18px 0 7px; font-weight:650; }
input[type=file], input[type=password] { box-sizing:border-box; width:100%; border:1px solid #bac6d7; border-radius:9px; padding:11px; background:#fff; } .hint { margin-top:6px; color:#68778d; font-size:.88rem; }
button, .button { display:inline-block; margin-top:22px; background:#1749b1; color:#fff; border:0; border-radius:9px; padding:12px 18px; font-weight:700; cursor:pointer; text-decoration:none; }
button:disabled { opacity:.6; cursor:progress; }
.notice { margin:0 0 18px; border:1px solid #dbe3ee; border-radius:10px; padding:12px 14px; line-height:1.45; } .notice[hidden] { display:none; } .error { border-color:#fecaca; background:#fef2f2; color:#991b1b; } .success { border-color:#bbf7d0; background:#f0fdf4; color:#166534; }
.privacy { margin-top:22px; padding-top:16px; border-top:1px solid #e2e8f0; color:#536178; font-size:.9rem; line-height:1.5; } .account { display:flex; justify-content:space-between; align-items:center; color:#536178; font-size:.9rem; margin-bottom:24px; } .account form { margin:0; } .link { margin:0; background:transparent; color:#1749b1; padding:4px; }
"""


def _page_html(content: str, *, status_code: int = 200, script: str = "") -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    script_tag = f'<script nonce="{nonce}">{script}</script>' if script else ""
    response = HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store"><title>MFHelper holdings import</title>
<style nonce="{nonce}">{_STYLE}</style></head><body><main><section class="card">{content}</section></main>{script_tag}</body></html>""",
        status_code=status_code,
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "connect-src 'self' https://vercel.com/api/blob/ https://*.blob.vercel-storage.com; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response
