import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from routes.terminal_routes import setup_terminal_routes


class _Auth:
    def get_username_for_token(self, token):
        return "amber" if token == "admin-session" else "guest"

    def is_admin(self, username):
        return username == "amber"


def _client():
    app = FastAPI()

    @app.middleware("http")
    async def attach_user(request, call_next):
        token = request.cookies.get("odysseus_session")
        request.state.current_user = _Auth().get_username_for_token(token)
        return await call_next(request)

    app.include_router(setup_terminal_routes(_Auth()))
    return TestClient(app)


def test_terminal_rejects_non_admin_websocket():
    client = _client()
    client.cookies.set("odysseus_session", "guest-session")

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/terminal/ws", headers={"origin": "http://testserver"}
        ):
            pass

    assert exc.value.code == 4403


def test_terminal_rejects_cross_site_websocket():
    client = _client()
    client.cookies.set("odysseus_session", "admin-session")

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/terminal/ws", headers={"origin": "https://attacker.example"}
        ):
            pass

    assert exc.value.code == 4403


def test_terminal_admin_gets_interactive_container_pty(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_TERMINAL_SHELL", "/bin/sh")
    client = _client()
    client.cookies.set("odysseus_session", "admin-session")

    with client.websocket_connect(
        "/api/terminal/ws", headers={"origin": "http://testserver"}
    ) as websocket:
        websocket.send_text(json.dumps({"type": "resize", "cols": 90, "rows": 25}))
        websocket.send_text(
            json.dumps({"type": "input", "data": "printf '__ODY_TERM_OK__\\n'\n"})
        )
        output = b""
        for _ in range(10):
            output += websocket.receive_bytes()
            if b"__ODY_TERM_OK__" in output:
                break

    assert b"__ODY_TERM_OK__" in output


def test_terminal_http_fallback_gets_interactive_output(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_TERMINAL_SHELL", "/bin/sh")
    client = _client()
    client.cookies.set("odysseus_session", "admin-session")

    session_id = client.post("/api/terminal/session").json()["id"]
    client.post(
        f"/api/terminal/session/{session_id}/input",
        json={"data": "printf '__ODY_HTTP_TERM_OK__\\n'\n"},
    )
    output = b""
    for _ in range(20):
        response = client.get(f"/api/terminal/session/{session_id}/output")
        output += response.content
        if b"__ODY_HTTP_TERM_OK__" in output:
            break
        time.sleep(0.02)
    client.delete(f"/api/terminal/session/{session_id}")

    assert b"__ODY_HTTP_TERM_OK__" in output


def test_terminal_ui_is_wired_into_sidebar_rail_and_deep_link():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    index = (root / "static/index.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    terminal_js = (root / "static/js/terminal.js").read_text(encoding="utf-8")

    assert 'id="tool-terminal-btn"' in index
    assert 'id="rail-terminal"' in index
    assert "'/terminal':  () => terminalModule.open()" in app_js
    assert "/api/terminal/ws" in terminal_js
    assert "type: 'resize'" in terminal_js
    assert "terminal-modal-content" in terminal_js
    assert "makeWindowDraggable" in terminal_js
    assert "Modals.injectMinimizeButton" in terminal_js
    assert "_connectHttp" in terminal_js
