from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from cosci.models import AgentArtifact, Hypothesis, LiteratureRecord, RunState


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def close(self) -> None:
        self.conn.close()

    def _init(self) -> None:
        self.conn.executescript(
            """
            create table if not exists runs (
              id text primary key,
              goal text not null,
              profile_json text not null,
              created_at text not null
            );
            create table if not exists hypotheses (
              id text primary key,
              run_id text not null,
              payload_json text not null,
              created_at text not null
            );
            create table if not exists artifacts (
              id text primary key,
              run_id text not null,
              role text not null,
              round_index integer not null,
              prompt text not null,
              response_text text not null,
              parsed_json text,
              created_at text not null
            );
            create table if not exists literature_records (
              id text primary key,
              run_id text not null,
              provider text not null,
              title text not null,
              payload_json text not null,
              created_at text not null
            );
            """
        )
        self.conn.commit()

    def save_run(self, run: RunState) -> None:
        self.conn.execute(
            "insert into runs (id, goal, profile_json, created_at) values (?, ?, ?, ?)",
            (
                run.id,
                run.goal,
                run.profile.model_dump_json(),
                run.created_at,
            ),
        )
        self.conn.commit()

    def save_hypotheses(self, run_id: str, hypotheses: Iterable[Hypothesis]) -> None:
        self.conn.executemany(
            """
            insert or replace into hypotheses (id, run_id, payload_json, created_at)
            values (?, ?, ?, ?)
            """,
            [
                (h.id, run_id, h.model_dump_json(), h.created_at)
                for h in hypotheses
            ],
        )
        self.conn.commit()

    def save_artifact(self, artifact: AgentArtifact) -> None:
        parsed_json = None
        if artifact.parsed is not None:
            parsed_json = json.dumps(artifact.parsed, ensure_ascii=True)
        self.conn.execute(
            """
            insert into artifacts
            (id, run_id, role, round_index, prompt, response_text, parsed_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.id,
                artifact.run_id,
                artifact.role.value,
                artifact.round_index,
                artifact.prompt,
                artifact.response_text,
                parsed_json,
                artifact.created_at,
            ),
        )
        self.conn.commit()

    def save_literature(
        self, run_id: str, records: Iterable[LiteratureRecord]
    ) -> None:
        self.conn.executemany(
            """
            insert or replace into literature_records
            (id, run_id, provider, title, payload_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.id,
                    run_id,
                    record.provider,
                    record.title,
                    record.model_dump_json(),
                    record.created_at,
                )
                for record in records
            ],
        )
        self.conn.commit()
