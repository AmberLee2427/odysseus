import asyncio
import base64
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routes import browser_routes


def _request(*, api_token=False, scopes=None, owner="alice"):
    return SimpleNamespace(
        state=SimpleNamespace(
            api_token=api_token,
            api_token_scopes=scopes or [],
            api_token_owner=owner,
            current_user=owner if not api_token else "api",
        )
    )


def _handler(path, method="POST"):
    router = browser_routes.setup_browser_routes()
    for route in router.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


def test_browser_scope_requires_browser_read_for_api_tokens():
    with pytest.raises(HTTPException) as exc:
        browser_routes._require_browser_scope(_request(api_token=True, scopes=["chat"]), "browser:read")
    assert exc.value.status_code == 403


def test_browser_scope_allows_cookie_session_without_api_scope():
    browser_routes._require_browser_scope(_request(api_token=False), "browser:read")


def test_owner_uses_real_token_owner_for_api_tokens():
    assert browser_routes._owner(_request(api_token=True, owner="amber")) == "amber"


def test_capture_screenshot_saves_image_and_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_routes, "CAPTURE_ROOT", str(tmp_path))
    monkeypatch.setattr(browser_routes, "get_current_user", lambda request: "alice")
    payload = base64.b64encode(b"\x89PNG\r\nfake").decode("ascii")
    body = browser_routes.BrowserScreenshotRequest(
        title="Example",
        url="https://example.test/page",
        data_url=f"data:image/png;base64,{payload}",
    )

    response = asyncio.run(_handler("/api/browser/captures/screenshot")(
        _request(api_token=True, scopes=["browser:read", "browser:write"]),
        body,
    ))

    assert response["filename"].endswith(".png")
    saved = tmp_path / "alice" / response["filename"]
    assert saved.read_bytes() == b"\x89PNG\r\nfake"
    sidecar = saved.with_suffix(".txt")
    assert "https://example.test/page" in sidecar.read_text(encoding="utf-8")


def test_summarize_uses_browser_reasoning_model(monkeypatch):
    calls = {}

    def fake_resolve(prefix, owner=None):
        calls["prefix"] = prefix
        calls["owner"] = owner
        return "https://llm.test/v1/chat/completions", "browser-model", {"Authorization": "Bearer key"}

    async def fake_llm(endpoint_url, model, messages, headers=None, timeout=None, max_retries=None, max_tokens=None):
        calls["endpoint_url"] = endpoint_url
        calls["model"] = model
        calls["messages"] = messages
        calls["headers"] = headers
        calls["timeout"] = timeout
        calls["max_retries"] = max_retries
        calls["max_tokens"] = max_tokens
        return "This page is about testing."

    monkeypatch.setattr(browser_routes, "resolve_endpoint", fake_resolve)
    monkeypatch.setattr(browser_routes, "load_settings", lambda: {"browser_summary_timeout_seconds": 77})
    monkeypatch.setattr(browser_routes, "get_current_user", lambda request: "alice")

    import src.llm_core

    monkeypatch.setattr(src.llm_core, "llm_call_async", fake_llm)
    body = browser_routes.BrowserSummaryRequest(
        page=browser_routes.BrowserPageContext(
            title="Test Page",
            url="https://example.test",
            text="Important page text.",
        )
    )

    response = asyncio.run(_handler("/api/browser/summarize")(
        _request(api_token=True, scopes=["browser:read"]),
        body,
    ))

    assert response["summary"] == "This page is about testing."
    assert response["model"] == "browser-model"
    assert calls["prefix"] == "browser_reasoning"
    assert calls["owner"] == "alice"
    assert calls["timeout"] == 77
    assert calls["max_retries"] == 1
    assert calls["max_tokens"] == 900
    assert "Important page text." in calls["messages"][1]["content"]
