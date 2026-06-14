"""Small filesystem-backed integration for a Logseq Markdown graph."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from core.constants import DATA_DIR

_PROPERTY_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)::\s*(.*?)\s*$")
_PAGE_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9][\w/-]*)")
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def configured_graph_root() -> Path:
    configured = os.getenv("ODYSSEUS_LOGSEQ_GRAPH_DIR", "").strip()
    return Path(configured or (Path(DATA_DIR) / "logseq-graph")).expanduser().resolve()


class LogseqGraph:
    """Read and update a file-based Logseq graph without requiring Logseq."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser().resolve() if root else configured_graph_root()

    def ensure_graph(self) -> None:
        for name in ("pages", "journals", "logseq"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        self.ensure_graph()
        pages = self._markdown_files()
        return {
            "root": str(self.root),
            "exists": self.root.is_dir(),
            "writable": os.access(self.root, os.W_OK),
            "page_count": len(pages),
        }

    def list_pages(self, query: str = "", tag: str = "", limit: int = 100) -> list[dict[str, Any]]:
        query_cf = query.strip().casefold()
        tag_cf = tag.strip().lstrip("#").casefold()
        pages = []
        for path in self._markdown_files():
            page = self._page_from_path(path, include_content=bool(query_cf))
            if query_cf:
                haystack = "\n".join(
                    [page["title"], page.get("content", ""), " ".join(page["tags"])]
                ).casefold()
                if query_cf not in haystack:
                    continue
            if tag_cf and tag_cf not in {item.casefold() for item in page["tags"]}:
                continue
            page.pop("content", None)
            pages.append(page)
        pages.sort(key=lambda item: item["updated_at"], reverse=True)
        return pages[: max(1, min(int(limit), 500))]

    def get_page(self, title: str) -> dict[str, Any] | None:
        path = self._find_page(title)
        if not path:
            return None
        page = self._page_from_path(path, include_content=True)
        page["backlinks"] = self.backlinks(page["title"])
        return page

    def upsert_page(
        self,
        title: str,
        content: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_title = self._clean_title(title)
        self.ensure_graph()
        path = self._find_page(clean_title) or self._new_page_path(clean_title)
        body = self._merge_properties(content or "", clean_title, properties or {})
        self._atomic_write(path, body)
        return self.get_page(clean_title) or self._page_from_path(path, include_content=True)

    def append_to_page(self, title: str, content: str) -> dict[str, Any]:
        clean_title = self._clean_title(title)
        existing = self.get_page(clean_title)
        current = existing["content"] if existing else ""
        separator = "" if not current or current.endswith("\n") else "\n"
        return self.upsert_page(clean_title, current + separator + content.rstrip() + "\n")

    def write_artifact(
        self,
        artifact_id: str,
        title: str,
        content: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write an Odysseus artifact at a stable, UUID-addressed graph path."""
        self.ensure_graph()
        clean_id = self._clean_artifact_id(artifact_id)
        path = self.root / "pages" / "artifacts" / f"{clean_id}.md"
        metadata = {"odysseus-id": clean_id, "artifact-type": "document", **(properties or {})}
        body = self._merge_properties(content or "", self._clean_title(title), metadata)
        self._atomic_write(path, body)
        page = self._page_from_path(path, include_content=True)
        page["body"] = self._body(page["content"])
        return page

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        clean_id = self._clean_artifact_id(artifact_id)
        path = self.root / "pages" / "artifacts" / f"{clean_id}.md"
        if not path.is_file():
            return None
        page = self._page_from_path(path, include_content=True)
        page["body"] = self._body(page["content"])
        return page

    def write_artifact_revision(self, artifact_id: str, version: int, content: str) -> str:
        clean_id = self._clean_artifact_id(artifact_id)
        clean_version = max(1, int(version))
        path = self.root / "logseq" / "odysseus-versions" / clean_id / f"{clean_version}.md"
        self._atomic_write(path, content or "")
        return str(path.relative_to(self.root))

    def get_artifact_revision(self, artifact_id: str, version: int) -> str | None:
        clean_id = self._clean_artifact_id(artifact_id)
        clean_version = max(1, int(version))
        path = self.root / "logseq" / "odysseus-versions" / clean_id / f"{clean_version}.md"
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def backlinks(self, title: str, limit: int = 100) -> list[dict[str, str]]:
        target = self._clean_title(title).casefold()
        matches = []
        for path in self._markdown_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            if target not in {link.casefold() for link in _PAGE_LINK_RE.findall(text)}:
                continue
            page = self._page_from_path(path, include_content=False)
            matches.append({"title": page["title"], "path": page["path"]})
        return matches[: max(1, min(int(limit), 500))]

    def _markdown_files(self) -> list[Path]:
        self.ensure_graph()
        files = []
        for folder in ("pages", "journals"):
            files.extend(path for path in (self.root / folder).rglob("*.md") if path.is_file())
        return sorted(files)

    def _find_page(self, title: str) -> Path | None:
        target = self._clean_title(title).casefold()
        for path in self._markdown_files():
            if self._title_for(path).casefold() == target:
                return path
        return None

    def _new_page_path(self, title: str) -> Path:
        filename = _UNSAFE_FILENAME_RE.sub("_", title).strip(" .") or "Untitled"
        filename = re.sub(r"\s+", " ", filename)[:120]
        candidate = self.root / "pages" / f"{filename}.md"
        if candidate.exists():
            suffix = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
            candidate = self.root / "pages" / f"{filename}-{suffix}.md"
        return candidate

    def _page_from_path(self, path: Path, include_content: bool) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
        properties = self._properties(text)
        tags = set(_TAG_RE.findall(text))
        tags_property = properties.get("tags") or ""
        tags.update(_PAGE_LINK_RE.findall(tags_property))
        tags_property = _PAGE_LINK_RE.sub("", tags_property)
        for raw in tags_property.split(","):
            value = raw.strip().strip("#")
            if value:
                tags.add(value)
        result = {
            "title": self._title_for(path, text=text),
            "path": str(path.relative_to(self.root)),
            "properties": properties,
            "tags": sorted(tags, key=str.casefold),
            "links": sorted(set(_PAGE_LINK_RE.findall(text)), key=str.casefold),
            "updated_at": stat.st_mtime,
            "size": stat.st_size,
            "journal": path.is_relative_to(self.root / "journals"),
        }
        if include_content:
            result["content"] = text
        return result

    def _title_for(self, path: Path, text: str | None = None) -> str:
        properties = self._properties(
            text if text is not None else path.read_text(encoding="utf-8", errors="replace")
        )
        return properties.get("title") or path.stem

    @staticmethod
    def _properties(text: str) -> dict[str, str]:
        properties = {}
        for line in text.splitlines():
            match = _PROPERTY_RE.match(line)
            if match:
                properties[match.group(1).lower()] = match.group(2)
                continue
            if line.strip() and not line.lstrip().startswith("-"):
                break
        return properties

    @staticmethod
    def _clean_title(title: str) -> str:
        clean = re.sub(r"\s+", " ", str(title or "")).strip()
        if not clean or clean in {".", ".."}:
            raise ValueError("Page title is required")
        if len(clean) > 240:
            raise ValueError("Page title is too long")
        return clean

    @staticmethod
    def _clean_artifact_id(artifact_id: str) -> str:
        clean = str(artifact_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", clean):
            raise ValueError("Invalid artifact id")
        return clean

    @staticmethod
    def _body(content: str) -> str:
        lines = content.splitlines()
        while lines and (_PROPERTY_RE.match(lines[0]) or not lines[0].strip()):
            lines.pop(0)
        return "\n".join(lines).rstrip() + ("\n" if lines else "")

    @staticmethod
    def _merge_properties(content: str, title: str, properties: dict[str, Any]) -> str:
        lines = content.splitlines()
        existing = LogseqGraph._properties(content)
        merged = {**existing, "title": title}
        for key, value in properties.items():
            clean_key = str(key).strip().lower()
            if re.fullmatch(r"[a-z0-9_-]+", clean_key) and value is not None:
                merged[clean_key] = str(value).strip()
        body = [line for line in lines if not _PROPERTY_RE.match(line)]
        while body and not body[0].strip():
            body.pop(0)
        prefix = [f"{key}:: {value}" for key, value in merged.items() if value]
        return "\n".join(prefix + ([""] if body else []) + body).rstrip() + "\n"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
