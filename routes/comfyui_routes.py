"""ComfyUI backend-control routes.

These endpoints keep the browser on Odysseus' HTTPS origin while Odysseus talks
to the local ComfyUI server from the backend. That avoids mixed-content iframe
blocks without requiring a public ComfyUI hostname.
"""

import os
import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from routes.gallery_routes import _comfyui_output_images
from src.auth_helpers import require_privilege


def _comfyui_server_url() -> str:
    configured = os.getenv("COMFYUI_SERVER_URL", "").strip().rstrip("/")
    if configured:
        return configured
    host = "host.docker.internal" if os.path.exists("/.dockerenv") else "127.0.0.1"
    return f"http://{host}:{os.getenv('COMFYUI_PORT', '8188')}"


def _comfyui_public_url(request: Request) -> str:
    configured = (
        os.getenv("COMFYUI_PUBLIC_URL", "").strip()
        or os.getenv("COMFYUI_EXTERNAL_URL", "").strip()
        or os.getenv("COMFYUI_URL", "").strip()
    )
    if configured:
        return configured.rstrip("/")
    hostname = request.url.hostname or "127.0.0.1"
    return f"http://{hostname}:{os.getenv('COMFYUI_PORT', '8188')}"


def _filename_is_safe(filename: str) -> bool:
    if not filename or "/" in filename or "\\" in filename:
        return False
    name = Path(filename).name
    return name == filename and name not in {".", ".."}


def _workflow_dirs() -> list[Path]:
    configured = os.getenv("COMFYUI_WORKFLOW_DIRS", "").strip()
    parts = configured.split(os.pathsep) if configured else []
    parts.extend([
        "data/comfyui_workflows",
        "comfyui_workflows",
    ])
    dirs: list[Path] = []
    for part in parts:
        if not part:
            continue
        path = Path(part).expanduser()
        if path.exists() and path.is_dir() and path not in dirs:
            dirs.append(path)
    return dirs


def _workflow_files() -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for directory in _workflow_dirs():
        for path in sorted(directory.glob("*.json")):
            if path.name in seen:
                continue
            seen.add(path.name)
            files.append(path)
    return files


def _workflow_path(name: str) -> Path:
    safe_name = Path(name).name
    if safe_name != name or not safe_name.endswith(".json"):
        raise HTTPException(400, "Unsafe workflow name")
    for path in _workflow_files():
        if path.name == safe_name:
            return path
    raise HTTPException(404, "Workflow not found")


