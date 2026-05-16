from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from bio_research_ai.models import IngestionRecord


@dataclass(frozen=True)
class VectorHit:
    record: IngestionRecord
    score: float


class InMemoryVectorStore:
    """Deterministic local vector store for development and tests.

    This is intentionally simple. Production should replace it with sentence embeddings
    and Postgres + pgvector, while preserving the same add/search calling shape.
    """

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions
        self._items: list[tuple[IngestionRecord, list[float]]] = []

    def add_many(self, records: list[IngestionRecord]) -> None:
        for record in records:
            self._items.append((record, embed_text(f"{record.title} {record.text}", self.dimensions)))

    def search(self, query: str, limit: int = 10) -> list[VectorHit]:
        query_vector = embed_text(query, self.dimensions)
        hits = [
            VectorHit(record=record, score=cosine_similarity(query_vector, vector))
            for record, vector in self._items
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return [hit for hit in hits[:limit] if hit.score > 0]


def embed_text(text: str, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9-]{2,}", text.lower())


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


PGVECTOR_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS evidence_records (
    id BIGSERIAL PRIMARY KEY,
    dataset TEXT NOT NULL,
    record_id TEXT NOT NULL,
    disease TEXT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    source_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(768),
    UNIQUE(dataset, record_id)
);

CREATE INDEX IF NOT EXISTS evidence_records_embedding_idx
ON evidence_records USING ivfflat (embedding vector_cosine_ops);
"""
