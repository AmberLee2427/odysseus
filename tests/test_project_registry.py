import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Project
import routes.project_routes as project_routes


def _client(monkeypatch, user="amber"):
    tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    engine = create_engine(
        f"sqlite:///{tmpdb.name}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(project_routes, "SessionLocal", TestSessionLocal)

    app = FastAPI()

    @app.middleware("http")
    async def attach_user(request, call_next):
        if user is not None:
            request.state.current_user = user
        return await call_next(request)

    app.include_router(project_routes.setup_project_routes())
    return TestClient(app), TestSessionLocal


def test_project_registry_create_update_archive(monkeypatch):
    client, SessionLocal = _client(monkeypatch)

    created = client.post(
        "/api/projects",
        json={
            "project_id": "stable-pid",
            "name": "First name",
            "description": "starter",
            "root_path": "/home/amber/work/one",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["project_id"] == "stable-pid"
    assert body["id"] == "stable-pid"
    assert body["archived"] is False

    renamed = client.patch("/api/projects/stable-pid", json={"name": "Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["project_id"] == "stable-pid"
    assert renamed.json()["name"] == "Renamed"

    listed = client.get("/api/projects").json()["projects"]
    assert [p["project_id"] for p in listed] == ["stable-pid"]

    archived = client.post("/api/projects/stable-pid/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert archived.json()["archived_at"]
    assert client.get("/api/projects").json()["projects"] == []
    assert client.get("/api/projects?include_archived=true").json()["projects"][0]["project_id"] == "stable-pid"

    db = SessionLocal()
    try:
        row = db.query(Project).filter(Project.project_id == "stable-pid").one()
        assert row.owner == "amber"
        assert row.name == "Renamed"
        assert row.archived_at is not None
    finally:
        db.close()


def test_project_registry_is_owner_scoped(monkeypatch):
    client, SessionLocal = _client(monkeypatch, user="alice")
    db = SessionLocal()
    try:
        db.add(Project(project_id="a", owner="alice", name="Alice"))
        db.add(Project(project_id="b", owner="bob", name="Bob"))
        db.commit()
    finally:
        db.close()

    assert client.get("/api/projects").json()["projects"][0]["project_id"] == "a"
    assert client.get("/api/projects/a").status_code == 200
    assert client.get("/api/projects/b").status_code == 404
    assert client.patch("/api/projects/b", json={"name": "Nope"}).status_code == 404
