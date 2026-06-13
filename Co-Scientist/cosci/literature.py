from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

import arxiv

from cosci.models import LiteratureRecord


ADS_SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"
USER_AGENT = "cosci/0.1.0 (personal research tool; contact local user)"


@dataclass
class LiteratureClient:
    provider: str = "auto"
    ads_token_env: str = "ADS_API_TOKEN"

    def search(self, query: str, limit: int = 5) -> list[LiteratureRecord]:
        provider = self.provider.lower()
        if provider not in {"auto", "ads", "arxiv", "none"}:
            raise ValueError(f"Unknown literature provider: {self.provider}")
        if provider == "none" or limit <= 0:
            return []

        if provider in {"auto", "ads"}:
            token = os.environ.get(self.ads_token_env)
            if token:
                try:
                    records = search_ads(query, token, limit)
                    if records or provider == "ads":
                        return records
                except Exception:
                    if provider == "ads":
                        raise

        if provider in {"auto", "arxiv"}:
            try:
                return search_arxiv(query, limit)
            except Exception:
                return []

        return []


def search_ads(query: str, token: str, limit: int = 5) -> list[LiteratureRecord]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "fl": "bibcode,title,author,year,abstract,doi,citation_count,identifier",
            "rows": str(limit),
            "sort": "score desc",
        }
    )
    req = urllib.request.Request(
        f"{ADS_SEARCH_URL}?{params}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    docs = payload.get("response", {}).get("docs", [])
    return [_ads_record(doc) for doc in docs]


def search_arxiv(query: str, limit: int = 5) -> list[LiteratureRecord]:
    search = arxiv.Search(
        query=query,
        max_results=limit,
        sort_by=arxiv.SortCriterion.Relevance,
        sort_order=arxiv.SortOrder.Descending,
    )
    client = arxiv.Client(page_size=min(max(limit, 1), 100), delay_seconds=5.0, num_retries=5)
    records = []
    for result in client.results(search):
        records.append(
            LiteratureRecord(
                provider="arxiv",
                title=_normalize_space(result.title),
                authors=[author.name for author in result.authors],
                year=result.published.year if result.published else None,
                abstract=_normalize_space(result.summary or ""),
                arxiv_id=result.entry_id.rsplit("/", 1)[-1] if result.entry_id else None,
                doi=result.doi,
                url=result.entry_id,
            )
        )
    return records


def literature_brief(records: list[LiteratureRecord], max_abstract_chars: int = 700) -> str:
    if not records:
        return "No literature records were retrieved for this run."

    lines = []
    for idx, record in enumerate(records, start=1):
        authors = ", ".join(record.authors[:4])
        if len(record.authors) > 4:
            authors += " et al."
        identifiers = []
        if record.bibcode:
            identifiers.append(f"bibcode={record.bibcode}")
        if record.arxiv_id:
            identifiers.append(f"arXiv={record.arxiv_id}")
        if record.doi:
            identifiers.append(f"doi={record.doi}")
        if record.url:
            identifiers.append(record.url)
        abstract = record.abstract[:max_abstract_chars].strip()
        if len(record.abstract) > max_abstract_chars:
            abstract += "..."
        lines.append(
            "\n".join(
                [
                    f"{idx}. {record.title}",
                    f"   Provider/year: {record.provider}, {record.year or 'unknown'}",
                    f"   Authors: {authors or 'unknown'}",
                    f"   IDs: {'; '.join(identifiers) or 'none'}",
                    f"   Abstract: {abstract or 'not available'}",
                ]
            )
        )
    return "\n\n".join(lines)


def _ads_record(doc: dict) -> LiteratureRecord:
    title_value = doc.get("title") or []
    title = title_value[0] if isinstance(title_value, list) and title_value else str(title_value)
    doi_value = doc.get("doi") or []
    doi = doi_value[0] if isinstance(doi_value, list) and doi_value else None
    identifiers = doc.get("identifier") or []
    arxiv_id = _first_arxiv_id(identifiers)
    bibcode = doc.get("bibcode")
    return LiteratureRecord(
        provider="ads",
        title=_normalize_space(title),
        authors=doc.get("author") or [],
        year=doc.get("year"),
        abstract=_normalize_space(doc.get("abstract") or ""),
        bibcode=bibcode,
        doi=doi,
        arxiv_id=arxiv_id,
        url=f"https://ui.adsabs.harvard.edu/abs/{urllib.parse.quote(bibcode, safe='')}/abstract"
        if bibcode
        else None,
        citation_count=doc.get("citation_count"),
    )


def _first_arxiv_id(identifiers: list[str]) -> str | None:
    for identifier in identifiers:
        if identifier.lower().startswith("arxiv:"):
            return identifier.split(":", 1)[1]
    return None


def _normalize_space(value: str) -> str:
    return " ".join(value.split())
