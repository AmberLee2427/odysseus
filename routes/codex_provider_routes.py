"""Local-only OpenAI-shaped transport backed by the authenticated Codex CLI."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.codex_app_server import CodexAppServerError, list_codex_models, stream_codex_chat


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    forwarded = any(
        request.headers.get(name)
        for name in ("forwarded", "x-forwarded-for", "x-real-ip", "cf-connecting-ip")
    )
    if host not in {"127.0.0.1", "::1"} or forwarded:
        raise HTTPException(403, "Codex provider is local-only")


def setup_codex_provider_routes() -> APIRouter:
    router = APIRouter(prefix="/api/codex-provider/v1", tags=["codex-provider"])

    @router.get("/models")
    async def models(request: Request):
        _require_loopback(request)
        try:
            model_ids = await list_codex_models()
        except (CodexAppServerError, OSError) as exc:
            raise HTTPException(503, str(exc))
        return {"object": "list", "data": [{"id": model, "object": "model"} for model in model_ids]}

    @router.post("/chat/completions")
    async def chat_completions(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
        _require_loopback(request)
        messages = body.get("messages")
        model = str(body.get("model") or "").strip()
        if not isinstance(messages, list) or not model:
            raise HTTPException(400, "model and messages are required")

        completion_id = f"chatcmpl-codex-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        async def events():
            full_text: list[str] = []
            try:
                async for event in stream_codex_chat(messages, model):
                    if event["type"] == "text":
                        text = event["text"]
                        full_text.append(text)
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    elif event["type"] == "usage":
                        usage = event["usage"]
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [],
                            "usage": {
                                "prompt_tokens": usage.get("inputTokens", 0),
                                "completion_tokens": usage.get("outputTokens", 0),
                                "total_tokens": usage.get("totalTokens", 0),
                            },
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
            except (CodexAppServerError, OSError) as exc:
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"\n\n[Codex provider error: {exc}]"},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

        if body.get("stream"):
            return StreamingResponse(events(), media_type="text/event-stream")

        text = []
        try:
            async for event in stream_codex_chat(messages, model):
                if event["type"] == "text":
                    text.append(event["text"])
        except (CodexAppServerError, OSError) as exc:
            raise HTTPException(502, str(exc))
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "".join(text)},
                    "finish_reason": "stop",
                }
            ],
        }

    return router
