from __future__ import annotations

import json
import re
from itertools import combinations
from typing import Protocol

from cosci.literature import LiteratureClient, literature_brief
from cosci.models import AgentArtifact, AgentRole, Hypothesis, RunState
from cosci.prompts import (
    evolution_prompt,
    generation_prompt,
    meta_review_prompt,
    pairwise_debate_prompt,
    reflection_prompt,
)
from cosci.store import Store


class ResearchClient(Protocol):
    async def ask(self, prompt: str) -> str: ...


class CoScientist:
    def __init__(
        self,
        client: ResearchClient,
        store: Store,
        literature_client: LiteratureClient | None = None,
    ):
        self.client = client
        self.store = store
        self.literature_client = literature_client

    async def run(
        self,
        run: RunState,
        rounds: int = 1,
        initial_hypotheses: int = 5,
        evolved_hypotheses: int = 3,
        tournament_matches: int = 6,
        elo_k: float = 32.0,
    ) -> tuple[list[Hypothesis], str]:
        self.store.save_run(run)
        literature_context = self._search_literature(run)

        hypotheses = await self._generate(run, initial_hypotheses, literature_context)
        self.store.save_hypotheses(run.id, hypotheses)

        for round_index in range(1, rounds + 1):
            await self._reflect(run, hypotheses, round_index, literature_context)
            await self._tournament(
                run,
                hypotheses,
                round_index,
                max_matches=tournament_matches,
                elo_k=elo_k,
                literature_context=literature_context,
            )
            hypotheses = sorted(hypotheses, key=lambda h: h.score, reverse=True)
            evolved = await self._evolve(
                run,
                hypotheses[: min(3, len(hypotheses))],
                round_index,
                evolved_hypotheses,
                literature_context,
            )
            hypotheses.extend(evolved)
            self.store.save_hypotheses(run.id, hypotheses)

        hypotheses = sorted(hypotheses, key=lambda h: h.score, reverse=True)
        review = await self._meta_review(run, hypotheses[:8], rounds, literature_context)
        return hypotheses, review

    def _search_literature(self, run: RunState) -> str:
        if not run.profile.literature or self.literature_client is None:
            return ""
        records = self.literature_client.search(
            run.goal,
            limit=run.profile.literature_results,
        )
        self.store.save_literature(run.id, records)
        brief = literature_brief(records)
        self._save_artifact(
            run,
            AgentRole.LITERATURE,
            0,
            run.goal,
            brief,
            [record.model_dump(mode="json") for record in records],
        )
        return brief

    async def _generate(
        self, run: RunState, n: int, literature_context: str
    ) -> list[Hypothesis]:
        prompt = generation_prompt(run.goal, n, literature_context)
        text, parsed = await self._ask_json(
            prompt,
            required_keys=["hypotheses"],
            schema_hint=(
                '{"hypotheses":[{"title":"...","claim":"...","rationale":"...",'
                '"microlensing_relevance":"...","tests":["..."],"risks":["..."],'
                '"citations":["..."]}]}'
            ),
        )
        self._save_artifact(run, AgentRole.GENERATION, 0, prompt, text, parsed)
        return [
            Hypothesis(**item)
            for item in parsed.get("hypotheses", [])
            if isinstance(item, dict)
        ]

    async def _reflect(
        self,
        run: RunState,
        hypotheses: list[Hypothesis],
        round_index: int,
        literature_context: str,
    ) -> None:
        prompt = reflection_prompt(run.goal, hypotheses, literature_context)
        text, parsed = await self._ask_json(
            prompt,
            required_keys=["critiques"],
            schema_hint=(
                '{"critiques":[{"hypothesis_id":"...","strengths":["..."],'
                '"weaknesses":["..."],"suggested_tests":["..."],"score_delta":0}]}'
            ),
        )
        self._save_artifact(run, AgentRole.REFLECTION, round_index, prompt, text, parsed)
        for critique in parsed.get("critiques", []):
            hyp = _find_hypothesis(hypotheses, critique.get("hypothesis_id"))
            if hyp is None:
                continue
            hyp.risks.extend(critique.get("weaknesses", []))
            hyp.tests.extend(critique.get("suggested_tests", []))
            hyp.score += float(critique.get("score_delta", 0) or 0)

    async def _tournament(
        self,
        run: RunState,
        hypotheses: list[Hypothesis],
        round_index: int,
        max_matches: int,
        elo_k: float,
        literature_context: str,
    ) -> None:
        if len(hypotheses) < 2 or max_matches == 0:
            return

        ordered = sorted(hypotheses, key=lambda h: h.score, reverse=True)
        pairs = list(combinations(ordered, 2))
        if max_matches > 0:
            pairs = pairs[:max_matches]

        for match_index, (hypothesis_a, hypothesis_b) in enumerate(pairs, start=1):
            prompt = pairwise_debate_prompt(
                run.goal, hypothesis_a, hypothesis_b, literature_context
            )
            text, parsed = await self._ask_json(
                prompt,
                required_keys=["winner", "confidence", "reason"],
                schema_hint=(
                    '{"winner":"a","confidence":0.75,"reason":"...",'
                    '"a_strengths":["..."],"b_strengths":["..."],'
                    '"decisive_criteria":["..."]}'
                ),
            )
            parsed["hypothesis_a_id"] = hypothesis_a.id
            parsed["hypothesis_b_id"] = hypothesis_b.id
            parsed["match_index"] = match_index
            self._save_artifact(
                run,
                AgentRole.RANKING,
                round_index,
                prompt,
                text,
                parsed,
            )
            apply_elo_result(hypothesis_a, hypothesis_b, parsed, elo_k=elo_k)

    async def _evolve(
        self,
        run: RunState,
        hypotheses: list[Hypothesis],
        round_index: int,
        n: int,
        literature_context: str,
    ) -> list[Hypothesis]:
        prompt = evolution_prompt(run.goal, hypotheses, n, literature_context)
        text, parsed = await self._ask_json(
            prompt,
            required_keys=["hypotheses"],
            schema_hint=(
                '{"hypotheses":[{"title":"...","claim":"...","rationale":"...",'
                '"microlensing_relevance":"...","tests":["..."],"risks":["..."],'
                '"citations":["..."],"parent_ids":["..."]}]}'
            ),
        )
        self._save_artifact(run, AgentRole.EVOLUTION, round_index, prompt, text, parsed)
        evolved = []
        for item in parsed.get("hypotheses", []):
            if isinstance(item, dict):
                evolved.append(Hypothesis(**item))
        return evolved

    async def _meta_review(
        self,
        run: RunState,
        hypotheses: list[Hypothesis],
        round_index: int,
        literature_context: str,
    ) -> str:
        prompt = meta_review_prompt(run.goal, hypotheses, literature_context)
        text = await self.client.ask(prompt)
        self._save_artifact(run, AgentRole.META_REVIEW, round_index, prompt, text, None)
        return text

    async def _ask_json(
        self,
        prompt: str,
        required_keys: list[str],
        schema_hint: str,
    ) -> tuple[str, dict]:
        text = await self.client.ask(prompt)
        try:
            parsed = parse_json_object(text)
            validate_required_keys(parsed, required_keys)
            return text, parsed
        except (json.JSONDecodeError, ValueError) as first_error:
            repair_prompt = json_repair_prompt(text, schema_hint, str(first_error))
            repaired_text = await self.client.ask(repair_prompt)
            parsed = parse_json_object(repaired_text)
            validate_required_keys(parsed, required_keys)
            combined_text = (
                f"{text}\n\n--- JSON REPAIR REQUEST ---\n{repair_prompt}"
                f"\n\n--- JSON REPAIR RESPONSE ---\n{repaired_text}"
            )
            return combined_text, parsed

    def _save_artifact(
        self,
        run: RunState,
        role: AgentRole,
        round_index: int,
        prompt: str,
        response_text: str,
        parsed: dict | list | None,
    ) -> None:
        self.store.save_artifact(
            AgentArtifact(
                run_id=run.id,
                role=role,
                round_index=round_index,
                prompt=prompt,
                response_text=response_text,
                parsed=parsed,
            )
        )


