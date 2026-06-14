import asyncio
import json

from src.logseq_graph import LogseqGraph


def test_logseq_graph_round_trip_search_tags_and_backlinks(tmp_path):
    graph = LogseqGraph(tmp_path / "graph")

    alpha = graph.upsert_page(
        "Project Alpha",
        "- First durable note #research\n- Related to [[Project Beta]]\n",
        {"projects": "[[Odysseus]]", "tags": "[[project]], #active"},
    )
    graph.upsert_page("Project Beta", "- Links back to [[Project Alpha]]\n")

    assert alpha["title"] == "Project Alpha"
    assert alpha["properties"]["projects"] == "[[Odysseus]]"
    assert set(alpha["tags"]) == {"active", "project", "research"}
    assert set(alpha["links"]) == {"Odysseus", "Project Beta", "project"}

    assert [page["title"] for page in graph.list_pages(query="durable")] == ["Project Alpha"]
    assert [page["title"] for page in graph.list_pages(tag="project")] == ["Project Alpha"]
    assert graph.backlinks("Project Alpha") == [
        {"title": "Project Beta", "path": "pages/Project Beta.md"}
    ]


def test_logseq_graph_append_preserves_page_properties(tmp_path):
    graph = LogseqGraph(tmp_path / "graph")
    graph.upsert_page("Lab Notes", "- Existing\n", {"artifact-type": "note"})

    page = graph.append_to_page("Lab Notes", "- Added")

    assert page["content"].startswith("title:: Lab Notes\nartifact-type:: note\n")
    assert page["content"].endswith("- Existing\n- Added\n")


def test_document_artifact_body_metadata_and_revisions_live_in_graph(monkeypatch, tmp_path):
    monkeypatch.setenv("ODYSSEUS_LOGSEQ_GRAPH_DIR", str(tmp_path / "graph"))
    from types import SimpleNamespace
    from src.document_artifacts import (
        ARTIFACT_PREFIX,
        document_metadata,
        read_document_content,
        read_revision,
        write_document_artifact,
        write_revision,
    )

    doc = SimpleNamespace(
        id="artifact-12345678",
        title="Observing Plan",
        language="markdown",
        owner="amber",
        current_content="",
    )
    write_document_artifact(doc, "# Observing Plan\n\nTarget list\n", project="RMDC26", tags=["science", "plan"])
    revision = write_revision(doc.id, 1, "# Observing Plan\n")

    assert doc.current_content == ARTIFACT_PREFIX + doc.id
    assert read_document_content(doc) == "# Observing Plan\n\nTarget list\n"
    assert document_metadata(doc)["project"] == "RMDC26"
    assert set(document_metadata(doc)["tags"]) == {"plan", "science"}
    assert read_revision(revision) == "# Observing Plan\n"


def test_manage_logseq_tool_uses_configured_graph(monkeypatch, tmp_path):
    monkeypatch.setenv("ODYSSEUS_LOGSEQ_GRAPH_DIR", str(tmp_path / "graph"))
    from src.tool_implementations import do_manage_logseq

    write = asyncio.run(do_manage_logseq(json.dumps({
        "action": "write",
        "title": "Agent Page",
        "content": "- Written by the agent #test",
    })))
    search = asyncio.run(do_manage_logseq(json.dumps({"action": "search", "tag": "test"})))

    assert write["exit_code"] == 0
    assert search["exit_code"] == 0
    assert [page["title"] for page in search["pages"]] == ["Agent Page"]


def test_manage_logseq_is_registered_and_admin_gated():
    from src.agent_tools import TOOL_TAGS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.tool_security import NON_ADMIN_BLOCKED_TOOLS, plan_mode_disabled_tools

    schema_names = {item["function"]["name"] for item in FUNCTION_TOOL_SCHEMAS}
    assert "manage_logseq" in TOOL_TAGS
    assert "manage_logseq" in schema_names
    assert "manage_logseq" in NON_ADMIN_BLOCKED_TOOLS
    assert "manage_logseq" in plan_mode_disabled_tools()


def test_logseq_backlinks_route_precedes_generic_page_route(monkeypatch, tmp_path):
    import routes.logseq_routes as routes

    monkeypatch.setenv("ODYSSEUS_LOGSEQ_GRAPH_DIR", str(tmp_path / "graph"))
    monkeypatch.setattr(routes, "_require_graph_admin", lambda request: "amber")
    graph = LogseqGraph(tmp_path / "graph")
    graph.upsert_page("Target", "- Target page")
    graph.upsert_page("Source", "- References [[Target]]")

    router = routes.setup_logseq_routes()
    get_paths = [route.path for route in router.routes if "GET" in route.methods]
    assert get_paths.index("/api/logseq/pages/{title:path}/backlinks") < get_paths.index(
        "/api/logseq/pages/{title:path}"
    )

    endpoint = next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/logseq/pages/{title:path}/backlinks"
    )
    assert endpoint(request=object(), title="Target") == {
        "backlinks": [{"title": "Source", "path": "pages/Source.md"}]
    }
