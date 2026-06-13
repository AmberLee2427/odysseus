from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AgentRole(StrEnum):
    LITERATURE = "literature"
    GENERATION = "generation"
    REFLECTION = "reflection"
    RANKING = "ranking"
    EVOLUTION = "evolution"
    META_REVIEW = "meta_review"


class RuntimeProfile(BaseModel):
    backend: str = "agy"
    model: str = "gemini-3.5-flash"
    thinking_level: str = "medium"
    agy_path: str = "agy"
    print_timeout: str = "5m"
    vertex: bool = False
    project: str | None = None
    location: str | None = None
    api_key_env: str = "GEMINI_API_KEY"
    literature: bool = True
    literature_results: int = 5
    ads_token_env: str = "ADS_API_TOKEN"
    literature_provider: str = "auto"


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: f"hyp_{uuid4().hex[:12]}")
    title: str
    claim: str
    rationale: str = ""
    microlensing_relevance: str = ""
    tests: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    score: float = 1000.0
    parent_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class AgentArtifact(BaseModel):
    id: str = Field(default_factory=lambda: f"art_{uuid4().hex[:12]}")
    run_id: str
    role: AgentRole
    round_index: int
    prompt: str
    response_text: str
    parsed: dict[str, Any] | list[Any] | None = None
    created_at: str = Field(default_factory=utc_now)


class LiteratureRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"lit_{uuid4().hex[:12]}")
    provider: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    bibcode: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    citation_count: int | None = None
    created_at: str = Field(default_factory=utc_now)


class RunState(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:12]}")
    goal: str
    profile: RuntimeProfile = Field(default_factory=RuntimeProfile)
    created_at: str = Field(default_factory=utc_now)