def parse_json_object(text: str) -> dict:
    text = strip_code_fence(text.strip())
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        object_text = extract_json_object_text(text)
        if object_text is None:
            raise
        parsed = json.loads(object_text)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object from agent response.")
    return parsed


def validate_required_keys(parsed: dict, required_keys: list[str]) -> None:
    missing = [key for key in required_keys if key not in parsed]
    if missing:
        raise ValueError(f"JSON object is missing required keys: {', '.join(missing)}")


def json_repair_prompt(raw_text: str, schema_hint: str, error: str) -> str:
    return f"""
Convert the text below into valid JSON only. Do not add explanation, Markdown,
code fences, or prose. Preserve the scientific content where possible.

Required JSON shape:
{schema_hint}

Parser error:
{error}

Text to repair:
{raw_text}
"""


def strip_code_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text


def extract_json_object_text(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def apply_elo_result(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    result: dict,
    elo_k: float = 32.0,
) -> None:
    winner = str(result.get("winner", "")).strip().lower()
    confidence = _clamp(float(result.get("confidence", 1.0) or 1.0), 0.25, 1.0)
    k = elo_k * confidence

    expected_a = 1.0 / (1.0 + 10.0 ** ((hypothesis_b.score - hypothesis_a.score) / 400.0))
    if winner in {hypothesis_a.id.lower(), "a", "hypothesis_a"}:
        actual_a = 1.0
    elif winner in {hypothesis_b.id.lower(), "b", "hypothesis_b"}:
        actual_a = 0.0
    elif winner == "tie":
        actual_a = 0.5
    else:
        raise ValueError(f"Unexpected tournament winner: {winner!r}")

    delta_a = k * (actual_a - expected_a)
    hypothesis_a.score += delta_a
    hypothesis_b.score -= delta_a


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _find_hypothesis(
    hypotheses: list[Hypothesis], hypothesis_id: str | None
) -> Hypothesis | None:
    if not hypothesis_id:
        return None
    return next((h for h in hypotheses if h.id == hypothesis_id), None)
