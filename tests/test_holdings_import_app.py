import asyncio

import pytest


def test_private_repository_gate_runs_before_multipart_body_is_read(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from starlette.requests import Request

    import mfhelper.holdings_import_app as import_app
    from mfhelper.holdings_cache import CacheError

    body_was_read = False

    async def receive():
        nonlocal body_was_read
        body_was_read = True
        return {"type": "http.request", "body": b"", "more_body": False}

    def reject_context():
        raise CacheError("private repository required")

    async def downstream(_request):
        raise AssertionError("multipart route must not run when the privacy gate fails")

    monkeypatch.setattr(import_app, "ensure_import_context", reject_context)
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/import",
            "raw_path": b"/import",
            "query_string": b"",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
            "client": ("testclient", 1234),
            "server": ("testserver", 80),
        },
        receive,
    )

    response = asyncio.run(import_app.guard_import_request(request, downstream))

    assert response.status_code == 403
    assert not body_was_read
