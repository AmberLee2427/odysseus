"""Admin-only interactive terminal backed by a container-local PTY."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import struct
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from routes.auth_routes import SESSION_COOKIE

try:
    import fcntl
    import pty
    import termios
except ImportError:
    fcntl = None
    pty = None
    termios = None


def _enabled() -> bool:
    return os.getenv("ODYSSEUS_TERMINAL_ENABLED", "true").lower() == "true"


def _same_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin or not host:
        return False
    return urlparse(origin).netloc.lower() == host.lower()


def _resize(master_fd: int, cols: int, rows: int) -> None:
    cols = max(20, min(cols, 500))
    rows = max(5, min(rows, 200))
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _spawn_terminal() -> tuple[int, int]:
    shell = os.getenv("ODYSSEUS_TERMINAL_SHELL", "/bin/bash")
    cwd = os.getenv("ODYSSEUS_TERMINAL_CWD", "/app")
    if not os.path.isfile(shell):
        shell = "/bin/sh"
    if not os.path.isdir(cwd):
        cwd = "/app"

    pid, master_fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        env = dict(os.environ)
        env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor"})
        os.execvpe(shell, [shell], env)
    return pid, master_fd


def _stop_terminal(pid: int, master_fd: int) -> None:
    try:
        os.close(master_fd)
    except OSError:
        pass
    try:
        os.killpg(pid, signal.SIGHUP)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


_http_sessions: dict[str, dict] = {}


def _require_admin_request(request: Request, auth_manager) -> str:
    username = getattr(request.state, "current_user", None)
    if not username or username == "api" or not auth_manager.is_admin(username):
        raise HTTPException(403, "Admin only")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site terminal request rejected")
    return username


def _drop_http_terminal(session_id: str) -> None:
    session = _http_sessions.pop(session_id, None)
    if not session:
        return
    _stop_terminal(session["pid"], session["fd"])


def _prune_http_terminals() -> None:
    cutoff = time.monotonic() - 30 * 60
    for session_id, session in list(_http_sessions.items()):
        if session["last_active"] < cutoff:
            _drop_http_terminal(session_id)


def setup_terminal_routes(auth_manager) -> APIRouter:
    router = APIRouter(tags=["terminal"])

    @router.post("/api/terminal/session")
    async def create_terminal_session(request: Request):
        if not _enabled() or pty is None or fcntl is None or termios is None:
            raise HTTPException(404, "Terminal unavailable")
        username = _require_admin_request(request, auth_manager)
        _prune_http_terminals()
        for old_id, session in list(_http_sessions.items()):
            if session["owner"] == username and not session["closed"]:
                if request.query_params.get("new") == "1":
                    _drop_http_terminal(old_id)
                    break
                session["last_active"] = time.monotonic()
                return {"id": old_id, "reused": True}
        pid, master_fd = _spawn_terminal()
        os.set_blocking(master_fd, False)
        _resize(master_fd, 100, 30)
        session_id = secrets.token_urlsafe(24)
        _http_sessions[session_id] = {
            "owner": username,
            "pid": pid,
            "fd": master_fd,
            "closed": False,
            "last_active": time.monotonic(),
        }
        return {"id": session_id, "reused": False}

    @router.get("/api/terminal/session")
    async def terminal_session_status(request: Request):
        username = _require_admin_request(request, auth_manager)
        _prune_http_terminals()
        for session_id, session in _http_sessions.items():
            if session["owner"] == username and not session["closed"]:
                return {"active": True, "id": session_id}
        return {"active": False, "id": None}

    def owned_session(request: Request, session_id: str) -> dict:
        username = _require_admin_request(request, auth_manager)
        session = _http_sessions.get(session_id)
        if not session or session["owner"] != username:
            raise HTTPException(404, "Terminal session not found")
        session["last_active"] = time.monotonic()
        return session

    @router.get("/api/terminal/session/{session_id}/output")
    async def terminal_output(request: Request, session_id: str):
        session = owned_session(request, session_id)
        chunks = []
        while not session["closed"]:
            try:
                data = os.read(session["fd"], 65536)
            except BlockingIOError:
                break
            except OSError:
                session["closed"] = True
                break
            if not data:
                session["closed"] = True
                break
            chunks.append(data)
        return Response(
            content=b"".join(chunks),
            media_type="application/octet-stream",
            headers={"X-Terminal-Closed": "1" if session["closed"] else "0"},
        )

    @router.post("/api/terminal/session/{session_id}/input")
    async def terminal_input(
        request: Request, session_id: str, payload: dict = Body(default_factory=dict)
    ):
        session = owned_session(request, session_id)
        try:
            os.write(session["fd"], str(payload.get("data", "")).encode())
        except OSError as error:
            session["closed"] = True
            raise HTTPException(410, "Terminal session closed") from error
        return {"ok": True}

    @router.post("/api/terminal/session/{session_id}/resize")
    async def terminal_resize(
        request: Request, session_id: str, payload: dict = Body(default_factory=dict)
    ):
        session = owned_session(request, session_id)
        _resize(
            session["fd"],
            int(payload.get("cols", 100)),
            int(payload.get("rows", 30)),
        )
        return {"ok": True}

    @router.delete("/api/terminal/session/{session_id}")
    async def close_terminal_session(request: Request, session_id: str):
        owned_session(request, session_id)
        _drop_http_terminal(session_id)
        return {"ok": True}

    @router.websocket("/api/terminal/ws")
    async def terminal_websocket(websocket: WebSocket):
        if not _enabled() or pty is None or fcntl is None or termios is None:
            await websocket.close(code=4404, reason="Terminal unavailable")
            return
        if not _same_origin(websocket):
            await websocket.close(code=4403, reason="Cross-site terminal connection rejected")
            return

        token = websocket.cookies.get(SESSION_COOKIE)
        username = auth_manager.get_username_for_token(token)
        if not username or not auth_manager.is_admin(username):
            await websocket.close(code=4403, reason="Admin only")
            return

        await websocket.accept()
        pid, master_fd = _spawn_terminal()
        _resize(master_fd, 100, 30)

        async def send_output():
            while True:
                data = await asyncio.to_thread(os.read, master_fd, 65536)
                if not data:
                    break
                await websocket.send_bytes(data)

        output_task = asyncio.create_task(send_output())
        try:
            while True:
                message = await websocket.receive_text()
                payload = json.loads(message)
                if payload.get("type") == "input":
                    os.write(master_fd, str(payload.get("data", "")).encode())
                elif payload.get("type") == "resize":
                    _resize(
                        master_fd,
                        int(payload.get("cols", 100)),
                        int(payload.get("rows", 30)),
                    )
        except (WebSocketDisconnect, json.JSONDecodeError, ValueError, OSError):
            pass
        finally:
            _stop_terminal(pid, master_fd)
            output_task.cancel()
            await asyncio.gather(output_task, return_exceptions=True)

    return router
