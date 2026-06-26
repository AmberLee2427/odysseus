"""Browser companion routes for the Odysseus Chrome extension."""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.auth_helpers import get_current_user
from src.endpoint_resolver import resolve_endpoint
from src.settings import load_settings


MAX_PAGE_TEXT_CHARS = 60_000
MAX_SELECTED_TEXT_CHARS = 20_000
MAX_PAGE_PROMPT_CHARS = 20_000
MAX_SELECTED_PROMPT_CHARS = 12_000
MAX_SUMMARY_CHARS = 8_000
MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024
CAPTURE_ROOT = os.path.join("data", "browser_captures")

_DATA_URL_RE = re.compile(
    r"^data:image/(?P<kind>png|jpe?g|webp);base64,(?P<data>[a-z0-9+/=\s]+)$",
    re.IGNORECASE,
)


class BrowserPageContext(BaseModel):
    title: str = Field("", max_length=500)
    url: str = Field("", max_length=4000)
    selected_text: str = Field("", max_length=MAX_SELECTED_TEXT_CHARS)
    text: str = Field("", max_length=MAX_PAGE_TEXT_CHARS)
    html_excerpt: str = Field("", max_length=20_000)


class BrowserSummaryRequest(BaseModel):
    page: BrowserPageContext
    instruction: str = Field("", max_length=1000)
    session_id: str = Field("", max_length=100)


class BrowserScreenshotRequest(BaseModel):
    title: str = Field("", max_length=500)
    url: str = Field("", max_length=4000)
    data_url: str = Field(..., max_length=MAX_SCREENSHOT_BYTES * 2)


def _require_browser_scope(request: Request, scope: str = "browser:read") -> None:
    """Allow normal cookie sessions, or bearer tokens with browser scopes."""
    if not getattr(request.state, "api_token", False):
        return
    scopes = set(getattr(request.state, "api_token_scopes", []) or [])
    if scope not in scopes:
        raise HTTPException(403, f"API token is not scoped for {scope}")


def _owner(request: Request) -> Optional[str]:
    if getattr(request.state, "api_token", False):
        return getattr(request.state, "api_token_owner", None)
    return get_current_user(request)


def _safe_owner_dir(owner: Optional[str]) -> str:
    value = owner or "shared"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._") or "shared"


def _trim(value: str, limit: int) -> str:
    value = value or ""
    return value if len(value) <= limit else value[:limit] + "\n\n[truncated]"


def _session_title(page: BrowserPageContext) -> str:
    title = (page.title or page.url or "Browser page").strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) > 70:
        title = title[:67].rstrip() + "..."
    return f"Browser: {title}"


def _verify_session_owner(session, owner: Optional[str]) -> None:
    if not session:
        raise HTTPException(404, "Session not found")
    if owner and getattr(session, "owner", None) != owner:
        raise HTTPException(404, "Session not found")


def _decode_image_data_url(data_url: str) -> tuple[str, bytes]:
    match = _DATA_URL_RE.fullmatch(data_url or "")
    if not match:
        raise HTTPException(400, "Screenshot must be a PNG, JPEG, or WebP data URL")
    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(400, "Screenshot data is not valid base64") from error
    if not raw:
        raise HTTPException(400, "Screenshot is empty")
    if len(raw) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(413, "Screenshot is larger than 16 MB")
    kind = match.group("kind").lower()
    ext = "jpg" if kind in {"jpg", "jpeg"} else kind
    return ext, raw


def _browser_model_status(owner: Optional[str]) -> dict:
    settings = load_settings()
    status = {}
    for name, prefix in (
        ("reasoning", "browser_reasoning"),
        ("action", "browser_action"),
        ("vision", "browser_vision"),
    ):
        endpoint_url, model, _headers = resolve_endpoint(prefix, owner=owner)
        status[name] = {
            "configured_endpoint_id": settings.get(f"{prefix}_endpoint_id", ""),
            "configured_model": settings.get(f"{prefix}_model", ""),
            "resolved": bool(endpoint_url and model),
            "model": model or "",
        }
    return status


