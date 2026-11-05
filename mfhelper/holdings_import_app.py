"""Private browser page for importing one user's CDSL CAS in Codespaces."""

from __future__ import annotations

import asyncio
import html
import hmac
import secrets

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from mfhelper.casl_import import CasImportError, parse_cdsl_cas
from mfhelper.holdings_cache import CacheError, ensure_import_context, save_snapshot_and_push


MAX_PDF_BYTES = 25 * 1024 * 1024
_FORM_TOKEN = secrets.token_urlsafe(32)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def guard_import_request(request: Request, call_next):
    # FastAPI parses multipart fields only after middleware calls downstream.
    # Check Codespaces/repository privacy before Starlette reads and spools the
    # PDF and password from the request body.
    if request.method == "POST" and request.url.path == "/import":
        try:
            await asyncio.to_thread(ensure_import_context)
        except CacheError as exc:
            return HTMLResponse(_page(str(exc), error=True), status_code=403)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def import_page() -> str:
    return _page()


@app.post("/import", response_class=HTMLResponse)
async def import_statement(
    file: UploadFile = File(...),
    pan: str = Form(...),
    form_token: str = Form(...),
) -> HTMLResponse:
    pdf_bytes: bytes | None = None
    try:
        if not hmac.compare_digest(form_token, _FORM_TOKEN):
            return HTMLResponse(_page("This import page expired. Reload it and try again.", error=True), status_code=400)
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            return HTMLResponse(_page("Choose the original CDSL CAS PDF file.", error=True), status_code=400)

        pdf_bytes = await file.read(MAX_PDF_BYTES + 1)
        if len(pdf_bytes) > MAX_PDF_BYTES:
            return HTMLResponse(_page("The PDF is too large (maximum 25 MB).", error=True), status_code=413)

        parsed = parse_cdsl_cas(pdf_bytes, pan)
        status = save_snapshot_and_push(parsed)
        return HTMLResponse(_page(status, success=True))
    except (CasImportError, CacheError) as exc:
        return HTMLResponse(_page(str(exc), error=True), status_code=400)
    except Exception:
        # Never include exception details in the browser or logs. Third-party
        # PDF errors can include pieces of the input document.
        return HTMLResponse(
            _page("The statement could not be imported. No holdings were saved.", error=True),
            status_code=500,
        )
    finally:
        pdf_bytes = None
        pan = ""
        await file.close()


def _page(message: str = "", *, error: bool = False, success: bool = False) -> str:
    alert = ""
    if message:
        tone = "border-red-200 bg-red-50 text-red-800" if error else "border-emerald-200 bg-emerald-50 text-emerald-800"
        mark = "⚠" if error else "✓"
        alert = f'<div class="notice {tone}" role="status">{mark} {html.escape(message)}</div>'
    token = html.escape(_FORM_TOKEN, quote=True)
    button_disabled = "disabled" if success else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-store">
  <title>MFHelper holdings import</title>
  <style>
    :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172033; background: #f4f7fb; }}
    body {{ margin: 0; padding: 36px 16px; }}
    main {{ max-width: 620px; margin: 0 auto; }}
    .card {{ background: white; border: 1px solid #dbe3ee; border-radius: 18px; padding: 28px; box-shadow: 0 12px 32px rgba(20, 40, 75, .08); }}
    h1 {{ margin: 0 0 8px; font-size: 1.55rem; }}
    .intro {{ color: #536178; line-height: 1.5; margin: 0 0 24px; }}
    label {{ display: block; margin: 18px 0 7px; font-weight: 650; }}
    input[type=file], input[type=password] {{ box-sizing: border-box; width: 100%; border: 1px solid #bac6d7; border-radius: 9px; padding: 11px; background: #fff; }}
    .hint {{ margin-top: 6px; color: #68778d; font-size: .88rem; }}
    button {{ margin-top: 22px; background: #1749b1; color: #fff; border: 0; border-radius: 9px; padding: 12px 18px; font-weight: 700; cursor: pointer; }}
    button:disabled {{ opacity: .65; cursor: wait; }}
    .notice {{ margin: 0 0 18px; border: 1px solid; border-radius: 10px; padding: 12px 14px; line-height: 1.45; }}
    .privacy {{ margin-top: 22px; padding-top: 16px; border-top: 1px solid #e2e8f0; color: #536178; font-size: .9rem; line-height: 1.5; }}
  </style>
</head>
<body>
<main>
  <section class="card">
    <h1>Import mutual-fund holdings</h1>
    <p class="intro">Choose your CDSL CAS PDF. MFHelper will process it in this private Codespace and save the holdings snapshot to this repository.</p>
    {alert}
    <form method="post" action="/import" enctype="multipart/form-data" autocomplete="off">
      <input type="hidden" name="form_token" value="{token}">
      <label for="cas-file">CDSL CAS PDF</label>
      <input id="cas-file" name="file" type="file" accept="application/pdf,.pdf" required {button_disabled}>
      <label for="pan">PDF password</label>
      <input id="pan" name="pan" type="password" inputmode="text" autocapitalize="characters" autocomplete="new-password" spellcheck="false" maxlength="10" required {button_disabled}>
      <div class="hint">For CDSL CAS, enter the first or sole holder’s PAN. It is converted to uppercase and used only for this import.</div>
      <button type="submit" {button_disabled}>Import statement</button>
    </form>
    <p class="privacy">The PDF is temporary and is not committed. MFHelper saves only the extracted holdings snapshot. Use this page only from a private repository and keep the Codespaces port private.</p>
  </section>
</main>
</body>
</html>"""
