from pathlib import Path

from src.builtin_actions import BUILTIN_ACTION_INFO
from src.task_scheduler import HOUSEKEEPING_DEFAULTS
from src.tool_index import ASSISTANT_ALWAYS_AVAILABLE, BUILTIN_TOOL_DESCRIPTIONS, ToolIndex
import src.agent_tools  # noqa: F401 - initializes the circular parsing facade
from src.tool_parsing import _TOOL_NAME_MAP


ROOT = Path(__file__).resolve().parents[1]


def test_logseq_tool_is_discoverable_for_agents_and_scheduled_assistant():
    assert "manage_logseq" in BUILTIN_TOOL_DESCRIPTIONS
    assert "manage_logseq" in ASSISTANT_ALWAYS_AVAILABLE
    assert _TOOL_NAME_MAP["logseq"] == "manage_logseq"
    assert _TOOL_NAME_MAP["knowledge"] == "manage_logseq"
    assert any(
        "knowledge graph" in keywords and "manage_logseq" in tools
        for keywords, tools in ToolIndex._KEYWORD_HINTS.items()
    )


def test_logseq_tool_is_in_knowledge_settings_surfaces():
    admin_js = (ROOT / "static/js/admin.js").read_text(encoding="utf-8")
    assistant_js = (ROOT / "static/js/assistant.js").read_text(encoding="utf-8")

    assert "manage_logseq:     { name: 'Logseq Knowledge'" in admin_js
    assert "cat: 'Knowledge'" in admin_js
    assert "'Knowledge': ['web_search', 'read_file', 'manage_memory', 'manage_logseq'" in assistant_js
    assert "'Documents': ['create_document', 'edit_document', 'update_document', 'suggest_document', 'manage_documents']" in assistant_js
    assert "manage_notes:      { name: 'Notes & Reminders'" in admin_js
    assert "manage_calendar:   { name: 'Calendar'" in admin_js
    assert "cat: 'Calendar & Notes'" in admin_js
    system_group = assistant_js.split("'System': [", 1)[1].split("]", 1)[0]
    assert "manage_documents" not in system_group
    assert "manage_skills" not in system_group


def test_housekeeping_names_and_descriptions_distinguish_storage_layers():
    assert HOUSEKEEPING_DEFAULTS["tidy_documents"]["name"] == "Editor Documents Tidy"
    assert HOUSEKEEPING_DEFAULTS["consolidate_memory"]["name"] == "Agent Memory Tidy"
    assert HOUSEKEEPING_DEFAULTS["tidy_research"]["name"] == "Research Files Tidy"
    assert "Does not touch notes" in BUILTIN_ACTION_INFO["tidy_sessions"]
    assert "Does not touch Logseq" in BUILTIN_ACTION_INFO["tidy_documents"]
    assert "Does not touch Logseq" in BUILTIN_ACTION_INFO["consolidate_memory"]
    assert "Does not touch Logseq" in BUILTIN_ACTION_INFO["tidy_research"]
