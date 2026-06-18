"""Project worktree API adapter.

The project registry remains the source of truth for stable projects. These
endpoints resolve `project_id` to the durable `root_path` and only operate on
branch/run-specific Git worktrees attached to that root.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal
from services.git_worktrees import GitCommandError, GitWorktreeService, WorktreeSafetyError
from services.project_registry import ProjectNotFoundError, ProjectRegistry
from src.auth_helpers import get_current_user


ProjectRootResolver = Callable[[str], str | None]


class CreateWorktreeRequest(BaseModel):
    path: str
    branch: str | None = None
    new_branch: str | None = None
    start_point: str | None = None


class RemoveWorktreeRequest(BaseModel):
    path: str


def setup_project_worktree_routes(
    resolve_project_root: ProjectRootResolver | None = None,
    service: GitWorktreeService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/worktrees", tags=["project-worktrees"])
    worktrees = service or GitWorktreeService()

    def root_for(request: Request, project_id: str) -> str:
        if resolve_project_root is not None:
            root = resolve_project_root(project_id)
        else:
            db = SessionLocal()
            try:
                project = ProjectRegistry(db, get_current_user(request)).get_project(project_id)
                root = project.get("root_path")
            except ProjectNotFoundError:
                raise HTTPException(status_code=404, detail="Project not found")
            finally:
                db.close()
        if not root:
            raise HTTPException(status_code=400, detail="Project root_path is required before using worktrees")
        return root

    def translate_error(error: Exception) -> HTTPException:
        if isinstance(error, WorktreeSafetyError):
            return HTTPException(status_code=400, detail=str(error))
        if isinstance(error, GitCommandError):
            return HTTPException(status_code=400, detail=str(error))
        return HTTPException(status_code=500, detail="Worktree operation failed")

    @router.get("")
    def list_worktrees(request: Request, project_id: str):
        try:
            root = root_for(request, project_id)
            return {
                "project_id": project_id,
                "root_path": root,
                "worktrees": [worktree.to_dict() for worktree in worktrees.list(root)],
                "branches": worktrees.list_branches(root),
            }
        except HTTPException:
            raise
        except Exception as error:
            raise translate_error(error) from error

    @router.post("")
    def create_worktree(request: Request, project_id: str, body: CreateWorktreeRequest):
        try:
            root = root_for(request, project_id)
            created = worktrees.add(
                root,
                body.path,
                branch=body.branch,
                new_branch=body.new_branch,
                start_point=body.start_point,
            )
            return {"project_id": project_id, "root_path": root, "worktree": created.to_dict()}
        except HTTPException:
            raise
        except Exception as error:
            raise translate_error(error) from error

    @router.delete("")
    def remove_worktree(request: Request, project_id: str, body: RemoveWorktreeRequest):
        try:
            root = root_for(request, project_id)
            worktrees.remove(root, body.path)
            return {"project_id": project_id, "removed": True, "path": body.path}
        except HTTPException:
            raise
        except Exception as error:
            raise translate_error(error) from error

    return router
