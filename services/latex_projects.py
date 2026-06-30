"""Local LaTeX project registry and workspace helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from core.database import SessionLocal
from services.project_registry import ProjectNotFoundError, ProjectRegistry
from src.constants import DATA_DIR
from src.secret_storage import decrypt, encrypt


LATEX_PROJECT_ROOT = Path(DATA_DIR) / "latex_projects"
TREE_SKIP_DIRS = {".git", ".latexmk", "__pycache__", ".cache"}
TREE_SKIP_SUFFIXES = {
    ".aux", ".bbl", ".bcf", ".blg", ".fdb_latexmk", ".fls", ".log",
    ".out", ".run.xml", ".synctex.gz", ".toc",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_segment(value: str, fallback: str = "project") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip(".-")
    return cleaned[:120] or fallback


def owner_key(owner: str | None) -> str:
    return _safe_segment(owner or "shared", "shared")


def new_project_id(title: str = "") -> str:
    slug = _safe_segment(title, "latex-project").lower()
    return f"{slug}-{uuid.uuid4().hex[:8]}"


def owner_root(owner: str | None) -> Path:
    return (LATEX_PROJECT_ROOT / owner_key(owner)).resolve(strict=False)


def project_root(owner: str | None, latex_project_id: str) -> Path:
    return (owner_root(owner) / _safe_segment(latex_project_id)).resolve(strict=False)


def metadata_path(owner: str | None, latex_project_id: str) -> Path:
    return project_root(owner, latex_project_id) / "project.json"


def worktree_path(owner: str | None, latex_project_id: str) -> Path:
    return project_root(owner, latex_project_id) / "worktree"


def credentials_path(owner: str | None) -> Path:
    return owner_root(owner) / "credentials.json"


def _assert_under(path: Path, base: Path) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve(strict=False))
    except ValueError as exc:
        raise HTTPException(400, "Path escapes the LaTeX project workspace") from exc
    return resolved


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if value is not None else fallback
    except Exception:
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def clean_metadata(raw: dict[str, Any], *, owner: str | None) -> dict[str, Any]:
    title = str(raw.get("title") or raw.get("latex_project_id") or "LaTeX Project").strip()
    latex_project_id = _safe_segment(raw.get("latex_project_id") or new_project_id(title))
    root = project_root(owner, latex_project_id)
    worktree = worktree_path(owner, latex_project_id)
    overleaf = raw.get("overleaf") if isinstance(raw.get("overleaf"), dict) else {}
    files = raw.get("files") if isinstance(raw.get("files"), dict) else {}
    metadata = {
        "latex_project_id": latex_project_id,
        "owner": owner,
        "odysseus_project_id": str(raw.get("odysseus_project_id") or "").strip(),
        "title": title[:300],
        "root_file": str(raw.get("root_file") or "main.tex").strip()[:300] or "main.tex",
        "workspace_path": str(root),
        "worktree_path": str(worktree),
        "overleaf": {
            "project_id": str(overleaf.get("project_id") or raw.get("overleaf_project_id") or "").strip()[:200],
            "git_remote": str(overleaf.get("git_remote") or raw.get("git_remote") or "").strip()[:2000],
            "credential_id": str(overleaf.get("credential_id") or raw.get("credential_id") or "").strip()[:120],
            "last_pulled_commit": str(overleaf.get("last_pulled_commit") or "").strip()[:200],
            "last_synced_at": str(overleaf.get("last_synced_at") or "").strip()[:80],
        },
        "tags": _clean_tags(raw.get("tags") or ["manuscript", "latex"]),
        "files": files,
        "created_at": str(raw.get("created_at") or _now()),
        "updated_at": _now(),
    }
    if not metadata["overleaf"]["git_remote"] and metadata["overleaf"]["project_id"]:
        metadata["overleaf"]["git_remote"] = f"https://git.overleaf.com/{metadata['overleaf']['project_id']}"
    return metadata


def _clean_tags(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else str(raw or "").replace(",", " ").split()
    tags: list[str] = []
    seen = set()
    for item in values:
        tag = str(item or "").strip().lstrip("#")
        tag = re.sub(r"^\[\[(.*)\]\]$", r"\1", tag).strip()
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            tags.append(tag[:120])
    return tags


def create_or_update_metadata(owner: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    metadata = clean_metadata(payload, owner=owner)
    root = project_root(owner, metadata["latex_project_id"])
    _assert_under(root, owner_root(owner))
    (root / "worktree").mkdir(parents=True, exist_ok=True)
    _write_json(root / "project.json", metadata)
    _link_project_mirror(owner, metadata)
    return metadata


def read_metadata(owner: str | None, latex_project_id: str) -> dict[str, Any]:
    path = metadata_path(owner, latex_project_id)
    if not path.exists():
        raise HTTPException(404, "LaTeX project not found")
    data = _read_json(path, {})
    if not isinstance(data, dict):
        raise HTTPException(500, "LaTeX project metadata is invalid")
    return clean_metadata(data, owner=owner)


def patch_metadata(owner: str | None, latex_project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    current = read_metadata(owner, latex_project_id)
    allowed = {"title", "root_file", "odysseus_project_id", "tags", "overleaf", "files"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise HTTPException(400, f"Unsupported metadata fields: {', '.join(unknown)}")
    merged = dict(current)
    for key in allowed:
        if key not in patch:
            continue
        if key == "overleaf":
            value = patch.get("overleaf") or {}
            if not isinstance(value, dict):
                raise HTTPException(400, "overleaf metadata must be an object")
            merged["overleaf"] = {**(current.get("overleaf") or {}), **value}
        else:
            merged[key] = patch[key]
    merged["latex_project_id"] = current["latex_project_id"]
    merged["created_at"] = current.get("created_at")
    return create_or_update_metadata(owner, merged)


def list_projects(owner: str | None) -> list[dict[str, Any]]:
    base = owner_root(owner)
    if not base.exists():
        return []
    rows = []
    for path in sorted(base.glob("*/project.json")):
        data = _read_json(path, {})
        if isinstance(data, dict):
            rows.append(clean_metadata(data, owner=owner))
    rows.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
    return rows


def project_tree(owner: str | None, latex_project_id: str, *, max_entries: int = 400) -> dict[str, Any]:
    metadata = read_metadata(owner, latex_project_id)
    worktree = _assert_under(Path(metadata["worktree_path"]), project_root(owner, latex_project_id))
    entries = []
    if worktree.exists():
        for path in sorted(worktree.rglob("*")):
            rel = path.relative_to(worktree).as_posix()
            if _skip_path(path, rel):
                continue
            stat = path.stat()
            entries.append({
                "path": rel,
                "type": "dir" if path.is_dir() else "file",
                "size": 0 if path.is_dir() else stat.st_size,
                "role": _file_role(rel, metadata),
            })
            if len(entries) >= max_entries:
                break
    return {"latex_project_id": latex_project_id, "worktree_path": str(worktree), "entries": entries}


def _skip_path(path: Path, rel: str) -> bool:
    parts = set(Path(rel).parts)
    if parts.intersection(TREE_SKIP_DIRS):
        return True
    if path.is_file() and any(rel.endswith(suffix) for suffix in TREE_SKIP_SUFFIXES):
        return True
    return False


def _file_role(rel: str, metadata: dict[str, Any]) -> str:
    if rel == metadata.get("root_file"):
        return "root"
    suffix = Path(rel).suffix.lower()
    if suffix in {".tex", ".bib", ".sty", ".cls"}:
        return suffix.lstrip(".")
    if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".eps"}:
        return "figure"
    return "asset"


def git_status(owner: str | None, latex_project_id: str) -> dict[str, Any]:
    metadata = read_metadata(owner, latex_project_id)
    worktree = Path(metadata["worktree_path"])
    if not (worktree / ".git").exists():
        return {"is_git": False, "clean": True, "branch": "", "head": "", "changes": []}
    status = _git(worktree, ["status", "--short", "--branch"])
    head = _git(worktree, ["rev-parse", "HEAD"], check=False).strip()
    lines = status.splitlines()
    branch = lines[0].replace("##", "").strip() if lines and lines[0].startswith("##") else ""
    changes = [line for line in lines if not line.startswith("##")]
    return {"is_git": True, "clean": not changes, "branch": branch, "head": head, "changes": changes}


def _git(cwd: Path, args: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise HTTPException(400, (proc.stderr or "Git command failed").strip()[:500])
    return proc.stdout.strip()


def store_credential(owner: str | None, credential_id: str, *, username: str = "", token: str) -> dict[str, Any]:
    credential_id = _safe_segment(credential_id, "overleaf")
    if not token:
        raise HTTPException(400, "Token is required")
    path = credentials_path(owner)
    data = _read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    data[credential_id] = {
        "credential_id": credential_id,
        "username": username.strip(),
        "token": encrypt(token),
        "updated_at": _now(),
    }
    _write_json(path, data)
    return {"credential_id": credential_id, "username": username.strip(), "configured": True}


def read_credential(owner: str | None, credential_id: str) -> dict[str, str]:
    data = _read_json(credentials_path(owner), {})
    row = data.get(credential_id) if isinstance(data, dict) else None
    if not isinstance(row, dict):
        raise HTTPException(404, "Credential not found")
    return {
        "credential_id": credential_id,
        "username": str(row.get("username") or ""),
        "token": decrypt(str(row.get("token") or "")),
    }


def credential_status(owner: str | None) -> list[dict[str, Any]]:
    data = _read_json(credentials_path(owner), {})
    if not isinstance(data, dict):
        return []
    return [
        {
            "credential_id": key,
            "username": str(row.get("username") or ""),
            "configured": bool(row.get("token")),
            "updated_at": row.get("updated_at") or "",
        }
        for key, row in sorted(data.items())
        if isinstance(row, dict)
    ]


def delete_credential(owner: str | None, credential_id: str) -> bool:
    path = credentials_path(owner)
    data = _read_json(path, {})
    if not isinstance(data, dict) or credential_id not in data:
        return False
    data.pop(credential_id, None)
    _write_json(path, data)
    return True


def _link_project_mirror(owner: str | None, metadata: dict[str, Any]) -> None:
    project_id = metadata.get("odysseus_project_id")
    if not project_id:
        return
    db = SessionLocal()
    try:
        registry = ProjectRegistry(db, owner)
        project = registry.get_project(project_id, include_archived=False)
        mirror = project.get("mirror") or {}
        latex_projects = mirror.get("latex_projects")
        if not isinstance(latex_projects, dict):
            latex_projects = {}
        latex_projects[metadata["latex_project_id"]] = {
            "title": metadata["title"],
            "root_file": metadata["root_file"],
            "overleaf_project_id": (metadata.get("overleaf") or {}).get("project_id", ""),
            "workspace_path": metadata["workspace_path"],
            "updated_at": metadata["updated_at"],
        }
        mirror["latex_projects"] = latex_projects
        registry.update_project(project_id, mirror=mirror)
    except ProjectNotFoundError:
        raise HTTPException(404, "Odysseus project not found")
    finally:
        db.close()
