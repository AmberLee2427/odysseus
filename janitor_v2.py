#!/usr/bin/env python3
"""Backfill project metadata after the project-registry migration.

The Janitor deliberately does not guess a project ID.  It only assigns a
project when an artifact text/property unambiguously matches a live project
registry name; otherwise it reports the artifact for review.  This makes it
safe to run repeatedly while projects and their Logseq mirror are evolving.

Run a report first::

    python janitor_v2.py

Apply the proposed changes only after reviewing it::

    python janitor_v2.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "app.db"
DEFAULT_GRAPH = ROOT / "data" / "logseq-graph"
SQL_ARTIFACTS = {
    "notes": ("id", ("title", "content", "items")),
    "scheduled_tasks": ("id", ("name", "prompt")),
    "memories": ("id", ("text",)),
}
ARTIFACT_PREFIX = "logseq-artifact::"
_PROPERTY_LINE = re.compile(r"^\s*([A-Za-z0-9_-]+)::\s*(.*?)\s*$")


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str
    tags: tuple[str, ...]
    owner: str | None


@dataclass
class JanitorReport:
    changed: list[str] = field(default_factory=list)
    created_projects: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _load_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _clean_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        values = re.findall(r"\[\[([^\]]+)\]\]|[^,\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        tag = str(item).strip().lstrip("#")
        if tag.startswith("[[") and tag.endswith("]]"):
            tag = tag[2:-2].strip()
        if tag and tag.casefold() not in seen:
            result.append(tag)
            seen.add(tag.casefold())
    return result


def _projects(conn: sqlite3.Connection) -> list[Project]:
    if not _table_exists(conn, "projects"):
        raise RuntimeError(
            "The projects table is missing. Restart/rebuild Odysseus first so "
            "the project-registry migration can run; the Janitor will not invent "
            "a parallel schema."
        )
    rows = conn.execute(
        "SELECT project_id, name, tags_json, owner FROM projects WHERE archived_at IS NULL"
    ).fetchall()
    projects = []
    for row in rows:
        try:
            stored_tags = json.loads(row["tags_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            stored_tags = []
        projects.append(
            Project(row["project_id"], row["name"], tuple(_clean_tags(stored_tags)), row["owner"])
        )
    return projects


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone())


def _matching_project(text: str, owner: str | None, projects: Iterable[Project]) -> Project | None:
    matches = []
    for project in projects:
        if owner and project.owner and owner != project.owner:
            continue
        name = project.name.strip()
        if name and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE):
            matches.append(project)
    return matches[0] if len(matches) == 1 else None


def _project_named(name: str, owner: str | None, projects: Iterable[Project]) -> Project | None:
    matches = [p for p in projects if p.name.casefold() == name.casefold() and (not owner or not p.owner or p.owner == owner)]
    return matches[0] if len(matches) == 1 else None


def _ensure_project(
    conn: sqlite3.Connection, projects: list[Project], report: JanitorReport, *,
    name: str, owner: str | None, description: str, tags: list[str], apply: bool,
) -> Project:
    existing = _project_named(name, owner, projects)
    if existing:
        return existing
    # Stable across dry-run/apply and unique across owners without exposing an
    # implementation-only SQLite row id as public project identity.
    project_id = "auto-" + uuid.uuid5(uuid.NAMESPACE_URL, f"odysseus:{owner or ''}:{name.casefold()}").hex[:16]
    project = Project(project_id, name, tuple(tags), owner)
    projects.append(project)
    report.created_projects.append(f"{name} -> {project_id}")
    if apply:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        conn.execute(
            """INSERT INTO projects
               (project_id, owner, name, description, root_path, tags_json,
                logseq_page_path, mirror_json, archived_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, NULL, ?, NULL, '{}', NULL, ?, ?)""",
            (project_id, owner, name, description, json.dumps(tags), now, now),
        )
    return project


def _automatic_project(
    conn: sqlite3.Connection, projects: list[Project], report: JanitorReport, *,
    table: str, row: sqlite3.Row, text: str, apply: bool,
) -> Project | None:
    owner = row["owner"]
    lower = text.casefold()
    # The Janitor itself and Odysseus implementation/configuration work belong
    # to the product project, including before that project has been manually
    # entered in the new registry.
    if any(token in lower for token in ("odysseus", "project_metadata_janitor", "tts", "stt", "api.malpas.nz", "gpt-5.3-codex")):
        return _ensure_project(conn, projects, report, name="Odysseus", owner=owner,
                               description="The core AI agent framework and ecosystem.",
                               tags=["ai-tooling", "local-first"], apply=apply)
    if table == "notes" and str(row["title"] or "").casefold().startswith("reminder:"):
        return _ensure_project(conn, projects, report, name="Personal", owner=owner,
                               description="Personal reminders and life administration.",
                               tags=["personal", "reminders"], apply=apply)
    if table == "scheduled_tasks" and row["action"]:
        return _ensure_project(conn, projects, report, name="System", owner=owner,
                               description="Odysseus built-in maintenance and automation tasks.",
                               tags=["system", "automation"], apply=apply)
    return None


def _apply_project_metadata(metadata: dict[str, Any], project: Project) -> dict[str, Any]:
    out = dict(metadata)
    out["project_id"] = project.project_id
    out["project"] = project.name
    out["tags"] = _clean_tags(out.get("tags")) or list(project.tags)
    return out


def _janitor_sql(conn: sqlite3.Connection, projects: list[Project], report: JanitorReport, apply: bool) -> None:
    for table, (id_col, text_cols) in SQL_ARTIFACTS.items():
        if not _table_exists(conn, table):
            report.skipped.append(f"{table}: table is absent")
            continue
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "metadata" not in cols:
            report.skipped.append(f"{table}: no metadata column")
            continue
        extra_cols = ["title"] if table == "notes" else []
        if table == "scheduled_tasks" and "action" in cols:
            extra_cols.append("action")
        select_cols = list(dict.fromkeys([id_col, "owner", "metadata", *extra_cols, *[c for c in text_cols if c in cols]]))
        for row in conn.execute(f"SELECT {', '.join(select_cols)} FROM {table}"):
            metadata = _load_json(row["metadata"])
            if metadata.get("project_id"):
                continue
            haystack = "\n".join(str(row[c] or "") for c in text_cols if c in cols)
            project = _matching_project(haystack, row["owner"], projects)
            if not project:
                project = _automatic_project(conn, projects, report, table=table, row=row, text=haystack, apply=apply)
            label = f"{table}:{row[id_col]}"
            if not project:
                report.unresolved.append(label)
                continue
            updated = _apply_project_metadata(metadata, project)
            if apply:
                conn.execute(
                    f"UPDATE {table} SET metadata = ? WHERE {id_col} = ?",
                    (json.dumps(updated, sort_keys=True), row[id_col]),
                )
            report.changed.append(f"{label} -> {project.project_id}")


def _janitor_graph(conn: sqlite3.Connection, projects: list[Project], graph_root: Path, report: JanitorReport, apply: bool) -> None:
    """Backfill ``project-id`` on graph-backed editor documents.

    Graph properties remain the canonical document metadata.  SQLite only
    identifies which document rows point at graph artifacts.
    """
    if not _table_exists(conn, "documents"):
        report.skipped.append("documents: table is absent")
        return
    for row in conn.execute("SELECT id, owner, title, language, current_content FROM documents"):
        stored = str(row["current_content"] or "")
        if not stored.startswith(ARTIFACT_PREFIX):
            label = f"documents:{row['id']}"
            project = _automatic_project(
                conn, projects, report, table="documents", row=row,
                text=f"{row['title'] or ''}\n{stored}", apply=apply,
            )
            if not project or str(row["language"] or "").casefold() == "email":
                report.skipped.append(f"{label}: not graph-backed")
                continue
            if apply:
                _write_new_graph_artifact(
                    graph_root, row["id"], row["title"], stored,
                    owner=row["owner"], language=row["language"], project=project,
                )
                conn.execute(
                    "UPDATE documents SET current_content = ? WHERE id = ?",
                    (ARTIFACT_PREFIX + row["id"], row["id"]),
                )
            report.changed.append(f"{label} -> {project.project_id}")
            continue
        artifact_id = stored[len(ARTIFACT_PREFIX):]
        label = f"documents:{row['id']}"
        artifact_path = graph_root / "pages" / "artifacts" / f"{artifact_id}.md"
        if not artifact_path.is_file():
            report.unresolved.append(f"{label}: missing graph artifact")
            continue
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
        props = _graph_properties(text)
        if props.get("project-id"):
            continue
        project_name = re.sub(r"^\[\[(.*)\]\]$", r"\1", str(props.get("project") or "").strip())
        project = _matching_project(project_name, row["owner"], projects)
        if not project and project_name:
            project = _ensure_project(conn, projects, report, name=project_name, owner=row["owner"],
                                      description="Project discovered from existing Logseq artifact metadata.",
                                      tags=[], apply=apply)
        if not project:
            report.unresolved.append(label)
            continue
        if apply:
            _set_graph_property(artifact_path, text, "project-id", project.project_id)
        report.changed.append(f"{label} -> {project.project_id}")


def _graph_properties(text: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in text.splitlines():
        match = _PROPERTY_LINE.match(line)
        if match:
            properties[match.group(1).lower()] = match.group(2)
            continue
        if line.strip():
            break
    return properties


def _set_graph_property(path: Path, text: str, key: str, value: str) -> None:
    """Add a Logseq property without importing/booting the web application."""
    lines = text.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if _PROPERTY_LINE.match(line):
            insert_at = index + 1
            continue
        if not line.strip():
            insert_at = index
        break
    lines.insert(insert_at, f"{key}:: {value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_new_graph_artifact(
    graph_root: Path, artifact_id: str, title: str, body: str, *,
    owner: str | None, language: str | None, project: Project,
) -> None:
    path = graph_root / "pages" / "artifacts" / f"{artifact_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    properties = [
        f"title:: {title or 'Untitled'}",
        f"odysseus-id:: {artifact_id}",
        "artifact-type:: document",
        f"language:: {language or 'text'}",
        f"owner:: {owner or ''}",
        f"project:: [[{project.name}]]",
        f"project-id:: {project.project_id}",
        "tags:: " + ", ".join(f"[[{tag}]]" for tag in project.tags),
    ]
    path.write_text("\n".join(properties) + "\n\n" + body.rstrip() + "\n", encoding="utf-8")


def run_janitor(db_path: Path = DEFAULT_DB, graph_root: Path = DEFAULT_GRAPH, *, apply: bool = False) -> JanitorReport:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        projects = _projects(conn)
        report = JanitorReport()
        _janitor_sql(conn, projects, report, apply)
        _janitor_graph(conn, projects, graph_root, report, apply)
        if apply:
            conn.commit()
        return report
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--graph-root", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--apply", action="store_true", help="write inferred metadata")
    args = parser.parse_args()
    try:
        report = run_janitor(args.db, args.graph_root, apply=args.apply)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"Janitor blocked: {exc}")
        return 2
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"Janitor {mode}: {len(report.changed)} change(s), {len(report.created_projects)} project(s) created, {len(report.unresolved)} unresolved")
    for entry in report.created_projects:
        print(f"  would create project: {entry}" if not args.apply else f"  created project: {entry}")
    for entry in report.changed:
        print(f"  would update: {entry}" if not args.apply else f"  updated: {entry}")
    for entry in report.unresolved:
        print(f"  needs project: {entry}")
    for entry in report.skipped:
        print(f"  skipped: {entry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
