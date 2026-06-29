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


def _handler_with_session_manager(path, session_manager, method="POST"):
    router = browser_routes.setup_browser_routes(session_manager)
    for route in router.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


class _FakeSession:
    def __init__(self, name):
        self.name = name
        self.headers = {}
        self.messages = []

    def add_message(self, message):
        self.messages.append(message)


class _FakeSessionManager:
    def __init__(self):
        self.created = []
        self.saved = 0
        self.session = None
        self.sessions = {}

    def create_session(self, **kwargs):
        self.created.append(kwargs)
        self.session = _FakeSession(kwargs["name"])
        self.session.id = kwargs["session_id"]
        self.session.model = kwargs["model"]
        self.session.owner = kwargs.get("owner")
        self.sessions[self.session.id] = self.session
        return self.session

    def save_sessions(self):
        self.saved += 1

    def get_session(self, session_id):
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return self.sessions[session_id]

    def get_sessions_for_user(self, owner):
        return {
            sid: session
            for sid, session in self.sessions.items()
            if getattr(session, "owner", None) == owner
        }


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


def test_summarize_saves_browser_summary_to_chat(monkeypatch):
    def fake_resolve(prefix, owner=None):
        return "https://llm.test/v1/chat/completions", "browser-model", {"Authorization": "Bearer key"}

    async def fake_llm(*args, **kwargs):
        return "Saved summary."

    monkeypatch.setattr(browser_routes, "resolve_endpoint", fake_resolve)
    monkeypatch.setattr(browser_routes, "load_settings", lambda: {"browser_summary_timeout_seconds": 20})
    monkeypatch.setattr(browser_routes, "get_current_user", lambda request: "alice")

    import src.llm_core

    monkeypatch.setattr(src.llm_core, "llm_call_async", fake_llm)
    manager = _FakeSessionManager()
    body = browser_routes.BrowserSummaryRequest(
        page=browser_routes.BrowserPageContext(
            title="A Very Interesting Browser Page",
            url="https://example.test/story",
            text="Page context for follow-up.",
        ),
        instruction="Summarize this page.",
    )

    response = asyncio.run(_handler_with_session_manager("/api/browser/summarize", manager)(
        _request(api_token=True, scopes=["browser:read"]),
        body,
    ))

    assert response["saved"] is True
    assert response["session_id"]
    assert response["session_url"] == f"/#session-{response['session_id']}"
    assert manager.created[0]["owner"] == "alice"
    assert manager.created[0]["model"] == "browser-model"
    assert manager.session.headers == {"Authorization": "Bearer key"}
    assert [msg.role for msg in manager.session.messages] == ["system", "user", "assistant"]
    assert "Page context for follow-up." in manager.session.messages[0].content
    assert manager.session.messages[2].content == "Saved summary."


def test_browser_sessions_lists_owned_sessions():
    manager = _FakeSessionManager()
    alice = _FakeSession("Alice chat")
    alice.id = "alice-chat"
    alice.owner = "alice"
    alice.model = "model-a"
    alice.archived = False
    bob = _FakeSession("Bob chat")
    bob.id = "bob-chat"
    bob.owner = "bob"
    bob.model = "model-b"
    bob.archived = False
    manager.sessions = {alice.id: alice, bob.id: bob}

    response = asyncio.run(_handler_with_session_manager("/api/browser/sessions", manager, method="GET")(
        _request(api_token=True, scopes=["browser:read"]),
    ))

    assert response["sessions"] == [{"id": "alice-chat", "name": "Alice chat", "model": "model-a"}]


def test_browser_theme_uses_token_owner_prefs(monkeypatch):
    def fake_load_user_prefs(owner):
        assert owner == "alice"
        return {
            "theme": {
                "name": "paper-boat",
                "colors": {
                    "bg": "#101820",
                    "fg": "#f2f2f2",
                    "panel": "#17222e",
                    "border": "#70a0af",
                    "red": "#ff6b6b",
                },
            }
        }

    monkeypatch.setattr(browser_routes, "_load_user_prefs", fake_load_user_prefs)

    response = asyncio.run(_handler("/api/browser/theme", method="GET")(
        _request(api_token=True, scopes=["browser:read"]),
    ))

    assert response["owner"] == "alice"
    assert response["theme"]["name"] == "paper-boat"
    assert response["theme"]["colors"]["bg"] == "#101820"
    assert response["theme"]["colors"]["red"] == "#ff6b6b"


