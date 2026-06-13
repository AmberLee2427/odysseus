from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from cosci.agy_client import AgyClient
from cosci.antigravity_client import AntigravityClient
from cosci.env import load_project_env
from cosci.literature import LiteratureClient, literature_brief
from cosci.models import RuntimeProfile, RunState
from cosci.orchestrator import CoScientist
from cosci.prompts import (
    evolution_prompt,
    generation_prompt,
    pairwise_debate_prompt,
    reflection_prompt,
)
from cosci.store import Store

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Personal co-scientist orchestration for microlensing research. "
        "Defaults to the logged-in Antigravity CLI (`agy`), grounds runs with "
        "ADS/arXiv literature, and ranks hypotheses with pairwise Elo debates."
    ),
)
console = Console()


@app.command()
def version() -> None:
    """Print the package version."""
    from cosci import __version__

    console.print(__version__)


@app.command("auth")
def auth_status(
    backend: str = typer.Option(
        "agy",
        help="Auth path to check. Use `agy` for subscription login or `sdk` for API/Vertex.",
    ),
    agy_path: str = typer.Option("agy", help="Path or command name for the Antigravity CLI."),
    api_key_env: str = typer.Option(
        "GEMINI_API_KEY",
        help="SDK mode only: environment variable containing a Gemini API key.",
    ),
    vertex: bool = typer.Option(False, help="SDK mode only: validate Vertex-style config."),
    project: str | None = typer.Option(None, help="SDK Vertex project ID."),
    location: str | None = typer.Option(None, help="SDK Vertex location, for example us-central1."),
) -> None:
    """Check whether the selected backend has usable auth/configuration."""
    load_project_env()
    if backend == "agy":
        import shutil
        import subprocess

        agy = shutil.which(agy_path) or agy_path
        try:
            result = subprocess.run(
                [agy, "--version"],
                check=True,
                text=True,
                capture_output=True,
                timeout=10,
            )
        except Exception as exc:
            console.print(f"[red]Missing[/red] agy CLI: {exc}")
            raise typer.Exit(1) from exc
        console.print(f"[green]OK[/green] agy CLI: {agy} ({result.stdout.strip()})")
        console.print("Subscription/login auth is handled by the Antigravity CLI.")
        return

    if os.environ.get(api_key_env):
        console.print(f"[green]OK[/green] {api_key_env} is set.")
    else:
        console.print(f"[yellow]Missing[/yellow] {api_key_env}.")

    if vertex:
        if project and location:
            console.print(f"[green]OK[/green] Vertex config: {project}/{location}.")
        else:
            console.print("[yellow]Vertex needs both --project and --location.[/yellow]")

    console.print(
        "The Antigravity SDK currently supports API-key auth or Vertex config here; "
        "it does not expose Google AI subscription/OAuth quota to Python."
    )


@app.command()
def run(
    goal: str = typer.Argument(..., help="Scientific research goal to investigate."),
    rounds: int = typer.Option(
        1,
        help="Number of reflect -> pairwise Elo tournament -> evolve cycles.",
    ),
    initial: int = typer.Option(5, help="Initial hypotheses generated before the first round."),
    evolved: int = typer.Option(3, help="New evolved hypotheses produced per round."),
    tournament_matches: int = typer.Option(
        6,
        help="Pairwise Elo debates per round. Use -1 for all pairs or 0 to skip ranking.",
    ),
    elo_k: float = typer.Option(
        32.0,
        help="Elo K-factor. Larger values make pairwise debate results move scores faster.",
    ),
    literature: bool = typer.Option(
        True,
        help="Retrieve a compact ADS/arXiv literature brief before generation.",
    ),
    literature_results: int = typer.Option(5, help="Maximum literature records to inject."),
    literature_provider: str = typer.Option(
        "auto",
        help="Literature provider: `auto` uses ADS if a token exists, then arXiv; or choose ads, arxiv, none.",
    ),
    ads_token_env: str = typer.Option(
        "ADS_API_TOKEN",
        help="Environment variable read from `.env`/environment for the ADS token.",
    ),
    backend: str = typer.Option("agy", help="Model backend: `agy` subscription CLI or `sdk` API/Vertex."),
    model: str = typer.Option("gemini-3.5-flash", help="Model name passed to the backend."),
    thinking: str = typer.Option(
        "medium",
        help="SDK mode only: Gemini thinking level such as low, medium, or high.",
    ),
    agy_path: str = typer.Option("agy", help="Path or command name for the Antigravity CLI."),
    print_timeout: str = typer.Option("5m", help="agy mode only: timeout for each `agy --print` call."),
    api_key_env: str = typer.Option(
        "GEMINI_API_KEY",
        help="SDK mode only: environment variable containing a Gemini API key.",
    ),
    vertex: bool = typer.Option(False, help="SDK mode only: use Vertex AI backend."),
    project: str | None = typer.Option(None, help="SDK Vertex project ID."),
    location: str | None = typer.Option(None, help="SDK Vertex location, for example us-central1."),
    db: Path = typer.Option(Path(".cosci/cosci.sqlite3"), help="SQLite file for runs, artifacts, and scores."),
    save_dir: Path = typer.Option(
        Path(".cosci/antigravity"),
        help="SDK mode only: Antigravity conversation save directory.",
    ),
    dry_run: bool = typer.Option(False, help="Print representative prompts without model calls."),
) -> None:
    """Run the full co-scientist loop for a research goal."""
    load_project_env()
    profile = RuntimeProfile(
        backend=backend,
        model=model,
        thinking_level=thinking,
        agy_path=agy_path,
        print_timeout=print_timeout,
        api_key_env=api_key_env,
        vertex=vertex,
        project=project,
        location=location,
        literature=literature,
        literature_results=literature_results,
        literature_provider=literature_provider,
        ads_token_env=ads_token_env,
    )
    run_state = RunState(goal=goal, profile=profile)

    if dry_run:
        _print_dry_run(goal, initial, evolved, profile)
        return

    store = Store(db)
    if backend == "agy":
        client = AgyClient(profile=profile, workspace=Path.cwd())
    elif backend == "sdk":
        client = AntigravityClient(
            profile=profile,
            workspace=Path.cwd(),
            save_dir=save_dir,
        )
    else:
        console.print("[red]Backend must be 'agy' or 'sdk'.[/red]")
        raise typer.Exit(2)
    literature_client = LiteratureClient(
        provider=literature_provider,
        ads_token_env=ads_token_env,
    )
    try:
        hypotheses, review = asyncio.run(
            CoScientist(client, store, literature_client=literature_client).run(
                run_state,
                rounds=rounds,
                initial_hypotheses=initial,
                evolved_hypotheses=evolved,
                tournament_matches=tournament_matches,
                elo_k=elo_k,
            )
        )
    finally:
        store.close()

    console.print(f"[bold]Run:[/bold] {run_state.id}")
    _print_hypotheses(hypotheses[:10])
    console.print("\n[bold]Meta-review[/bold]")
    console.print(review)


