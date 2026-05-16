from __future__ import annotations

import json

from bio_research_ai.models import IngestionRecord


class PostgresResearchRepository:
    """Postgres-backed evidence repository for Supabase and Railway deployments."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._initialize()

    def add_many(self, records: list[IngestionRecord]) -> None:
        if not records:
            return
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO evidence_records (
                        dataset, record_id, disease, title, text, source_url, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(dataset, record_id) DO UPDATE SET
                        disease=EXCLUDED.disease,
                        title=EXCLUDED.title,
                        text=EXCLUDED.text,
                        source_url=EXCLUDED.source_url,
                        metadata=EXCLUDED.metadata,
                        updated_at=NOW()
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
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT dataset, record_id, disease, title, text, source_url, metadata
                    FROM evidence_records
                    ORDER BY id
                    """
                )
                rows = cursor.fetchall()
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
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS evidence_records (
                        id BIGSERIAL PRIMARY KEY,
                        dataset TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        disease TEXT,
                        title TEXT NOT NULL,
                        text TEXT NOT NULL,
                        source_url TEXT,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE(dataset, record_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS evidence_records_lookup_idx
                    ON evidence_records(dataset, disease, title)
                    """
                )
            connection.commit()

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "Postgres storage requires psycopg. Install with `pip install -e .[storage]`."
            ) from exc
        return psycopg.connect(self.database_url)


def row_to_record(row: tuple[object, ...]) -> IngestionRecord:
    dataset, record_id, disease, title, text, source_url, metadata = row
    if isinstance(metadata, str):
        metadata_value = json.loads(metadata or "{}")
    elif isinstance(metadata, dict):
        metadata_value = metadata
    else:
        metadata_value = {}
    return IngestionRecord(
        dataset=str(dataset),
        record_id=str(record_id),
        disease=str(disease) if disease is not None else None,
        title=str(title),
        text=str(text),
        source_url=str(source_url) if source_url is not None else None,
        metadata=metadata_value,
    )
