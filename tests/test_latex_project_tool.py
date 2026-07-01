import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services import latex_projects
from src.agent_tools import parse_tool_blocks
from src.tool_implementations import do_manage_latex_projects
from src.tool_index import ToolIndex


@pytest.fixture
def latex_env(tmp_path, monkeypatch):
    root = tmp_path / "data" / "latex_projects"
    monkeypatch.setattr(latex_projects, "LATEX_PROJECT_ROOT", root)
    monkeypatch.setattr(latex_projects, "encrypt", lambda value: f"enc:{value[::-1]}")
    monkeypatch.setattr(latex_projects, "decrypt", lambda value: value[4:][::-1] if value.startswith("enc:") else value)
    return root


def test_manage_latex_projects_credential_status_never_returns_token(latex_env):
    latex_projects.store_credential(
        "amber",
        credential_id="overleaf",
        username="amber@example.com",
        token="super-secret-token",
    )

    result = asyncio.run(do_manage_latex_projects(
        json.dumps({"action": "credential_status"}),
        owner="amber",
    ))

    serialized = json.dumps(result)
    assert result["credentials"][0]["credential_id"] == "overleaf"
    assert result["credentials"][0]["username"] == "amber@example.com"
    assert result["credentials"][0]["configured"] is True
    assert "super-secret-token" not in serialized
    assert "overleaf" in result["results"]


def test_manage_latex_projects_can_list_tree(latex_env):
    latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "paper",
        "title": "Paper",
    })
    worktree = latex_env / "amber" / "paper" / "worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    (worktree / "main.tex").write_text("\\section{Intro}\n", encoding="utf-8")

    result = asyncio.run(do_manage_latex_projects(
        json.dumps({"action": "tree", "latex_project_id": "paper"}),
        owner="amber",
    ))

    assert "main.tex" in result["results"]
    assert result["tree"]["entries"][0]["path"] == "main.tex"


def test_create_defaults_overleaf_project_to_configured_credential(latex_env):
    latex_projects.store_credential(
        "amber",
        credential_id="overleaf",
        username="amber@example.com",
        token="super-secret-token",
    )

    metadata = latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "paper",
        "title": "Paper",
        "overleaf_project_id": "abc123",
    })

    assert metadata["overleaf"]["credential_id"] == "overleaf"


def test_manage_latex_projects_pull_uses_stored_credential(latex_env, monkeypatch):
    latex_projects.store_credential(
        "amber",
        credential_id="overleaf",
        username="amber@example.com",
        token="super-secret-token",
    )
    latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "paper",
        "title": "Paper",
        "overleaf_project_id": "abc123",
    })
    calls = []

    def fake_git_with_credential(cwd, args, *, username, token):
        calls.append({"cwd": cwd, "args": args, "username": username, "token": token})
        (cwd / ".git").mkdir()
        (cwd / "main.tex").write_text("\\section{Intro}\n", encoding="utf-8")
        return "cloned"

    def fake_git(cwd, args, *, check=True):
        if args == ["rev-parse", "HEAD"]:
            return "abcde12345"
        return ""

    monkeypatch.setattr(latex_projects, "_git_with_credential", fake_git_with_credential)
    monkeypatch.setattr(latex_projects, "_git", fake_git)

    result = asyncio.run(do_manage_latex_projects(
        json.dumps({"action": "pull", "latex_project_id": "paper"}),
        owner="amber",
    ))

    assert calls
    assert calls[0]["args"] == ["clone", "https://git.overleaf.com/abc123", "."]
    assert calls[0]["username"] == "git"
    assert calls[0]["token"] == "super-secret-token"
    assert result["head"] == "abcde12345"
    assert "main.tex" in result["results"]


