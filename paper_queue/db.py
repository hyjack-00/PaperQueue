from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text TEXT NOT NULL,
    notebook_id TEXT NOT NULL,
    notebook_title TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    paper_title TEXT,
    output_path TEXT,
    result_summary TEXT,
    error_message TEXT,
    worker_pid INTEGER,
    artifact_dir TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


class JobStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with connect(db_path) as conn:
            conn.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "worker_pid" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN worker_pid INTEGER")
            if "artifact_dir" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN artifact_dir TEXT")

    def _conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def create_job(self, *, input_text: str, notebook_id: str, notebook_title: str, created_at: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO jobs (
                    input_text, notebook_id, notebook_title, status, stage,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', 'queued', ?, ?)
                """,
                (input_text, notebook_id, notebook_title, created_at, created_at),
            )
            return int(cur.lastrowid)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT jobs.*, (
                    SELECT message FROM job_logs
                    WHERE job_id = jobs.id
                    ORDER BY id DESC LIMIT 1
                ) AS latest_log
                FROM jobs
                ORDER BY jobs.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def running_jobs(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'running'
                ORDER BY id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_recent_logs(self, job_id: int, limit: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT created_at, level, stage, message
                FROM job_logs
                WHERE job_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (job_id, limit),
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def get_log_text(self, job_id: int) -> str:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT created_at, level, stage, message
                FROM job_logs
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
            lines = [f"{row['created_at']} [{row['level']}] ({row['stage']}) {row['message']}" for row in rows]
            return "\n".join(lines)

    def append_log(self, *, job_id: int, created_at: str, level: str, stage: str, message: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO job_logs (job_id, created_at, level, stage, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, created_at, level, stage, message),
            )

    def claim_next_job(self, now: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    stage = 'starting',
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?,
                    attempt_count = attempt_count + 1
                WHERE id = ?
                """,
                (now, now, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
            return dict(claimed) if claimed else None

    def claim_job_by_id(self, job_id: int, now: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row["status"] != "queued":
                return None
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    stage = 'starting',
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?,
                    attempt_count = attempt_count + 1
                WHERE id = ?
                """,
                (now, now, job_id),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(claimed) if claimed else None

    def set_status(
        self,
        job_id: int,
        *,
        status: str,
        stage: str,
        updated_at: str,
        error_message: str | None = None,
        paper_title: str | None = None,
        output_path: str | None = None,
        result_summary: str | None = None,
        finished_at: str | None = None,
        worker_pid: int | None = None,
        artifact_dir: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    stage = ?,
                    updated_at = ?,
                    error_message = COALESCE(?, error_message),
                    paper_title = COALESCE(?, paper_title),
                    output_path = COALESCE(?, output_path),
                    result_summary = COALESCE(?, result_summary),
                    worker_pid = COALESCE(?, worker_pid),
                    artifact_dir = COALESCE(?, artifact_dir),
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    status,
                    stage,
                    updated_at,
                    error_message,
                    paper_title,
                    output_path,
                    result_summary,
                    worker_pid,
                    artifact_dir,
                    finished_at,
                    job_id,
                ),
            )

    def clear_worker_pid(self, job_id: int, updated_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET worker_pid = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (updated_at, job_id),
            )

    def attach_worker_pid(self, job_id: int, worker_pid: int, updated_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET worker_pid = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (worker_pid, updated_at, job_id),
            )

    def set_notebook(self, job_id: int, notebook_id: str, notebook_title: str, updated_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET notebook_id = ?,
                    notebook_title = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (notebook_id, notebook_title, updated_at, job_id),
            )

    def requeue_job(self, job_id: int, now: str, *, error_message: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    stage = 'queued',
                    updated_at = ?,
                    error_message = ?,
                    worker_pid = NULL
                WHERE id = ?
                """,
                (now, error_message, job_id),
            )

    def requeue_blocked_git(self, now: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    stage = 'queued',
                    updated_at = ?,
                    error_message = NULL
                WHERE status = 'blocked_git'
                """,
                (now,),
            )
            return int(cur.rowcount)

    def requeue_waiting_auth(self, now: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = 'queued', stage = 'queued', updated_at = ?, error_message = NULL
                WHERE status = 'waiting_auth'
                """,
                (now,),
            )
            return int(cur.rowcount)

    def retry_job(self, job_id: int, now: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row["status"] != "failed":
                return False
            conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    stage = 'queued',
                    updated_at = ?,
                    error_message = NULL,
                    finished_at = NULL,
                    result_summary = NULL,
                    output_path = NULL,
                    artifact_dir = NULL
                WHERE id = ?
                """,
                (now, job_id),
            )
            return True

    def delete_job(self, job_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            payload = dict(row)
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return payload

    def system_snapshot(self, recent_log_lines: int) -> list[dict[str, Any]]:
        jobs = self.list_jobs()
        for job in jobs:
            job["recent_logs"] = self.get_recent_logs(job["id"], recent_log_lines)
        return jobs
