"""Routes for local, git-backed LaTeX manuscript workspaces."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from services import latex_projects
from src.auth_helpers import get_current_user


def _require_scope(request: Request, scope: str) -> None:
    if not getattr(request.state, "api_token", False):
        return
    scopes = set(getattr(request.state, "api_token_scopes", []) or [])
    if scope not in scopes:
        from fastapi import HTTPException

        raise HTTPException(403, f"API token is not scoped for {scope}")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatexProjectCreate(_StrictModel):
    latex_project_id: Optional[str] = None
    odysseus_project_id: Optional[str] = None
    title: str = "LaTeX Project"
    root_file: str = "main.tex"
    tags: list[str] = Field(default_factory=lambda: ["manuscript", "latex"])
    overleaf_project_id: str = ""
    git_remote: str = ""
    credential_id: str = ""


class LatexProjectPatch(_StrictModel):
    odysseus_project_id: Optional[str] = None
    title: Optional[str] = None
    root_file: Optional[str] = None
    tags: Optional[list[str]] = None
    overleaf: Optional[dict[str, Any]] = None
    files: Optional[dict[str, Any]] = None


class LatexCredentialUpsert(_StrictModel):
    credential_id: str = "overleaf"
    username: str = ""
    token: str


def setup_latex_project_routes() -> APIRouter:
    router = APIRouter(prefix="/api/latex-projects", tags=["latex-projects"])

    @router.get("")
    async def list_latex_projects(request: Request):
        _require_scope(request, "documents:read")
        owner = get_current_user(request)
        return {"projects": latex_projects.list_projects(owner)}

    @router.post("")
    async def create_latex_project(request: Request, body: LatexProjectCreate):
        _require_scope(request, "documents:write")
        owner = get_current_user(request)
        metadata = latex_projects.create_or_update_metadata(owner, body.model_dump())
        return {"ok": True, "project": metadata}

    @router.get("/credentials")
    async def list_credentials(request: Request):
        _require_scope(request, "documents:read")
        owner = get_current_user(request)
        return {"credentials": latex_projects.credential_status(owner)}

    @router.post("/credentials")
    async def upsert_credential(request: Request, body: LatexCredentialUpsert):
        _require_scope(request, "documents:write")
        owner = get_current_user(request)
        return latex_projects.store_credential(
            owner,
            body.credential_id,
            username=body.username,
            token=body.token,
        )

    @router.delete("/credentials/{credential_id}")
    async def delete_credential(request: Request, credential_id: str):
        _require_scope(request, "documents:write")
        owner = get_current_user(request)
        return {"ok": latex_projects.delete_credential(owner, credential_id)}

    @router.get("/{latex_project_id}/metadata")
    async def read_metadata(request: Request, latex_project_id: str):
        _require_scope(request, "documents:read")
        owner = get_current_user(request)
        return latex_projects.read_metadata(owner, latex_project_id)

    @router.patch("/{latex_project_id}/metadata")
    async def patch_metadata(request: Request, latex_project_id: str, body: LatexProjectPatch):
        _require_scope(request, "documents:write")
        owner = get_current_user(request)
        return latex_projects.patch_metadata(
            owner,
            latex_project_id,
            body.model_dump(exclude_unset=True),
        )

    @router.get("/{latex_project_id}/tree")
    async def project_tree(request: Request, latex_project_id: str, max_entries: int = 400):
        _require_scope(request, "documents:read")
        owner = get_current_user(request)
        return latex_projects.project_tree(owner, latex_project_id, max_entries=max_entries)

    @router.get("/{latex_project_id}/status")
    async def project_status(request: Request, latex_project_id: str):
        _require_scope(request, "documents:read")
        owner = get_current_user(request)
        metadata = latex_projects.read_metadata(owner, latex_project_id)
        return {
            "latex_project_id": latex_project_id,
            "metadata": metadata,
            "git": latex_projects.git_status(owner, latex_project_id),
        }

    return router
