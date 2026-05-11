"""
SQLite-backed persistence layer for tasks and runs.
All state lives in a single `agent_manager.db` file.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .models import Run, Task


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    user_message    TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    run_id          TEXT,
    error           TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    user_message    TEXT NOT NULL,
    model           TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    response        TEXT,
    error           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_runs_agent     ON runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_runs_task      ON runs(task_id);
"""


class Store:
    """Thin SQLite wrapper. Thread-safe via check_same_thread=False + WAL mode."""

    def __init__(self, db_path: str | Path = "agent_manager.db"):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions manually
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ Tasks

    def upsert_task(self, task: Task) -> None:
        self._conn.execute(
            """
            INSERT INTO tasks
                (id, agent_name, user_message, priority, status,
                 created_at, started_at, completed_at, run_id, error, metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                status       = excluded.status,
                started_at   = excluded.started_at,
                completed_at = excluded.completed_at,
                run_id       = excluded.run_id,
                error        = excluded.error,
                metadata     = excluded.metadata
            """,
            (
                task.id,
                task.agent_name,
                task.user_message,
                task.priority,
                task.status,
                task.created_at,
                task.started_at,
                task.completed_at,
                task.run_id,
                task.error,
                json.dumps(task.metadata),
            ),
        )

    def get_task(self, task_id: str) -> Optional[Task]:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(
        self,
        status: Optional[str] = None,
        agent_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at ASC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def claim_pending_tasks(self, limit: int = 10) -> list[Task]:
        """Atomically claim up to `limit` pending tasks → set status=running."""
        rows = self._conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        tasks = [_row_to_task(r) for r in rows]
        if tasks:
            ids = ",".join("?" for _ in tasks)
            self._conn.execute(
                f"UPDATE tasks SET status='running' WHERE id IN ({ids})",
                [t.id for t in tasks],
            )
            for t in tasks:
                t.status = "running"
        return tasks

    # ------------------------------------------------------------------ Runs

    def insert_run(self, run: Run) -> None:
        self._conn.execute(
            """
            INSERT INTO runs
                (id, task_id, agent_name, user_message, model, status,
                 created_at, response, error, input_tokens, output_tokens,
                 duration_seconds, metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run.id,
                run.task_id,
                run.agent_name,
                run.user_message,
                run.model,
                run.status,
                run.created_at,
                run.response,
                run.error,
                run.input_tokens,
                run.output_tokens,
                run.duration_seconds,
                json.dumps(run.metadata),
            ),
        )

    def get_run(self, run_id: str) -> Optional[Run]:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(
        self,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Run]:
        clauses, params = [], []
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_run(r) for r in rows]

    def stats(self) -> dict:
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status='pending')   AS pending,
                COUNT(*) FILTER (WHERE status='running')   AS running,
                COUNT(*) FILTER (WHERE status='completed') AS completed,
                COUNT(*) FILTER (WHERE status='failed')    AS failed
            FROM tasks
            """
        ).fetchone()
        run_row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS total_runs,
                SUM(input_tokens)  AS total_input_tokens,
                SUM(output_tokens) AS total_output_tokens,
                AVG(duration_seconds) AS avg_duration
            FROM runs
            """
        ).fetchone()
        return {
            "tasks": dict(row),
            "runs": dict(run_row),
        }

    def close(self) -> None:
        self._conn.close()


# -------------------------------------------------------- helpers

def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        agent_name=row["agent_name"],
        user_message=row["user_message"],
        priority=row["priority"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        run_id=row["run_id"],
        error=row["error"],
        metadata=json.loads(row["metadata"]),
    )


def _row_to_run(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"],
        task_id=row["task_id"],
        agent_name=row["agent_name"],
        user_message=row["user_message"],
        model=row["model"],
        status=row["status"],
        created_at=row["created_at"],
        response=row["response"],
        error=row["error"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        duration_seconds=row["duration_seconds"],
        metadata=json.loads(row["metadata"]),
    )
