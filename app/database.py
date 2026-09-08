from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class JobRecord:
    id: str
    title: str
    original_filename: str
    status: str
    language_code: str
    identify_language: bool
    speaker_labels: bool
    s3_media_key: str
    s3_output_key: str
    media_format: str
    media_content_type: str
    size_bytes: int
    transcribe_job_name: str
    transcript_text: str
    transcript_json: str
    segments_json: str
    failure_reason: str
    created_at: str
    updated_at: str
    completed_at: str

    @property
    def segments(self) -> list[dict[str, Any]]:
        if not self.segments_json:
            return []
        return json.loads(self.segments_json)


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    language_code TEXT NOT NULL,
                    identify_language INTEGER NOT NULL,
                    speaker_labels INTEGER NOT NULL,
                    s3_media_key TEXT NOT NULL,
                    s3_output_key TEXT NOT NULL,
                    media_format TEXT NOT NULL,
                    media_content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    transcribe_job_name TEXT NOT NULL UNIQUE,
                    transcript_text TEXT NOT NULL DEFAULT '',
                    transcript_json TEXT NOT NULL DEFAULT '',
                    segments_json TEXT NOT NULL DEFAULT '[]',
                    failure_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)")

    def create(self, **values: Any) -> JobRecord:
        timestamp = now_iso()
        values = {
            **values,
            "transcript_text": "",
            "transcript_json": "",
            "segments_json": "[]",
            "failure_reason": "",
            "created_at": timestamp,
            "updated_at": timestamp,
            "completed_at": "",
        }
        fields = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO jobs ({fields}) VALUES ({placeholders})",
                list(values.values()),
            )
        record = self.get(values["id"])
        if record is None:
            raise RuntimeError("No se pudo crear el trabajo.")
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return JobRecord(**dict(row)) if row else None

    def by_transcribe_name(self, name: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE transcribe_job_name = ?", (name,)
            ).fetchone()
        return JobRecord(**dict(row)) if row else None

    def list_recent(self, limit: int = 60) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [JobRecord(**dict(row)) for row in rows]

    def update(self, job_id: str, **values: Any) -> JobRecord:
        values["updated_at"] = now_iso()
        if not values:
            record = self.get(job_id)
            if record is None:
                raise KeyError(job_id)
            return record
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                [*values.values(), job_id],
            )
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        return record