def setup_browser_routes(session_manager=None) -> APIRouter:
    router = APIRouter(prefix="/api/browser", tags=["browser"])

    @router.get("/ping")
    async def ping(request: Request):
        _require_browser_scope(request, "browser:read")
        return {
            "ok": True,
            "name": "odysseus-browser",
            "owner": _owner(request),
            "models": _browser_model_status(_owner(request)),
        }

    @router.get("/settings")
    async def settings(request: Request):
        _require_browser_scope(request, "browser:read")
        return {
            "owner": _owner(request),
            "models": _browser_model_status(_owner(request)),
            "capabilities": {
                "page_summary": True,
                "visible_tab_screenshot": True,
                "page_actions": False,
                "overleaf_adapter": False,
            },
        }

    @router.get("/sessions")
    async def sessions(request: Request):
        _require_browser_scope(request, "browser:read")
        owner = _owner(request)
        if session_manager is None:
            return {"sessions": []}
        rows = session_manager.get_sessions_for_user(owner) if owner else {}
        out = []
        for session in rows.values():
            name = (getattr(session, "name", "") or "").strip()
            if not name or name in {"Nobody", "Incognito"} or getattr(session, "archived", False):
                continue
            out.append({
                "id": session.id,
                "name": name,
                "model": session.model or "",
            })
        out.sort(key=lambda row: row["name"].lower())
        return {"sessions": out[:100]}

    @router.post("/summarize")
    async def summarize(request: Request, body: BrowserSummaryRequest):
        _require_browser_scope(request, "browser:read")
        owner = _owner(request)
        endpoint_url, model, headers = resolve_endpoint("browser_reasoning", owner=owner)
        if not endpoint_url or not model:
            raise HTTPException(400, "No browser reasoning, utility, or default model is configured")

        page = body.page
        text = (page.selected_text or page.text or page.html_excerpt or "").strip()
        if not text:
            raise HTTPException(400, "No page text was provided")

        instruction = body.instruction.strip() or "Summarize this browser page for Amber."
        user_content = (
            f"Instruction: {instruction}\n\n"
            f"Title: {_trim(page.title, 500)}\n"
            f"URL: {_trim(page.url, 4000)}\n\n"
            f"Selected text:\n{_trim(page.selected_text, MAX_SELECTED_PROMPT_CHARS)}\n\n"
            f"Visible/readable page text:\n{_trim(page.text, MAX_PAGE_PROMPT_CHARS)}"
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You summarize browser pages for the user. Be concise, faithful to the "
                    "provided page text, and call out uncertainty when the page text is sparse."
                ),
            },
            {"role": "user", "content": user_content},
        ]

        from src.llm_core import llm_call_async

        timeout = float(load_settings().get("browser_summary_timeout_seconds") or 65)
        try:
            summary = await asyncio.wait_for(
                llm_call_async(
                    endpoint_url,
                    model,
                    messages,
                    headers=headers,
                    timeout=timeout,
                    max_retries=1,
                    max_tokens=900,
                ),
                timeout=timeout + 5,
            )
        except asyncio.TimeoutError as error:
            raise HTTPException(504, "Browser summary timed out") from error
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(502, "Browser summary model call failed") from error
        session_payload = {}
        if session_manager is not None:
            from core.models import ChatMessage

            requested_session_id = (body.session_id or "").strip()
            if requested_session_id:
                try:
                    new_session = session_manager.get_session(requested_session_id)
                except KeyError as error:
                    raise HTTPException(404, "Session not found") from error
                _verify_session_owner(new_session, owner)
                session_id = requested_session_id
                appended = True
            else:
                session_id = str(uuid.uuid4())
                new_session = session_manager.create_session(
                    session_id=session_id,
                    name=_session_title(page),
                    endpoint_url=endpoint_url,
                    model=model,
                    rag=False,
                    owner=owner,
                )
                if headers:
                    new_session.headers = dict(headers)
                    session_manager.save_sessions()
                appended = False

            context = (
                "Browser page context for follow-up questions.\n\n"
                f"Title: {page.title or '(untitled)'}\n"
                f"URL: {page.url or '(unknown)'}\n\n"
                f"Captured page text:\n{_trim(text, MAX_PAGE_PROMPT_CHARS)}"
            )
            new_session.add_message(ChatMessage(
                role="system",
                content=context,
                metadata={"source": "browser_companion", "url": page.url},
            ))
            new_session.add_message(ChatMessage(
                role="user",
                content=instruction,
                metadata={"source": "browser_companion", "url": page.url},
            ))
            new_session.add_message(ChatMessage(
                role="assistant",
                content=summary or "",
                metadata={"source": "browser_companion", "url": page.url},
            ))
            session_manager.save_sessions()
            try:
                from src.event_bus import fire_event
                fire_event("session_created", owner)
            except Exception:
                pass
            session_payload = {
                "saved": True,
                "appended": appended,
                "session_id": session_id,
                "session_url": f"/#session-{session_id}",
                "session_name": new_session.name,
            }
        return {
            "summary": _trim(summary or "", MAX_SUMMARY_CHARS),
            "model": model,
            "url": page.url,
            "title": page.title,
            **session_payload,
        }

    @router.post("/captures/screenshot")
    async def capture_screenshot(request: Request, body: BrowserScreenshotRequest):
        _require_browser_scope(request, "browser:write")
        ext, raw = _decode_image_data_url(body.data_url)
        owner = _owner(request)
        capture_id = f"{int(time.time())}-{uuid.uuid4().hex[:10]}"
        owner_dir = os.path.join(CAPTURE_ROOT, _safe_owner_dir(owner))
        os.makedirs(owner_dir, exist_ok=True)
        filename = f"{capture_id}.{ext}"
        path = os.path.join(owner_dir, filename)
        with open(path, "xb") as handle:
            handle.write(raw)
        sidecar = os.path.join(owner_dir, f"{capture_id}.txt")
        with open(sidecar, "x", encoding="utf-8") as handle:
            handle.write(f"Title: {body.title}\nURL: {body.url}\n")
        return {
            "id": capture_id,
            "filename": filename,
            "path": path,
            "bytes": len(raw),
            "content_type": f"image/{'jpeg' if ext == 'jpg' else ext}",
        }

    return router
