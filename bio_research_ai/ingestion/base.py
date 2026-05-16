from __future__ import annotations

from typing import Protocol

from bio_research_ai.models import IngestionRecord


class IngestionSource(Protocol):
    def ingest(self, query: str, disease: str | None = None, limit: int = 25) -> list[IngestionRecord]:
        """Return normalized records for a query."""
