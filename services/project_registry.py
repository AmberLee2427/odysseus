"""Backend service for the durable Project Registry."""

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.database import Project, utcnow_naive


class ProjectNotFoundError(LookupError):
    """Raised when a project is missing or hidden from the caller."""


STRUCTURAL_PROJECT_FIELDS = frozenset({
    "project_id",
    "id",
    "owner",
    "created_at",
    "updated_at",
    "archived",
    "archived_at",
})
"""Fields that are app invariants, not freely editable Logseq mirror state."""

MIRRORED_PROJECT_FIELDS = frozenset({
    "name",
    "description",
    "root_path",
    "tags",
    "logseq_page_path",
    "mirror",
})
"""Fields intended to be editable in the project page / Logseq mirror."""


def _clean_optional_text(value: Optional[str], *, max_len: int | None = None) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if max_len is not None:
        cleaned = cleaned[:max_len]
    return cleaned


def _clean_name(value: Optional[str]) -> str:
    name = _clean_optional_text(value, max_len=200)
    if not name:
        raise ValueError("Project name is required")
    return name


def _can_access(project: Project, owner: Optional[str]) -> bool:
    if owner is None:
        return True
    return project.owner == owner


def _json_load(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _clean_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_tags = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple, set)):
        raw_tags = list(value)
    else:
        raise ValueError("Project tags must be a list or string")
    tags = []
    seen = set()
    for raw in raw_tags:
        tag = str(raw).strip().lstrip("#")
        if tag.startswith("[[") and tag.endswith("]]"):
            tag = tag[2:-2].strip()
        if not tag:
            continue
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag[:120])
    return tags


def _clean_mirror(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Project mirror must be a JSON object")
    forbidden = sorted(STRUCTURAL_PROJECT_FIELDS.intersection(value.keys()))
    if forbidden:
        raise ValueError(
            "Project mirror cannot overwrite structural fields: " + ", ".join(forbidden)
        )
    return value


def project_to_dict(project: Project) -> Dict[str, Any]:
    archived_at = project.archived_at.isoformat() if project.archived_at else None
    return {
        "project_id": project.project_id,
        "id": project.project_id,
        "name": project.name,
        "description": project.description or "",
        "root_path": project.root_path,
        "tags": _json_load(project.tags_json, []),
        "logseq_page_path": project.logseq_page_path,
        "mirror": _json_load(project.mirror_json, {}),
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "archived_at": archived_at,
        "archived": archived_at is not None,
    }


class ProjectRegistry:
    """Small owner-scoped CRUD service for durable projects."""

    def __init__(self, db: Session, owner: Optional[str]):
        self.db = db
        self.owner = owner

    def list_projects(self, *, include_archived: bool = False) -> List[Dict[str, Any]]:
        query = self.db.query(Project)
        if self.owner is not None:
            query = query.filter(Project.owner == self.owner)
        if not include_archived:
            query = query.filter(Project.archived_at == None)  # noqa: E711
        rows = query.order_by(Project.updated_at.desc(), Project.created_at.desc()).all()
        return [project_to_dict(row) for row in rows]

    def get_project(self, project_id: str, *, include_archived: bool = True) -> Dict[str, Any]:
        project = self._get_row(project_id, include_archived=include_archived)
        return project_to_dict(project)

    def create_project(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        root_path: Optional[str] = None,
        tags: Any = None,
        logseq_page_path: Optional[str] = None,
        mirror: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pid = _clean_optional_text(project_id, max_len=128) or str(uuid.uuid4())
        if self.db.query(Project).filter(Project.project_id == pid).first():
            raise ValueError("Project id already exists")
        project = Project(
            project_id=pid,
            owner=self.owner,
            name=_clean_name(name),
            description=_clean_optional_text(description) or "",
            root_path=_clean_optional_text(root_path),
            tags_json=json.dumps(_clean_tags(tags)),
            logseq_page_path=_clean_optional_text(logseq_page_path),
            mirror_json=json.dumps(_clean_mirror(mirror)),
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project_to_dict(project)

    def update_project(
        self,
        project_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        root_path: Optional[str] = None,
        tags: Any = None,
        logseq_page_path: Optional[str] = None,
        mirror: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        project = self._get_row(project_id)
        if name is not None:
            project.name = _clean_name(name)
        if description is not None:
            project.description = _clean_optional_text(description) or ""
        if root_path is not None:
            project.root_path = _clean_optional_text(root_path)
        if tags is not None:
            project.tags_json = json.dumps(_clean_tags(tags))
        if logseq_page_path is not None:
            project.logseq_page_path = _clean_optional_text(logseq_page_path)
        if mirror is not None:
            project.mirror_json = json.dumps(_clean_mirror(mirror))
        self.db.commit()
        self.db.refresh(project)
        return project_to_dict(project)

    def archive_project(self, project_id: str) -> Dict[str, Any]:
        project = self._get_row(project_id)
        if project.archived_at is None:
            project.archived_at = utcnow_naive()
            self.db.commit()
            self.db.refresh(project)
        return project_to_dict(project)

    def _get_row(self, project_id: str, *, include_archived: bool = True) -> Project:
        project = self.db.query(Project).filter(Project.project_id == project_id).first()
        if not project or not _can_access(project, self.owner):
            raise ProjectNotFoundError(project_id)
        if not include_archived and project.archived_at is not None:
            raise ProjectNotFoundError(project_id)
        return project
