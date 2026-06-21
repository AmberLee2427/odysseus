import asyncio
import tempfile
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Project
import routes.project_routes as project_routes


def _session(monkeypatch):
    tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    engine = create_engine(
        f"sqlite:///{tmpdb.name}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(project_routes, "SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _req(user="amber"):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


def _endpoint(method, path):
    router = project_routes.setup_project_routes()
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise RuntimeError(f"{method} {path} not found")


def test_project_registry_create_update_archive(monkeypatch):
    asyncio.run(_test_project_registry_create_update_archive(monkeypatch))


async def _test_project_registry_create_update_archive(monkeypatch):
    SessionLocal = _session(monkeypatch)
    create_project = _endpoint("POST", "/api/projects")
    update_project = _endpoint("PATCH", "/api/projects/{project_id}")
    list_projects = _endpoint("GET", "/api/projects")
    archive_project = _endpoint("POST", "/api/projects/{project_id}/archive")

    body = project_routes.ProjectCreate(
        project_id="stable-pid",
        name="First name",
        description="starter",
        root_path="/home/amber/work/one",
        tags=["ai-tooling", "local-first"],
        logseq_page_path="pages/projects/odysseus.md",
        mirror={"status": "active", "kanban": {"backlog": []}},
    )
    created = await create_project(_req(), body)
    assert created["project_id"] == "stable-pid"
    assert created["id"] == "stable-pid"
    assert created["archived"] is False
    assert created["tags"] == ["ai-tooling", "local-first"]
    assert created["logseq_page_path"] == "pages/projects/odysseus.md"
    assert created["mirror"]["status"] == "active"

    renamed = await update_project(
        _req(),
        "stable-pid",
        project_routes.ProjectUpdate(
            name="Renamed",
            tags=["research"],
            mirror={"status": "paused"},
        ),
    )
    assert renamed["project_id"] == "stable-pid"
    assert renamed["name"] == "Renamed"
    assert renamed["tags"] == ["research"]
    assert renamed["mirror"] == {"status": "paused"}

    listed = (await list_projects(_req()))["projects"]
    assert [p["project_id"] for p in listed] == ["stable-pid"]

    archived = await archive_project(_req(), "stable-pid")
    assert archived["archived"] is True
    assert archived["archived_at"]
    assert (await list_projects(_req()))["projects"] == []
    assert (await list_projects(_req(), include_archived=True))["projects"][0]["project_id"] == "stable-pid"

    db = SessionLocal()
    try:
        row = db.query(Project).filter(Project.project_id == "stable-pid").one()
        assert row.owner == "amber"
        assert row.name == "Renamed"
        assert row.archived_at is not None
    finally:
        db.close()


def test_project_registry_rejects_structural_fields_in_mirror(monkeypatch):
    asyncio.run(_test_project_registry_rejects_structural_fields_in_mirror(monkeypatch))


async def _test_project_registry_rejects_structural_fields_in_mirror(monkeypatch):
    _session(monkeypatch)
    create_project = _endpoint("POST", "/api/projects")

    try:
        await create_project(
            _req(),
            project_routes.ProjectCreate(
                project_id="stable-pid",
                name="First name",
                mirror={"project_id": "silently-forked"},
            ),
        )
        assert False, "expected structural field rejection"
    except project_routes.HTTPException as error:
        assert error.status_code == 400
        assert "structural fields" in str(error.detail)


def test_project_registry_is_owner_scoped(monkeypatch):
    asyncio.run(_test_project_registry_is_owner_scoped(monkeypatch))


async def _test_project_registry_is_owner_scoped(monkeypatch):
    SessionLocal = _session(monkeypatch)
    list_projects = _endpoint("GET", "/api/projects")
    get_project = _endpoint("GET", "/api/projects/{project_id}")
    update_project = _endpoint("PATCH", "/api/projects/{project_id}")
    db = SessionLocal()
    try:
        db.add(Project(project_id="a", owner="alice", name="Alice"))
        db.add(Project(project_id="b", owner="bob", name="Bob"))
        db.commit()
    finally:
        db.close()

    assert (await list_projects(_req("alice")))["projects"][0]["project_id"] == "a"
    assert (await get_project(_req("alice"), "a"))["project_id"] == "a"

    try:
        await get_project(_req("alice"), "b")
        assert False, "expected missing project"
    except project_routes.HTTPException as error:
        assert error.status_code == 404

    try:
        await update_project(_req("alice"), "b", project_routes.ProjectUpdate(name="Nope"))
        assert False, "expected missing project"
    except project_routes.HTTPException as error:
        assert error.status_code == 404
