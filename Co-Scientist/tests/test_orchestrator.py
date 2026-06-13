from __future__ import annotations

import pytest

from cosci.agy_client import AgyClient
from cosci.antigravity_client import AntigravityClient
from cosci.env import load_project_env
from cosci.literature import LiteratureClient, search_ads, search_arxiv
from cosci.models import LiteratureRecord
from cosci.models import Hypothesis, RuntimeProfile, RunState
from cosci.mcp_server import coscientist_status, search_literature_tool
from cosci.orchestrator import (
    CoScientist,
    apply_elo_result,
    extract_json_object_text,
    parse_json_object,
)
from cosci.store import Store


class FakeClient:
    def __init__(self):
        self.prompts = []

    async def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Generate" in prompt:
            return """{"hypotheses":[{"id":"hyp_a","title":"Finite-source parallax coupling","claim":"Finite-source effects can masquerade as weak parallax in selected caustic-crossing events.","rationale":"Both perturb long-timescale residuals when cadence is uneven.","microlensing_relevance":"binary lens modelling","tests":["inject synthetic caustic crossings"],"risks":["selection bias"],"citations":[]},{"id":"hyp_b","title":"Cadence-window caustic bias","claim":"Roman cadence windows can bias caustic topology selection in binary-lens fits.","rationale":"Missed ingress/egress points change topology likelihoods.","microlensing_relevance":"Roman binary lens modelling","tests":["resample synthetic caustic crossings"],"risks":["depends on alert strategy"],"citations":[]}]}"""
        if '"critiques"' in prompt:
            return """{"critiques":[{"hypothesis_id":"missing","strengths":[],"weaknesses":["needs Roman cadence check"],"suggested_tests":["simulate cadence gaps"],"score_delta":25}]}"""
        if "Compare two hypotheses" in prompt:
            return """{"winner":"a","confidence":1.0,"reason":"A is more physically specific.","a_strengths":["specific degeneracy"],"b_strengths":["survey relevance"],"decisive_criteria":["testability"]}"""
        if "Improve the strongest" in prompt:
            return """{"hypotheses":[]}"""
        return "Most promising direction: test the degeneracy on synthetic light curves."


class FakeLiteratureClient:
    def search(self, query: str, limit: int = 5):
        return [
            LiteratureRecord(
                provider="ads",
                title="Roman microlensing detector systematics",
                authors=["A. Astronomer"],
                year=2026,
                abstract="Detector effects can bias high-cadence light curves.",
                bibcode="2026Test....1A",
            )
        ]


class BrokenJsonClient:
    def __init__(self):
        self.prompts = []

    async def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Convert the text below into valid JSON only" in prompt:
            return """{"hypotheses":[{"id":"hyp_repaired","title":"Repaired","claim":"A repaired claim.","rationale":"","microlensing_relevance":"","tests":[],"risks":[],"citations":[]}]}"""
        if "Generate" in prompt:
            return "Here is the result:\n- Repaired: A repaired claim."
        return "Meta-review."


def test_parse_json_object_strips_markdown():
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_parse_json_object_extracts_first_balanced_object():
    text = 'Before {"outer": {"inner": "brace } inside string"}, "ok": true} after {"x": 1}'
    assert parse_json_object(text) == {
        "outer": {"inner": "brace } inside string"},
        "ok": True,
    }


def test_extract_json_object_text_returns_none_for_missing_object():
    assert extract_json_object_text("no json here") is None


