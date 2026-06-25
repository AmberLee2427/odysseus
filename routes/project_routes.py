"""Project Registry API routes."""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from core.database import Document, Note, ScheduledTask, Session as ChatSession, SessionLocal
from services.project_registry import ProjectNotFoundError, ProjectRegistry
from src.auth_helpers import get_current_user

logger = logging.getLogger(__name__)


class _ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(_ProjectModel):
    project_id: Optional[str] = None
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    root_path: Optional[str] = None
    tags: Optional[List[str]] = None
    logseq_page_path: Optional[str] = None
    mirror: Optional[Dict[str, Any]] = None


class ProjectUpdate(_ProjectModel):
    name: Optional[str] = None
    description: Optional[str] = None
    root_path: Optional[str] = None
    tags: Optional[List[str]] = None
    logseq_page_path: Optional[str] = None
    mirror: Optional[Dict[str, Any]] = None


def _provided(body: BaseModel, field: str) -> bool:
    fields = getattr(body, "model_fields_set", None)
    if fields is None:
        fields = getattr(body, "__fields_set__", set())
    return field in fields


def setup_project_routes() -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("")
    async def list_projects(request: Request, include_archived: bool = False):
        db = SessionLocal()
        try:
            registry = ProjectRegistry(db, get_current_user(request))
            return {"projects": registry.list_projects(include_archived=include_archived)}
        finally:
            db.close()

    @router.get("/{project_id}")
    async def get_project(request: Request, project_id: str):
        db = SessionLocal()
        try:
            registry = ProjectRegistry(db, get_current_user(request))
            return registry.get_project(project_id)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        finally:
            db.close()

    @router.get("/{project_id}/context")
    async def get_project_context(request: Request, project_id: str):
        """Context-safe board annotations grouped by their linked artifact."""
        db = SessionLocal()
        try:
            project = ProjectRegistry(db, get_current_user(request)).get_project(project_id, include_archived=False)
            cards = ((project.get("mirror") or {}).get("board") or {}).get("cards") or []
            annotations = {}
            for card in cards:
                if card.get("type") != "annotation" or not card.get("include_context"):
                    continue
                item = {"text": card.get("text", ""), "title": card.get("title", ""), "tags": card.get("tags") or []}
                annotations.setdefault(card.get("backlink") or "project", []).append(item)
            return {"project_id": project_id, "annotations_by_artifact": annotations}
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        finally:
            db.close()

    @router.post("")
    async def create_project(request: Request, body: ProjectCreate):
        db = SessionLocal()
        try:
            registry = ProjectRegistry(db, get_current_user(request))
            return registry.create_project(
                project_id=body.project_id or body.id,
                name=body.name,
                description=body.description,
                root_path=body.root_path,
                tags=body.tags,
                logseq_page_path=body.logseq_page_path,
                mirror=body.mirror,
            )
        except ValueError as error:
            db.rollback()
            raise HTTPException(400, str(error))
        except Exception as error:
            db.rollback()
            logger.warning("project create failed: %s", error)
            raise HTTPException(500, "Could not create project")
        finally:
            db.close()

    @router.patch("/{project_id}")
    async def update_project(request: Request, project_id: str, body: ProjectUpdate):
        db = SessionLocal()
        try:
            registry = ProjectRegistry(db, get_current_user(request))
            kwargs = {}
            if _provided(body, "name"):
                kwargs["name"] = body.name
            if _provided(body, "description"):
                kwargs["description"] = body.description or ""
            if _provided(body, "root_path"):
                kwargs["root_path"] = body.root_path or ""
            if _provided(body, "tags"):
                kwargs["tags"] = body.tags or []
            if _provided(body, "logseq_page_path"):
                kwargs["logseq_page_path"] = body.logseq_page_path or ""
            if _provided(body, "mirror"):
                kwargs["mirror"] = body.mirror or {}
            return registry.update_project(project_id, **kwargs)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        except ValueError as error:
            db.rollback()
            raise HTTPException(400, str(error))
        except Exception as error:
            db.rollback()
            logger.warning("project update failed: %s", error)
            raise HTTPException(500, "Could not update project")
        finally:
            db.close()

    @router.post("/{project_id}/artifacts/{artifact_type}/{artifact_id}")
    async def assign_artifact(request: Request, project_id: str, artifact_type: str, artifact_id: str):
        """Attach one artifact to a project; board layout remains separate."""
        models = {
            "chat": ChatSession,
            "note": Note,
            "task": ScheduledTask,
            "document": Document,
        }
        model = models.get(artifact_type)
        if model is None:
            raise HTTPException(400, "Unknown artifact type")
        db = SessionLocal()
        try:
            registry = ProjectRegistry(db, get_current_user(request))
            registry.get_project(project_id, include_archived=False)
            artifact = db.query(model).filter(model.id == artifact_id).first()
            owner = get_current_user(request)
            if not artifact or (owner is not None and getattr(artifact, "owner", None) != owner):
                raise HTTPException(404, "Artifact not found")
            artifact.project_id = project_id
            if not getattr(artifact, "tags_json", None):
                artifact.tags_json = json.dumps([])
            db.commit()
            return {"ok": True, "project_id": project_id, "artifact_type": artifact_type, "artifact_id": artifact_id}
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        finally:
            db.close()

    @router.post("/{project_id}/archive")
    async def archive_project(request: Request, project_id: str):
        db = SessionLocal()
        try:
            registry = ProjectRegistry(db, get_current_user(request))
            return registry.archive_project(project_id)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        except Exception as error:
            db.rollback()
            logger.warning("project archive failed: %s", error)
            raise HTTPException(500, "Could not archive project")
        finally:
            db.close()

    @router.delete("/{project_id}")
    async def delete_project(request: Request, project_id: str):
        return await archive_project(request, project_id)

    return router
