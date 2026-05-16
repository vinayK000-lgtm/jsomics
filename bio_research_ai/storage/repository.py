from __future__ import annotations

import json
from pathlib import Path

from bio_research_ai.models import IngestionRecord


class ResearchRepository:
    """Small local repository used before replacing persistence with Postgres."""

    def __init__(self) -> None:
        self._records: list[IngestionRecord] = []

    def add_many(self, records: list[IngestionRecord]) -> None:
        by_key = {
            (record.dataset, record.record_id): index
            for index, record in enumerate(self._records)
        }
        for record in records:
            key = (record.dataset, record.record_id)
            if key in by_key:
                self._records[by_key[key]] = record
                continue
            by_key[key] = len(self._records)
            self._records.append(record)

    def all(self) -> list[IngestionRecord]:
        return list(self._records)

    def search_text(self, query: str, limit: int = 25) -> list[IngestionRecord]:
        terms = {term.lower() for term in query.split() if len(term) > 2}
        scored: list[tuple[int, IngestionRecord]] = []
        for record in self._records:
            haystack = f"{record.title} {record.text}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    @classmethod
    def from_jsonl(cls, path: Path) -> "ResearchRepository":
        repo = cls()
        if not path.exists():
            return repo
        records: list[IngestionRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            records.append(IngestionRecord(**payload))
        repo.add_many(records)
        return repo

    def to_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in self._records:
                handle.write(json.dumps(_record_to_dict(record), sort_keys=True) + "\n")


def _record_to_dict(record: IngestionRecord) -> dict[str, object]:
    return {
        "dataset": record.dataset,
        "record_id": record.record_id,
        "disease": record.disease,
        "title": record.title,
        "text": record.text,
        "source_url": record.source_url,
        "metadata": record.metadata,
    }
