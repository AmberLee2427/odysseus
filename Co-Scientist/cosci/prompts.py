from __future__ import annotations

import json

from cosci.models import Hypothesis


DOMAIN_BIAS = """
You are supporting a professional astronomer whose specialty is gravitational
microlensing modelling. Default to that context when a scientific goal is broad.
Prefer concrete modelling ideas: lens-source geometry, binary/triple lens
degeneracies, finite-source effects, parallax, xallarap, orbital motion,
limb-darkening, cadence/window functions, survey selection effects, Roman/OGLE/KMTNet
data, Bayesian priors, caustic topology, numerical stability, and validation with
synthetic light curves. Avoid biomedical defaults.
"""


SYSTEM_INSTRUCTIONS = f"""
You are a private research co-scientist running inside Google Antigravity.
This is not a general SaaS product. Optimize for one expert user's scientific
workflow, not broad usability.

Operate as a rigorous scientific collaborator:
- generate hypotheses that are testable, falsifiable, and specific;
- separate evidence, speculation, and proposed checks;
- identify degeneracies and observational selection effects;
- cite literature identifiers when you know them, but do not invent citations;
- be comfortable saying that a claim needs external verification.
- do not inspect the workspace, read files, or use tools unless the current
  prompt explicitly asks you to.

{DOMAIN_BIAS}
"""


def generation_prompt(goal: str, n: int, literature_context: str = "") -> str:
    return f"""
Research goal:
{goal}

Literature context:
{_literature_context(literature_context)}

Generate {n} initial research hypotheses. Return only JSON with this shape:
{{
  "hypotheses": [
    {{
      "title": "...",
      "claim": "...",
      "rationale": "...",
      "microlensing_relevance": "...",
      "tests": ["..."],
      "risks": ["..."],
      "citations": ["..."]
    }}
  ]
}}
"""


def reflection_prompt(
    goal: str, hypotheses: list[Hypothesis], literature_context: str = ""
) -> str:
    return f"""
Research goal:
{goal}

Literature context:
{_literature_context(literature_context)}

Critique these hypotheses as a skeptical microlensing modeller. Focus on hidden
degeneracies, missing observables, false novelty, and practical validation.

Hypotheses:
{_hypotheses_json(hypotheses)}

Return only JSON:
{{
  "critiques": [
    {{
      "hypothesis_id": "...",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "suggested_tests": ["..."],
      "score_delta": 0
    }}
  ]
}}
"""


def pairwise_debate_prompt(
    goal: str,
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    literature_context: str = "",
) -> str:
    return f"""
Research goal:
{goal}

Literature context:
{_literature_context(literature_context)}

Compare two hypotheses in a scientific debate. Judge which is more valuable to
an expert microlensing modeller right now. Prefer novelty, physical plausibility,
testability with real or synthetic light curves, ability to expose modelling
systematics, and usefulness for astronomical inference.

Hypothesis A:
{_hypotheses_json([hypothesis_a])}

Hypothesis B:
{_hypotheses_json([hypothesis_b])}

Return only JSON:
{{
  "winner": "a",
  "confidence": 0.75,
  "reason": "...",
  "a_strengths": ["..."],
  "b_strengths": ["..."],
  "decisive_criteria": ["..."]
}}

Use "winner": "tie" only when the hypotheses are genuinely inseparable.
"""


def evolution_prompt(
    goal: str,
    hypotheses: list[Hypothesis],
    n: int,
    literature_context: str = "",
) -> str:
    return f"""
Research goal:
{goal}

Literature context:
{_literature_context(literature_context)}

Improve the strongest hypotheses below. You may merge related ideas, sharpen
claims, add concrete observational or simulation tests, or propose a more
interesting variant. Produce {n} evolved hypotheses.

Current hypotheses:
{_hypotheses_json(hypotheses)}

Return only JSON with the same shape used by generation:
{{
  "hypotheses": [
    {{
      "title": "...",
      "claim": "...",
      "rationale": "...",
      "microlensing_relevance": "...",
      "tests": ["..."],
      "risks": ["..."],
      "citations": ["..."],
      "parent_ids": ["..."]
    }}
  ]
}}
"""


def meta_review_prompt(
    goal: str, hypotheses: list[Hypothesis], literature_context: str = ""
) -> str:
    return f"""
Research goal:
{goal}

Literature context:
{_literature_context(literature_context)}

Write a concise meta-review of the current hypothesis set for the astronomer.
Identify the most promising direction, key failure modes, and the next modelling
or simulation task to run.

Hypotheses:
{_hypotheses_json(hypotheses)}
"""


def _hypotheses_json(hypotheses: list[Hypothesis]) -> str:
    return json.dumps(
        [h.model_dump(mode="json") for h in hypotheses],
        indent=2,
        ensure_ascii=True,
    )


def _literature_context(literature_context: str) -> str:
    if literature_context.strip():
        return literature_context.strip()
    return "No retrieved literature context was supplied. Do not invent citations."
