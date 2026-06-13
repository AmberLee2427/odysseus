from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from cosci.agy_client import AgyClient
from cosci.env import load_project_env
from cosci.literature import LiteratureClient, literature_brief
from cosci.models import RuntimeProfile, RunState
from cosci.orchestrator import CoScientist
from cosci.store import Store


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / ".cosci" / "cosci.sqlite3"
DEFAULT_AGY = "/Users/malpas.1/.local/bin/agy"

mcp = FastMCP(
    "cosci",
    instructions=(
        "Personal microlensing co-scientist. Use run_microlensing_coscientist "
        "for hypothesis generation/ranking, search_microlensing_literature for "
        "ADS/arXiv grounding, and ask_coscientist for a single Antigravity call."
    ),
)


@mcp.tool()
async def run_microlensing_coscientist(
    goal: str,
    depth: Literal["quick", "normal", "deep"] = "quick",
    literature_provider: Literal["auto", "ads", "arxiv", "none"] = "auto",
    model: str = "gemini-3.5-flash",
) -> dict:
    """Run the co-scientist loop with opinionated microlensing defaults."""
    return await run_coscientist_tool(
        goal=goal,
        depth=depth,
        literature_provider=literature_provider,
        model=model,
    )


@mcp.tool()
def search_microlensing_literature(
    query: str,
    provider: Literal["auto", "ads", "arxiv", "none"] = "auto",
    limit: int = 5,
) -> dict:
    """Search ADS/arXiv and return a compact literature brief."""
    return search_literature_tool(query=query, provider=provider, limit=limit)


@mcp.tool()
async def ask_coscientist(
    prompt: str,
    model: str = "gemini-3.5-flash",
) -> str:
    """Send one prompt through the logged-in Antigravity CLI."""
    return await ask_tool(prompt=prompt, model=model)


@mcp.tool()
def coscientist_status() -> dict:
    """Return local configuration status for the co-scientist MCP server."""
    load_project_env(ROOT / ".env")
    return {
        "workspace": str(ROOT),
        "db": str(DEFAULT_DB),
        "agy_path": DEFAULT_AGY,
        "env_loaded": (ROOT / ".env").exists(),
        "ads_token_available": bool(__import__("os").environ.get("ADS_API_TOKEN")),
    }


async def run_coscientist_tool(
    goal: str,
    depth: Literal["quick", "normal", "deep"] = "quick",
    literature_provider: Literal["auto", "ads", "arxiv", "none"] = "auto",
    model: str = "gemini-3.5-flash",
) -> dict:
    load_project_env(ROOT / ".env")
    preset = _depth_preset(depth)
    profile = RuntimeProfile(
        backend="agy",
        model=model,
        agy_path=DEFAULT_AGY,
        print_timeout=preset["print_timeout"],
        literature=literature_provider != "none",
        literature_provider=literature_provider,
        literature_results=preset["literature_results"],
    )
    store = Store(DEFAULT_DB)
    client = AgyClient(profile=profile, workspace=ROOT)
    literature_client = LiteratureClient(provider=literature_provider)
    run_state = RunState(goal=goal, profile=profile)
    try:
        hypotheses, review = await CoScientist(
            client,
            store,
            literature_client=literature_client,
        ).run(
            run_state,
            rounds=preset["rounds"],
            initial_hypotheses=preset["initial"],
            evolved_hypotheses=preset["evolved"],
            tournament_matches=preset["tournament_matches"],
        )
    finally:
        store.close()

    return {
        "run_id": run_state.id,
        "depth": depth,
        "top_hypotheses": [
            {
                "id": h.id,
                "score": round(h.score, 2),
                "title": h.title,
                "claim": h.claim,
                "tests": h.tests[:5],
                "risks": h.risks[:5],
                "citations": h.citations[:5],
            }
            for h in hypotheses[:8]
        ],
        "meta_review": review,
    }


def search_literature_tool(
    query: str,
    provider: Literal["auto", "ads", "arxiv", "none"] = "auto",
    limit: int = 5,
) -> dict:
    load_project_env(ROOT / ".env")
    safe_limit = max(1, min(limit, 20))
    records = LiteratureClient(provider=provider).search(query, limit=safe_limit)
    return {
        "query": query,
        "provider": provider,
        "brief": literature_brief(records),
        "records": [record.model_dump(mode="json") for record in records],
    }


async def ask_tool(prompt: str, model: str = "gemini-3.5-flash") -> str:
    load_project_env(ROOT / ".env")
    profile = RuntimeProfile(
        backend="agy",
        model=model,
        agy_path=DEFAULT_AGY,
        print_timeout="2m",
        literature=False,
    )
    return await AgyClient(profile=profile, workspace=ROOT).ask(prompt)


def _depth_preset(depth: str) -> dict:
    if depth == "quick":
        return {
            "initial": 3,
            "rounds": 1,
            "evolved": 1,
            "tournament_matches": 2,
            "literature_results": 3,
            "print_timeout": "2m",
        }
    if depth == "normal":
        return {
            "initial": 5,
            "rounds": 2,
            "evolved": 2,
            "tournament_matches": 6,
            "literature_results": 5,
            "print_timeout": "3m",
        }
    if depth == "deep":
        return {
            "initial": 8,
            "rounds": 3,
            "evolved": 3,
            "tournament_matches": -1,
            "literature_results": 8,
            "print_timeout": "5m",
        }
    raise ValueError("depth must be quick, normal, or deep")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
