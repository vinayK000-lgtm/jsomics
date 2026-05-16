from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from bio_research_ai.models import IngestionRecord


class SQLiteResearchRepository:
    """SQLite-backed evidence repository for local deployments and pilots."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add_many(self, records: list[IngestionRecord]) -> None:
        with closing(self._connect()) as connection:
            connection.executemany(
                """
                INSERT INTO evidence_records (
                    dataset, record_id, disease, title, text, source_url, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, record_id) DO UPDATE SET
                    disease=excluded.disease,
                    title=excluded.title,
                    text=excluded.text,
                    source_url=excluded.source_url,
                    metadata=excluded.metadata
                """,
                [
                    (
                        record.dataset,
                        record.record_id,
                        record.disease,
                        record.title,
                        record.text,
                        record.source_url,
                        json.dumps(record.metadata, sort_keys=True),
                    )
                    for record in records
                ],
            )
            connection.commit()

    def all(self) -> list[IngestionRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT dataset, record_id, disease, title, text, source_url, metadata
                FROM evidence_records
                ORDER BY id
                """
            ).fetchall()
        return [row_to_record(row) for row in rows]

    def search_text(self, query: str, limit: int = 25) -> list[IngestionRecord]:
        terms = [term.lower() for term in query.split() if len(term) > 2]
        if not terms:
            return []
        records = self.all()
        scored: list[tuple[int, IngestionRecord]] = []
        for record in records:
            haystack = f"{record.title} {record.text}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    disease TEXT,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source_url TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(dataset, record_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS evidence_records_text_idx
                ON evidence_records(dataset, disease, title)
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def row_to_record(row: tuple[object, ...]) -> IngestionRecord:
    dataset, record_id, disease, title, text, source_url, metadata = row
    return IngestionRecord(
        dataset=str(dataset),
        record_id=str(record_id),
        disease=str(disease) if disease is not None else None,
        title=str(title),
        text=str(text),
        source_url=str(source_url) if source_url is not None else None,
        metadata=json.loads(str(metadata or "{}")),
    )