def test_summarize_appends_to_existing_chat(monkeypatch):
    def fake_resolve(prefix, owner=None):
        return "https://llm.test/v1/chat/completions", "browser-model", {}

    async def fake_llm(*args, **kwargs):
        return "Appended summary."

    monkeypatch.setattr(browser_routes, "resolve_endpoint", fake_resolve)
    monkeypatch.setattr(browser_routes, "load_settings", lambda: {"browser_summary_timeout_seconds": 20})
    monkeypatch.setattr(browser_routes, "get_current_user", lambda request: "alice")

    import src.llm_core

    monkeypatch.setattr(src.llm_core, "llm_call_async", fake_llm)
    manager = _FakeSessionManager()
    existing = _FakeSession("Existing chat")
    existing.id = "existing"
    existing.owner = "alice"
    existing.model = "chat-model"
    existing.archived = False
    manager.sessions = {"existing": existing}
    body = browser_routes.BrowserSummaryRequest(
        page=browser_routes.BrowserPageContext(
            title="Page",
            url="https://example.test",
            text="Existing chat context.",
        ),
        instruction="Add this page.",
        session_id="existing",
    )

    response = asyncio.run(_handler_with_session_manager("/api/browser/summarize", manager)(
        _request(api_token=True, scopes=["browser:read"]),
        body,
    ))

    assert response["saved"] is True
    assert response["appended"] is True
    assert response["session_id"] == "existing"
    assert manager.created == []
    assert [msg.role for msg in existing.messages] == ["system", "user", "assistant"]


def test_overleaf_context_saves_to_new_chat(monkeypatch):
    def fake_resolve(prefix, owner=None):
        assert prefix == "browser_reasoning"
        assert owner == "alice"
        return "https://llm.test/v1/chat/completions", "browser-model", {"Authorization": "Bearer key"}

    monkeypatch.setattr(browser_routes, "resolve_endpoint", fake_resolve)
    monkeypatch.setattr(browser_routes, "get_current_user", lambda request: "alice")

    manager = _FakeSessionManager()
    body = browser_routes.BrowserOverleafContextRequest(
        context=browser_routes.BrowserOverleafContext(
            project_id="68768ebaca76a90da8368215",
            project_title="Paper Draft",
            file_name="main.tex",
            editor_kind="codemirror",
            url="https://www.overleaf.com/project/68768ebaca76a90da8368215",
            text="\\section{Introduction}\nHello Overleaf.",
        )
    )

    response = asyncio.run(_handler_with_session_manager("/api/browser/overleaf/context", manager)(
        _request(api_token=True, scopes=["browser:read"]),
        body,
    ))

    assert response["saved"] is True
    assert response["appended"] is False
    assert response["session_url"] == f"/#session-{response['session_id']}"
    assert manager.created[0]["name"] == "Overleaf: Paper Draft / main.tex"
    assert manager.created[0]["owner"] == "alice"
    assert manager.created[0]["model"] == "browser-model"
    assert manager.session.headers == {"Authorization": "Bearer key"}
    assert [msg.role for msg in manager.session.messages] == ["system", "user"]
    assert "Project ID: 68768ebaca76a90da8368215" in manager.session.messages[0].content
    assert "\\section{Introduction}" in manager.session.messages[0].content
    assert manager.session.messages[0].metadata["kind"] == "overleaf"
    assert manager.session.messages[0].metadata["file_name"] == "main.tex"


def test_overleaf_context_appends_to_existing_chat(monkeypatch):
    monkeypatch.setattr(browser_routes, "resolve_endpoint", lambda *args, **kwargs: ("", "", {}))
    monkeypatch.setattr(browser_routes, "get_current_user", lambda request: "alice")

    manager = _FakeSessionManager()
    existing = _FakeSession("Existing chat")
    existing.id = "existing"
    existing.owner = "alice"
    existing.model = "chat-model"
    existing.archived = False
    manager.sessions = {"existing": existing}
    body = browser_routes.BrowserOverleafContextRequest(
        context=browser_routes.BrowserOverleafContext(
            project_id="68768ebaca76a90da8368215",
            project_title="Paper Draft",
            file_name="main.tex",
            url="https://www.overleaf.com/project/68768ebaca76a90da8368215",
            selected_text="Important selected paragraph.",
            text="Full editor text.",
            warning="Only visible editor lines were available from the Overleaf tab.",
        ),
        session_id="existing",
    )

    response = asyncio.run(_handler_with_session_manager("/api/browser/overleaf/context", manager)(
        _request(api_token=True, scopes=["browser:read"]),
        body,
    ))

    assert response["saved"] is True
    assert response["appended"] is True
    assert response["session_id"] == "existing"
    assert manager.created == []
    assert [msg.role for msg in existing.messages] == ["system", "user"]
    assert "Captured scope: selected text" in existing.messages[0].content
    assert "Important selected paragraph." in existing.messages[0].content
    assert "Only visible editor lines" in response["warning"]
