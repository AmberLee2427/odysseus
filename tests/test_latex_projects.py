import json
from pathlib import Path

import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Project
from services import latex_projects
from routes import latex_project_routes


@pytest.fixture()
def latex_env(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'app.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(latex_projects, "SessionLocal", SessionLocal)
    monkeypatch.setattr(latex_projects, "LATEX_PROJECT_ROOT", tmp_path / "latex_projects")
    monkeypatch.setattr(latex_projects, "encrypt", lambda value: f"enc:{value[::-1]}")
    monkeypatch.setattr(latex_projects, "decrypt", lambda value: value[4:][::-1] if value.startswith("enc:") else value)
    return SessionLocal


def test_create_metadata_links_odysseus_project_mirror(latex_env):
    db = latex_env()
    try:
        db.add(Project(project_id="astro-paper", owner="amber", name="Astro Paper", mirror_json="{}"))
        db.commit()
    finally:
        db.close()

    created = latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "boss-draft",
        "odysseus_project_id": "astro-paper",
        "title": "Boss Draft",
        "root_file": "paper/main.tex",
        "overleaf_project_id": "68768ebaca76a90da8368215",
    })

    assert created["workspace_path"].endswith("/amber/boss-draft")
    assert created["worktree_path"].endswith("/amber/boss-draft/worktree")
    assert created["overleaf"]["git_remote"] == "https://git.overleaf.com/68768ebaca76a90da8368215"
    assert Path(created["workspace_path"], "project.json").exists()

    db = latex_env()
    try:
        project = db.query(Project).filter(Project.project_id == "astro-paper").one()
        mirror = json.loads(project.mirror_json)
    finally:
        db.close()
    assert mirror["latex_projects"]["boss-draft"]["title"] == "Boss Draft"
    assert mirror["latex_projects"]["boss-draft"]["overleaf_project_id"] == "68768ebaca76a90da8368215"


def test_patch_metadata_rejects_unknown_fields(latex_env):
    latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "draft",
        "title": "Draft",
    })

    with pytest.raises(Exception) as exc:
        latex_projects.patch_metadata("amber", "draft", {"workspace_path": "/tmp/nope"})

    assert "Unsupported metadata fields" in str(exc.value)


def test_project_tree_filters_git_and_latex_build_files(latex_env):
    latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "draft",
        "title": "Draft",
        "root_file": "main.tex",
    })
    worktree = Path(latex_projects.read_metadata("amber", "draft")["worktree_path"])
    (worktree / ".git").mkdir()
    (worktree / "figures").mkdir()
    (worktree / "main.tex").write_text("hello", encoding="utf-8")
    (worktree / "main.aux").write_text("build", encoding="utf-8")
    (worktree / "figures" / "plot.pdf").write_text("pdf", encoding="utf-8")

    tree = latex_projects.project_tree("amber", "draft")

    assert [row["path"] for row in tree["entries"]] == ["figures", "figures/plot.pdf", "main.tex"]
    assert {row["path"]: row["role"] for row in tree["entries"]}["main.tex"] == "root"
    assert {row["path"]: row["role"] for row in tree["entries"]}["figures/plot.pdf"] == "figure"


def test_credentials_are_encrypted_and_owner_scoped(latex_env):
    stored = latex_projects.store_credential(
        "amber",
        "overleaf",
        username="amber@example.test",
        token="secret-token",
    )

    assert stored == {"credential_id": "overleaf", "username": "amber@example.test", "configured": True}
    raw = json.loads((latex_projects.owner_root("amber") / "credentials.json").read_text(encoding="utf-8"))
    assert raw["overleaf"]["token"] == "enc:nekot-terces"
    assert "secret-token" not in json.dumps(raw)
    assert latex_projects.read_credential("amber", "overleaf")["token"] == "secret-token"
    assert latex_projects.credential_status("bob") == []


def test_latex_routes_require_document_scope_for_api_tokens():
    request = SimpleNamespace(
        state=SimpleNamespace(api_token=True, api_token_scopes=["browser:read"])
    )

    with pytest.raises(Exception) as exc:
        latex_project_routes._require_scope(request, "documents:read")

    assert getattr(exc.value, "status_code", None) == 403

    request.state.api_token_scopes = ["documents:read"]
    latex_project_routes._require_scope(request, "documents:read")
