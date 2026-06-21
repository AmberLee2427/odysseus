import json
import sqlite3

from janitor_v2 import run_janitor


def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE projects (project_id TEXT, name TEXT, description TEXT, root_path TEXT, tags_json TEXT, logseq_page_path TEXT, mirror_json TEXT, owner TEXT, archived_at TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE notes (id TEXT, owner TEXT, title TEXT, content TEXT, items TEXT, metadata TEXT);
        CREATE TABLE scheduled_tasks (id TEXT, owner TEXT, name TEXT, prompt TEXT, metadata TEXT);
        CREATE TABLE memories (id TEXT, owner TEXT, text TEXT, metadata TEXT);
        CREATE TABLE documents (id TEXT, owner TEXT, title TEXT, language TEXT, current_content TEXT);
    """)
    conn.execute(
        "INSERT INTO projects (project_id, name, tags_json, owner, archived_at) VALUES (?, ?, ?, ?, NULL)",
        ("odysseus-id", "Odysseus", json.dumps(["ai-tooling"]), "amber"),
    )
    conn.execute("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)", ("n1", "amber", "Odysseus", "plan", "", None))
    conn.execute("INSERT INTO memories VALUES (?, ?, ?, ?)", ("m1", "amber", "Odysseus preference", None))
    conn.commit()
    return conn


def test_janitor_reports_then_applies_registry_metadata(tmp_path):
    db_path = tmp_path / "app.db"
    conn = _db(db_path)
    graph_root = tmp_path / "graph"
    artifact = graph_root / "pages" / "artifacts" / "doc-0001.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("title:: Doc\nowner:: amber\nproject:: [[Odysseus]]\n\nbody\n", encoding="utf-8")
    conn.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?)", ("doc-0001", "amber", "Doc", "markdown", "logseq-artifact::doc-0001"))
    conn.commit()
    conn.close()

    report = run_janitor(db_path, graph_root)
    assert set(report.changed) == {"notes:n1 -> odysseus-id", "memories:m1 -> odysseus-id", "documents:doc-0001 -> odysseus-id"}

    run_janitor(db_path, graph_root, apply=True)
    conn = sqlite3.connect(db_path)
    note_meta = json.loads(conn.execute("SELECT metadata FROM notes WHERE id = 'n1'").fetchone()[0])
    assert note_meta == {"project": "Odysseus", "project_id": "odysseus-id", "tags": ["ai-tooling"]}
    conn.close()
    assert "project-id:: odysseus-id" in artifact.read_text(encoding="utf-8")


def test_janitor_refuses_to_run_before_project_migration(tmp_path):
    db_path = tmp_path / "app.db"
    sqlite3.connect(db_path).close()
    try:
        run_janitor(db_path, tmp_path / "graph")
        assert False, "expected missing project table failure"
    except RuntimeError as error:
        assert "projects table is missing" in str(error)


def test_janitor_creates_personal_and_system_projects_for_clear_artifacts(tmp_path):
    db_path = tmp_path / "app.db"
    conn = _db(db_path)
    conn.execute("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)", ("n2", "amber", "Reminder: coffee", "", "", None))
    conn.execute("INSERT INTO scheduled_tasks VALUES (?, ?, ?, ?, ?)", ("t1", "amber", "Editor Documents Tidy", "", None))
    # The built-in-action signal is added after creation so the test table can
    # stay minimal for the metadata columns it exercises.
    conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN action TEXT")
    conn.execute("UPDATE scheduled_tasks SET action = 'tidy_documents' WHERE id = 't1'")
    conn.commit()
    conn.close()

    report = run_janitor(db_path, tmp_path / "graph", apply=True)
    assert any(entry.startswith("Personal ->") for entry in report.created_projects)
    assert any(entry.startswith("System ->") for entry in report.created_projects)


def test_janitor_migrates_clear_legacy_odysseus_document(tmp_path):
    db_path = tmp_path / "app.db"
    conn = _db(db_path)
    conn.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
        ("doc-legacy", "amber", "Provider config", "json", "https://api.malpas.nz/v1"),
    )
    conn.commit()
    conn.close()

    run_janitor(db_path, tmp_path / "graph", apply=True)
    artifact = tmp_path / "graph" / "pages" / "artifacts" / "doc-legacy.md"
    assert "project-id:: odysseus-id" in artifact.read_text(encoding="utf-8")
