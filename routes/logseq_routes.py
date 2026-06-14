"""Authenticated API for the configured Logseq Markdown graph."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.auth_helpers import get_current_user, require_user
from src.logseq_graph import LogseqGraph
from src.tool_security import owner_is_admin_or_single_user


class PageWrite(BaseModel):
    content: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class PageAppend(BaseModel):
    content: str


def _require_graph_admin(request: Request) -> str:
    owner = require_user(request)
    if not owner_is_admin_or_single_user(get_current_user(request)):
        raise HTTPException(403, "Logseq graph access is admin-only")
    return owner


def setup_logseq_routes() -> APIRouter:
    router = APIRouter(prefix="/api/logseq", tags=["logseq"])

    @router.get("/status")
    def status(request: Request):
        _require_graph_admin(request)
        return LogseqGraph().status()

    @router.get("/pages")
    def list_pages(
        request: Request,
        query: str = Query(default=""),
        tag: str = Query(default=""),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        _require_graph_admin(request)
        return {"pages": LogseqGraph().list_pages(query=query, tag=tag, limit=limit)}

    @router.put("/pages/{title:path}")
    def write_page(request: Request, title: str, payload: PageWrite):
        _require_graph_admin(request)
        try:
            return LogseqGraph().upsert_page(title, payload.content, payload.properties)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/pages/{title:path}/append")
    def append_page(request: Request, title: str, payload: PageAppend):
        _require_graph_admin(request)
        try:
            return LogseqGraph().append_to_page(title, payload.content)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/pages/{title:path}/backlinks")
    def backlinks(request: Request, title: str):
        _require_graph_admin(request)
        return {"backlinks": LogseqGraph().backlinks(title)}

    @router.get("/pages/{title:path}")
    def read_page(request: Request, title: str):
        _require_graph_admin(request)
        page = LogseqGraph().get_page(title)
        if not page:
            raise HTTPException(404, "Logseq page not found")
        return page

    return router