def test_manage_latex_projects_commit_and_push_uses_stored_credential(latex_env, monkeypatch):
    latex_projects.store_credential(
        "amber",
        credential_id="overleaf",
        username="amber@example.com",
        token="super-secret-token",
    )
    latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "paper",
        "title": "Paper",
        "overleaf_project_id": "abc123",
    })
    worktree = Path(latex_projects.read_metadata("amber", "paper")["worktree_path"])
    (worktree / ".git").mkdir()
    (worktree / "bibliography.bib").write_text("@article{test}\n", encoding="utf-8")
    state = {"committed": False}
    credential_calls = []
    git_calls = []

    def fake_git(cwd, args, *, check=True):
        git_calls.append(args)
        if args == ["remote", "get-url", "origin"]:
            return "https://git.overleaf.com/abc123"
        if args == ["status", "--short", "--branch"]:
            if state["committed"]:
                return "## main...origin/main"
            return "## main...origin/main\n M bibliography.bib"
        if args == ["diff", "--cached", "--stat"]:
            return " bibliography.bib | 1 +"
        if args == ["diff", "--cached", "--name-status"]:
            return "M\tbibliography.bib"
        if args == ["commit", "-m", "Add campaign bibliography entry"]:
            state["committed"] = True
            return "[main abcde12] Add campaign bibliography entry"
        if args == ["rev-parse", "HEAD"]:
            return "abcde12345"
        return ""

    def fake_git_with_credential(cwd, args, *, username, token):
        credential_calls.append({"cwd": cwd, "args": args, "username": username, "token": token})
        return "pushed"

    monkeypatch.setattr(latex_projects, "_git", fake_git)
    monkeypatch.setattr(latex_projects, "_git_with_credential", fake_git_with_credential)

    result = asyncio.run(do_manage_latex_projects(
        json.dumps({
            "action": "commit_and_push",
            "latex_project_id": "paper",
            "message": "Add campaign bibliography entry",
        }),
        owner="amber",
    ))

    assert ["add", "-A"] in git_calls
    assert ["commit", "-m", "Add campaign bibliography entry"] in git_calls
    assert credential_calls[0]["args"] == ["push", "origin", "HEAD"]
    assert credential_calls[0]["username"] == "git"
    assert credential_calls[0]["token"] == "super-secret-token"
    assert result["head"] == "abcde12345"
    assert "bibliography.bib" in result["results"]
    assert "super-secret-token" not in json.dumps(result)


def test_manage_latex_projects_push_failure_reports_local_commit_state(latex_env, monkeypatch):
    latex_projects.store_credential(
        "amber",
        credential_id="overleaf",
        username="amber@example.com",
        token="super-secret-token",
    )
    latex_projects.create_or_update_metadata("amber", {
        "latex_project_id": "paper",
        "title": "Paper",
        "overleaf_project_id": "abc123",
    })
    worktree = Path(latex_projects.read_metadata("amber", "paper")["worktree_path"])
    (worktree / ".git").mkdir()
    (worktree / "bibliography.bib").write_text("@article{test}\n", encoding="utf-8")
    state = {"committed": False}

    def fake_git(cwd, args, *, check=True):
        if args == ["remote", "get-url", "origin"]:
            return "https://git.overleaf.com/abc123"
        if args == ["status", "--short", "--branch"]:
            if state["committed"]:
                return "## main...origin/main [ahead 1]"
            return "## main...origin/main\n M bibliography.bib"
        if args == ["diff", "--cached", "--name-status"]:
            return "M\tbibliography.bib"
        if args == ["commit", "-m", "Add campaign bibliography entry"]:
            state["committed"] = True
            return "[main abcde12] Add campaign bibliography entry"
        if args == ["rev-parse", "HEAD"]:
            return "abcde12345"
        return ""

    def fake_git_with_credential(cwd, args, *, username, token):
        raise HTTPException(400, "fatal: unable to access remote: 403")

    monkeypatch.setattr(latex_projects, "_git", fake_git)
    monkeypatch.setattr(latex_projects, "_git_with_credential", fake_git_with_credential)

    result = asyncio.run(do_manage_latex_projects(
        json.dumps({
            "action": "commit_and_push",
            "latex_project_id": "paper",
            "message": "Add campaign bibliography entry",
        }),
        owner="amber",
    ))

    assert result["exit_code"] == 1
    assert result["committed"] is True
    assert result["head"] == "abcde12345"
    assert result["git"]["branch"] == "main...origin/main [ahead 1]"
    assert "write access" in result["error"]
    assert "super-secret-token" not in json.dumps(result)


def test_overleaf_alias_parses_to_latex_project_tool():
    blocks = parse_tool_blocks("""```overleaf_git
{"action":"credential_status"}
```""")

    assert len(blocks) == 1
    assert blocks[0].tool_type == "manage_latex_projects"


def test_keyword_hints_surface_latex_project_tool():
    tools = set()
    query = "check whether my Overleaf Git credential is configured"
    for keywords, hinted in ToolIndex._KEYWORD_HINTS.items():
        if any(keyword in query.lower() for keyword in keywords):
            tools.update(hinted)

    assert "manage_latex_projects" in tools
