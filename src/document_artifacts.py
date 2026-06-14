"""Canonical Logseq-backed storage for editor document artifacts."""

from __future__ import annotations

import re
from typing import Any

from src.logseq_graph import LogseqGraph

ARTIFACT_PREFIX = "logseq-artifact::"
REVISION_PREFIX = "logseq-revision::"


def is_graph_document(doc: Any) -> bool:
    return str(getattr(doc, "current_content", "") or "").startswith(ARTIFACT_PREFIX)


def should_store_in_graph(language: str | None) -> bool:
    # Email-language documents are operational drafts, not durable artifacts.
    return (language or "").lower() != "email"


def read_document_content(doc: Any) -> str:
    stored = str(getattr(doc, "current_content", "") or "")
    if not stored.startswith(ARTIFACT_PREFIX):
        return stored
    page = LogseqGraph().get_artifact(stored[len(ARTIFACT_PREFIX):])
    return page["body"] if page else ""


def document_metadata(doc: Any) -> dict[str, Any]:
    stored = str(getattr(doc, "current_content", "") or "")
    if not stored.startswith(ARTIFACT_PREFIX):
        return {"project": "", "tags": [], "artifact_path": None, "graph_backed": False}
    page = LogseqGraph().get_artifact(stored[len(ARTIFACT_PREFIX):])
    if not page:
        return {"project": "", "tags": [], "artifact_path": None, "graph_backed": True}
    props = page.get("properties") or {}
    project = props.get("project") or props.get("projects") or ""
    project = re.sub(r"^\[\[(.*)\]\]$", r"\1", project.strip())
    return {
        "project": project,
        "tags": page.get("tags") or [],
        "artifact_path": page.get("path"),
        "graph_backed": True,
    }


def write_document_artifact(
    doc: Any,
    content: str,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
) -> str:
    existing = document_metadata(doc)
    project_value = existing["project"] if project is None else project.strip()
    tag_values = existing["tags"] if tags is None else _clean_tags(tags)
    properties = {
        "language": getattr(doc, "language", None) or "text",
        "owner": getattr(doc, "owner", None) or "",
        "project": f"[[{project_value}]]" if project_value else "",
        "tags": ", ".join(f"[[{tag}]]" for tag in tag_values),
    }
    LogseqGraph().write_artifact(doc.id, getattr(doc, "title", None) or "Untitled", content, properties)
    doc.current_content = ARTIFACT_PREFIX + doc.id
    return content


def migrate_document_to_graph(doc: Any) -> bool:
    if is_graph_document(doc) or not should_store_in_graph(getattr(doc, "language", None)):
        return False
    content = str(getattr(doc, "current_content", "") or "")
    write_document_artifact(doc, content)
    return True


def write_revision(doc_id: str, version: int, content: str) -> str:
    LogseqGraph().write_artifact_revision(doc_id, version, content)
    return f"{REVISION_PREFIX}{doc_id}/{int(version)}"


def read_revision(content: str) -> str:
    stored = str(content or "")
    if not stored.startswith(REVISION_PREFIX):
        return stored
    locator = stored[len(REVISION_PREFIX):]
    doc_id, _, version = locator.partition("/")
    return LogseqGraph().get_artifact_revision(doc_id, int(version)) or ""


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for raw in tags:
        tag = str(raw or "").strip().lstrip("#")
        tag = re.sub(r"^\[\[(.*)\]\]$", r"\1", tag).strip()
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            cleaned.append(tag)
    return cleaned