def _workflow_label(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def _workflow_summary(graph: dict[str, Any]) -> dict[str, Any]:
    prompts: list[dict[str, str]] = []
    models: list[str] = []
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        title = str((node.get("_meta") or {}).get("title") or node.get("class_type") or node_id)
        for key in ("text", "prompt", "positive", "negative"):
            value = inputs.get(key)
            if isinstance(value, str):
                prompts.append({"node": str(node_id), "key": key, "title": title, "value": value})
        for key in ("ckpt_name", "unet_name", "model_name", "vae_name", "clip_name1", "clip_name2"):
            value = inputs.get(key)
            if isinstance(value, str) and value not in models:
                models.append(value)
    return {"prompts": prompts, "models": models}


async def _comfy_get(path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
    base = _comfyui_server_url()
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{base}{path}", params=params)
        response.raise_for_status()
        return response


def setup_comfyui_routes() -> APIRouter:
    router = APIRouter()

    @router.get("/api/comfyui/backend/config")
    async def comfyui_backend_config(request: Request):
        return {
            "ok": True,
            "mode": "backend",
            "public_url": _comfyui_public_url(request),
        }

    @router.get("/api/comfyui/status")
    async def comfyui_status():
        try:
            queue_response = await _comfy_get("/queue")
            stats_response = await _comfy_get("/system_stats")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        queue = queue_response.json()
        stats = stats_response.json()
        queue_running = queue.get("queue_running") if isinstance(queue, dict) else []
        queue_pending = queue.get("queue_pending") if isinstance(queue, dict) else []
        return {
            "ok": True,
            "queue_running": len(queue_running or []),
            "queue_pending": len(queue_pending or []),
            "queue": queue,
            "system_stats": stats,
        }

    @router.get("/api/comfyui/queue")
    async def comfyui_queue():
        try:
            response = await _comfy_get("/queue")
            return response.json()
        except Exception as exc:
            raise HTTPException(502, f"Could not reach ComfyUI queue: {exc}")

    @router.get("/api/comfyui/history")
    async def comfyui_history(max_items: int = Query(25, ge=1, le=200)):
        try:
            response = await _comfy_get("/history", params={"max_items": max_items})
            return response.json()
        except Exception as exc:
            raise HTTPException(502, f"Could not reach ComfyUI history: {exc}")

    @router.get("/api/comfyui/workflows")
    async def comfyui_workflows():
        workflows = []
        for path in _workflow_files():
            try:
                graph = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                graph = {}
            comment = graph.get("_comment") if isinstance(graph, dict) else ""
            workflows.append({
                "name": path.name,
                "label": _workflow_label(path),
                "description": comment or "",
                "summary": _workflow_summary(graph) if isinstance(graph, dict) else {"prompts": [], "models": []},
            })
        return {"ok": True, "workflows": workflows}

    @router.get("/api/comfyui/workflows/{name}")
    async def comfyui_workflow(name: str):
        path = _workflow_path(name)
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(500, f"Could not read workflow: {exc}")
        return {
            "ok": True,
            "name": path.name,
            "label": _workflow_label(path),
            "workflow": graph,
            "summary": _workflow_summary(graph) if isinstance(graph, dict) else {"prompts": [], "models": []},
        }

    @router.get("/api/comfyui/images")
    async def comfyui_images(
        max_items: int = Query(50, ge=1, le=200),
        limit: int = Query(24, ge=1, le=100),
    ):
        try:
            response = await _comfy_get("/history", params={"max_items": max_items})
            history = response.json()
            if not isinstance(history, dict):
                raise ValueError("ComfyUI returned invalid history")
        except Exception as exc:
            raise HTTPException(502, f"Could not reach ComfyUI history: {exc}")

        images = []
        for prompt_id, image, prompt, model in _comfyui_output_images(history):
            filename = str(image.get("filename") or "")
            if not _filename_is_safe(filename):
                continue
            query = urlencode({
                "filename": filename,
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            })
            images.append({
                "prompt_id": prompt_id,
                "filename": filename,
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
                "prompt": prompt,
                "model": model,
                "url": f"/api/comfyui/view?{query}",
            })
            if len(images) >= limit:
                break
        return {"ok": True, "images": images}

    @router.get("/api/comfyui/view")
    async def comfyui_view(
        filename: str = Query(..., min_length=1, max_length=255),
        subfolder: str = Query("", max_length=255),
        type: str = Query("output", pattern="^(output|input|temp)$"),
    ):
        if not _filename_is_safe(filename):
            raise HTTPException(400, "Unsafe ComfyUI filename")
        try:
            response = await _comfy_get(
                "/view",
                params={"filename": filename, "subfolder": subfolder, "type": type},
            )
        except Exception as exc:
            raise HTTPException(502, f"Could not fetch ComfyUI image: {exc}")

        content_type = response.headers.get("content-type", "application/octet-stream")
        return Response(
            content=response.content,
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=30"},
        )

    @router.post("/api/comfyui/prompt")
    async def comfyui_prompt(request: Request):
        require_privilege(request, "can_generate_images")
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "Expected JSON body")
        if not isinstance(payload, dict):
            raise HTTPException(400, "Expected a ComfyUI workflow JSON object")
        if isinstance(payload.get("prompt"), dict):
            prompt_payload = payload
        elif any(isinstance(node, dict) and "class_type" in node for node in payload.values()):
            prompt_payload = {"prompt": payload}
        else:
            raise HTTPException(400, "Expected a ComfyUI workflow or prompt JSON object")
        prompt_payload.setdefault("client_id", f"odysseus-{uuid.uuid4().hex}")

        base = _comfyui_server_url()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                response = await client.post(f"{base}/prompt", json=prompt_payload)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            raise HTTPException(502, f"Could not submit ComfyUI prompt: {exc}")

    return router