@app.command()
def literature(
    query: str = typer.Argument(..., help="ADS/arXiv query string."),
    provider: str = typer.Option(
        "auto",
        help="Provider: `auto`, `ads`, `arxiv`, or `none`.",
    ),
    limit: int = typer.Option(5, help="Maximum records to print."),
    ads_token_env: str = typer.Option(
        "ADS_API_TOKEN",
        help="Environment variable read from `.env`/environment for the ADS token.",
    ),
) -> None:
    """Search ADS/arXiv and print the compact literature brief."""
    load_project_env()
    try:
        records = LiteratureClient(provider=provider, ads_token_env=ads_token_env).search(
            query,
            limit=limit,
        )
    except Exception as exc:
        console.print(f"[red]Literature search failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(literature_brief(records))


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Single prompt to send through the selected backend."),
    backend: str = typer.Option("agy", help="Backend: `agy` subscription CLI or `sdk` API/Vertex."),
    model: str = typer.Option("gemini-3.5-flash", help="Model name passed to the backend."),
    thinking: str = typer.Option("medium", help="SDK mode only: Gemini thinking level."),
    agy_path: str = typer.Option("agy", help="Path or command name for the Antigravity CLI."),
    print_timeout: str = typer.Option("5m", help="agy mode only: timeout for the single `agy --print` call."),
    api_key_env: str = typer.Option("GEMINI_API_KEY", help="SDK mode only: Gemini API-key env var."),
    vertex: bool = typer.Option(False, help="SDK mode only: use Vertex AI backend."),
    project: str | None = typer.Option(None, help="SDK Vertex project ID."),
    location: str | None = typer.Option(None, help="SDK Vertex location, for example us-central1."),
    save_dir: Path = typer.Option(Path(".cosci/antigravity"), help="SDK mode only: conversation save dir."),
) -> None:
    """Send one prompt through the configured backend."""
    load_project_env()
    profile = RuntimeProfile(
        backend=backend,
        model=model,
        thinking_level=thinking,
        agy_path=agy_path,
        print_timeout=print_timeout,
        api_key_env=api_key_env,
        vertex=vertex,
        project=project,
        location=location,
    )
    if backend == "agy":
        client = AgyClient(profile=profile, workspace=Path.cwd())
    elif backend == "sdk":
        client = AntigravityClient(profile=profile, workspace=Path.cwd(), save_dir=save_dir)
    else:
        console.print("[red]Backend must be 'agy' or 'sdk'.[/red]")
        raise typer.Exit(2)
    console.print(asyncio.run(client.ask(prompt)))


def _print_dry_run(
    goal: str, initial: int, evolved: int, profile: RuntimeProfile
) -> None:
    console.print("[bold]Antigravity dry run[/bold]")
    if profile.backend == "agy":
        backend = f"agy CLI at {profile.agy_path}"
    else:
        backend = "Vertex" if profile.vertex else f"API key via ${profile.api_key_env}"
    console.print(
        f"Runtime: {profile.model}, thinking={profile.thinking_level}, backend={backend}"
    )
    console.print(
        f"Literature: {profile.literature_provider}, "
        f"enabled={profile.literature}, n={profile.literature_results}"
    )
    for name, prompt in [
        ("generation", generation_prompt(goal, initial)),
        ("reflection", reflection_prompt(goal, [])),
        (
            "pairwise debate",
            pairwise_debate_prompt(
                goal,
                _example_hypothesis("A"),
                _example_hypothesis("B"),
            ),
        ),
        ("evolution", evolution_prompt(goal, [], evolved)),
    ]:
        console.rule(name)
        console.print(prompt.strip())


def _print_hypotheses(hypotheses) -> None:
    table = Table(title="Top hypotheses")
    table.add_column("Score", justify="right")
    table.add_column("Title")
    table.add_column("Claim")
    for h in hypotheses:
        table.add_row(f"{h.score:.0f}", h.title, h.claim)
    console.print(table)


def _example_hypothesis(label: str):
    from cosci.models import Hypothesis

    return Hypothesis(
        id=f"example_{label.lower()}",
        title=f"Example hypothesis {label}",
        claim="A concrete microlensing modelling claim goes here.",
        rationale="Why it might matter.",
        microlensing_relevance="Binary-lens degeneracy or survey-systematics relevance.",
        tests=["Run synthetic light-curve injection tests."],
        risks=["May be explained by a simpler cadence artefact."],
    )


if __name__ == "__main__":
    app()
