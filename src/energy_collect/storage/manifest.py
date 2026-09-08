from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

JobStatus = Literal["pending", "success", "failed", "skipped"]


@dataclass
class JobRecord:
    job_id: str
    dataset: str
    scope_key: str
    period_start: str
    period_end: str
    status: JobStatus
    row_count: int | None
    file_path: str | None
    error: str | None
    fetched_at: str | None


class Manifest:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    dataset TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    status TEXT NOT NULL,
                    row_count INTEGER,
                    file_path TEXT,
                    error TEXT,
                    fetched_at TEXT
                )
                """
            )
            conn.commit()

    @staticmethod
    def make_job_id(
        dataset: str, scope_key: str, period_start: str, period_end: str
    ) -> str:
        return f"{dataset}|{scope_key}|{period_start}|{period_end}"

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return JobRecord(**dict(row))

    def should_skip(self, job_id: str, resume: bool) -> bool:
        if not resume:
            return False
        record = self.get(job_id)
        return record is not None and record.status == "success"

    def upsert(
        self,
        *,
        job_id: str,
        dataset: str,
        scope_key: str,
        period_start: str,
        period_end: str,
        status: JobStatus,
        row_count: int | None = None,
        file_path: str | None = None,
        error: str | None = None,
    ) -> None:
        fetched_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, dataset, scope_key, period_start, period_end,
                    status, row_count, file_path, error, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    row_count=excluded.row_count,
                    file_path=excluded.file_path,
                    error=excluded.error,
                    fetched_at=excluded.fetched_at
                """,
                (
                    job_id,
                    dataset,
                    scope_key,
                    period_start,
                    period_end,
                    status,
                    row_count,
                    file_path,
                    error,
                    fetched_at,
                ),
            )
            conn.commit()

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        dataset: str | None = None,
    ) -> list[JobRecord]:
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list[str] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        query += " ORDER BY fetched_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [JobRecord(**dict(row)) for row in rows]

    def summary(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
            ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    def gaps_report(self) -> dict:
        """Summarize skipped and failed jobs for visibility into no-data warnings."""
        with self._connect() as conn:
            skipped = conn.execute(
                "SELECT dataset, scope_key, error FROM jobs WHERE status='skipped'"
            ).fetchall()
            failed = conn.execute(
                "SELECT dataset, scope_key, error FROM jobs WHERE status='failed'"
            ).fetchall()

        from collections import Counter, defaultdict

        skipped_by_dataset: Counter[str] = Counter()
        skipped_by_scope: dict[str, set[str]] = defaultdict(set)
        for row in skipped:
            skipped_by_dataset[row["dataset"]] += 1
            skipped_by_scope[row["dataset"]].add(row["scope_key"])

        failed_list = [
            {"dataset": r["dataset"], "scope_key": r["scope_key"], "error": r["error"]}
            for r in failed
        ]

        # Full-year skips (zone-level) vs partial (monthly border)
        full_year_gaps: dict[str, list[str]] = defaultdict(list)
        partial_gaps: dict[str, list[str]] = defaultdict(list)
        for row in skipped:
            ds, scope = row["dataset"], row["scope_key"]
            # Count how many months skipped for this scope
            pass

        for ds, scopes in skipped_by_scope.items():
            with self._connect() as conn:
                for scope in scopes:
                    cnt = conn.execute(
                        "SELECT COUNT(*) FROM jobs WHERE status='skipped' AND dataset=? AND scope_key=?",
                        (ds, scope),
                    ).fetchone()[0]
                    if cnt >= 12 or ">" not in scope:
                        full_year_gaps[ds].append(scope)
                    elif cnt >= 1:
                        partial_gaps[ds].append(f"{scope} ({cnt} months)")

        return {
            "summary": self.summary(),
            "skipped_by_dataset": dict(skipped_by_dataset),
            "full_year_gaps": {k: sorted(v) for k, v in full_year_gaps.items()},
            "partial_gaps_sample": {
                k: sorted(set(v))[:15] for k, v in partial_gaps.items()
            },
            "failed": failed_list,
        }