@pytest.mark.asyncio
async def test_orchestrator_dry_fake_loop(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    client = FakeClient()
    run = RunState(
        goal="Find microlensing modelling systematics.",
        profile=RuntimeProfile(),
    )
    try:
        hypotheses, review = await CoScientist(
            client, store, literature_client=FakeLiteratureClient()
        ).run(run, rounds=1)
    finally:
        store.close()

    assert len(hypotheses) == 2
    assert "Finite-source" in hypotheses[0].title
    assert "Most promising" in review
    assert len(client.prompts) == 5
    assert hypotheses[0].score > hypotheses[1].score
    assert "Literature context" in client.prompts[0]
    assert "Roman microlensing detector systematics" in client.prompts[0]


@pytest.mark.asyncio
async def test_json_repair_loop_for_generation(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    client = BrokenJsonClient()
    run = RunState(
        goal="Find microlensing modelling systematics.",
        profile=RuntimeProfile(literature=False),
    )
    try:
        hypotheses, review = await CoScientist(client, store).run(
            run,
            rounds=0,
            initial_hypotheses=1,
        )
    finally:
        store.close()

    assert hypotheses[0].id == "hyp_repaired"
    assert review == "Meta-review."
    assert any("Required JSON shape" in prompt for prompt in client.prompts)


def test_apply_elo_result_updates_scores():
    a = Hypothesis(id="a", title="A", claim="A")
    b = Hypothesis(id="b", title="B", claim="B")

    apply_elo_result(a, b, {"winner": "a", "confidence": 1.0}, elo_k=32)

    assert round(a.score, 1) == 1016.0
    assert round(b.score, 1) == 984.0


@pytest.mark.asyncio
async def test_antigravity_client_rejects_missing_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("COSCI_TEST_KEY", raising=False)
    client = AntigravityClient(
        RuntimeProfile(api_key_env="COSCI_TEST_KEY"),
        tmp_path,
        tmp_path / "ag",
    )

    with pytest.raises(RuntimeError, match="subscription auth"):
        await client.ask("hello")


@pytest.mark.asyncio
async def test_agy_client_uses_print_mode(tmp_path):
    fake_agy = tmp_path / "agy"
    fake_agy.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > args.txt\n"
        "printf 'AGY RESPONSE\\n'\n",
        encoding="utf-8",
    )
    fake_agy.chmod(0o755)

    client = AgyClient(
        RuntimeProfile(agy_path=str(fake_agy), model="gemini-3.5-flash"),
        tmp_path,
    )
    response = await client.ask("hello")

    assert response == "AGY RESPONSE"
    args = (tmp_path / "args.txt").read_text(encoding="utf-8")
    assert "--print" in args
    assert "--model" in args
    assert "gemini-3.5-flash" in args


def test_literature_client_falls_back_to_arxiv(monkeypatch):
    monkeypatch.delenv("COSCI_TEST_ADS", raising=False)

    def fake_arxiv(query, limit):
        return [LiteratureRecord(provider="arxiv", title=query)]

    monkeypatch.setattr("cosci.literature.search_arxiv", fake_arxiv)

    records = LiteratureClient(provider="auto", ads_token_env="COSCI_TEST_ADS").search(
        "microlensing", 1
    )

    assert records[0].provider == "arxiv"


def test_search_ads_parses_response(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"""{"response":{"docs":[{"bibcode":"2026A&A...1A","title":["A title"],"author":["A. One"],"year":2026,"abstract":"Abstract text","doi":["10.1/test"],"citation_count":7,"identifier":["arXiv:2601.12345"]}]}}"""

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())

    records = search_ads("roman microlensing", "token", 1)

    assert records[0].provider == "ads"
    assert records[0].bibcode == "2026A&A...1A"
    assert records[0].arxiv_id == "2601.12345"


def test_search_arxiv_parses_response(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def results(self, search):
            return [
                SimpleNamespace(
                    title=" A Roman microlensing paper ",
                    authors=[SimpleNamespace(name="A. Author")],
                    published=datetime(2026, 1, 1, tzinfo=UTC),
                    summary=" Abstract text. ",
                    entry_id="http://arxiv.org/abs/2601.12345v1",
                    doi="10.1/example",
                )
            ]

    monkeypatch.setattr("arxiv.Client", FakeClient)

    records = search_arxiv("roman microlensing", 1)

    assert records[0].provider == "arxiv"
    assert records[0].year == 2026
    assert records[0].doi == "10.1/example"


def test_load_project_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("COSCI_TEST_ENV=loaded\n", encoding="utf-8")
    monkeypatch.delenv("COSCI_TEST_ENV", raising=False)

    load_project_env(env_file)

    import os

    assert os.environ["COSCI_TEST_ENV"] == "loaded"


def test_mcp_status_shape():
    status = coscientist_status()

    assert "workspace" in status
    assert "agy_path" in status
    assert "ads_token_available" in status


def test_mcp_literature_tool_none_provider():
    result = search_literature_tool("microlensing", provider="none", limit=2)

    assert result["provider"] == "none"
    assert result["records"] == []
    assert "No literature records" in result["brief"]
