from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


class DecisionConflict(Exception):
    pass


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    review_id: str
    project: str
    requester: str
    baseline: str
    candidate: str
    baseline_revision: str
    candidate_revision: str
    split_fingerprint: str
    training_protocol: str
    evaluation_protocol: str
    seed: int
    metric_epoch: int | None = None


class Store:
    def __init__(self, path: Path, database_url: str = "") -> None:
        self.path = path
        self.database_url = database_url
        with self.connect() as conn:
            self.execute(conn, """
                CREATE TABLE IF NOT EXISTS pilot_proposals (
                    id TEXT PRIMARY KEY, review_id TEXT NOT NULL, project TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL, reviewer TEXT, reason TEXT
                )
            """)
            self.execute(conn, """
                CREATE TABLE IF NOT EXISTS pilot_queue (
                    id TEXT PRIMARY KEY, proposal_id TEXT UNIQUE NOT NULL
                )
            """)
            self.execute(conn, """
                CREATE TABLE IF NOT EXISTS pilot_usage (
                    review_id TEXT NOT NULL, turn_id TEXT NOT NULL, stage TEXT NOT NULL,
                    model TEXT, input_tokens INTEGER, output_tokens INTEGER,
                    cost_usd DOUBLE PRECISION, elapsed_ms DOUBLE PRECISION NOT NULL
                )
            """)

    @contextmanager
    def connect(self):
        if self.database_url:
            with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=4) as conn:
                yield conn
            return
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def execute(self, conn, sql: str, params: tuple = ()):
        if self.database_url:
            sql = sql.replace("?", "%s")
        return conn.execute(sql, params)

    @staticmethod
    def _proposal(row) -> dict | None:
        if row is None:
            return None
        state = row["state"]
        return {
            **json.loads(row["payload"]),
            "state": state,
            "reviewer": row["reviewer"],
            "reason": row["reason"],
            "job_id": f"job-{row['id']}" if state == "approved" else None,
        }

    def create_proposal(self, proposal: Proposal) -> dict:
        with self.connect() as conn:
            self.execute(conn, """
                INSERT INTO pilot_proposals (id, review_id, project, payload, state)
                VALUES (?, ?, ?, ?, 'pending') ON CONFLICT (id) DO NOTHING
            """, (proposal.proposal_id, proposal.review_id, proposal.project,
                  json.dumps(asdict(proposal), ensure_ascii=False)))
            row = self.execute(conn, "SELECT * FROM pilot_proposals WHERE id = ?",
                               (proposal.proposal_id,)).fetchone()
            return self._proposal(row)

    def pending(self, project: str) -> list[dict]:
        with self.connect() as conn:
            rows = self.execute(conn, """
                SELECT * FROM pilot_proposals
                WHERE project = ? AND state = 'pending' ORDER BY id
            """, (project,)).fetchall()
        return [self._proposal(row) for row in rows]

    def decide(self, project: str, proposal_id: str, reviewer: str, approve: bool,
               reason: str) -> dict:
        state = "approved" if approve else "rejected"
        with self.connect() as conn:
            self.execute(conn, """
                UPDATE pilot_proposals SET state = ?, reviewer = ?, reason = ?
                WHERE id = ? AND project = ? AND state = 'pending'
            """, (state, reviewer, reason, proposal_id, project))
            row = self.execute(conn, "SELECT * FROM pilot_proposals WHERE id = ? AND project = ?",
                               (proposal_id, project)).fetchone()
            if row is None:
                raise LookupError(proposal_id)
            if (row["state"], row["reviewer"], row["reason"]) != (state, reviewer, reason):
                raise DecisionConflict("申请已由其他决策处理")
            if approve:
                self.execute(conn, """
                    INSERT INTO pilot_queue (id, proposal_id) VALUES (?, ?)
                    ON CONFLICT (proposal_id) DO NOTHING
                """, (f"job-{proposal_id}", proposal_id))
        return self._proposal(row)

    def ping(self) -> None:
        with self.connect() as conn:
            self.execute(conn, "SELECT 1").fetchone()

    def queued_count(self) -> int:
        with self.connect() as conn:
            row = self.execute(conn, "SELECT count(*) AS n FROM pilot_queue").fetchone()
        return row["n"]

    def record(self, review_id: str, turn_id: str, stage: str, elapsed_ms: float,
               model: str | None = None, input_tokens: int | None = None,
               output_tokens: int | None = None, cost_usd: float | None = None) -> None:
        with self.connect() as conn:
            self.execute(conn, """
                INSERT INTO pilot_usage (
                    review_id, turn_id, stage, elapsed_ms,
                    model, input_tokens, output_tokens, cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (review_id, turn_id, stage, elapsed_ms, model, input_tokens,
                  output_tokens, cost_usd))

    def usage(self, review_id: str) -> dict:
        with self.connect() as conn:
            rows = self.execute(conn, """
                SELECT * FROM pilot_usage WHERE review_id = ?
            """, (review_id,)).fetchall()
        calls = [row for row in rows if row["model"]]
        priced = [row["cost_usd"] for row in calls if row["cost_usd"] is not None]
        return {
            "model_calls": len(calls),
            "input_tokens": sum(row["input_tokens"] or 0 for row in calls),
            "output_tokens": sum(row["output_tokens"] or 0 for row in calls),
            "unreported_usage_calls": sum(
                row["input_tokens"] is None or row["output_tokens"] is None for row in calls
            ),
            "cost_usd": round(sum(priced), 8) if len(priced) == len(calls) else None,
            "unpriced_calls": len(calls) - len(priced),
            "node_ms": round(sum(row["elapsed_ms"] for row in rows if not row["model"]), 2),
        }
