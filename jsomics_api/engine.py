"""
JSOMICS — Engine bootstrap

Builds the ResearchOrchestrator using:
  1. Supabase Postgres (via DATABASE_URL)  ← preferred in production
  2. SQLite (via SQLITE_PATH)              ← local dev fallback
  3. In-memory                             ← testing / empty start

The orchestrator is created once at startup and stored in app.state.orchestrator.
Every request reads it from there — no re-initialisation per request.
"""
from __future__ import annotations

from bio_research_ai.agents.orchestrator import ResearchOrchestrator
from bio_research_ai.storage import InMemoryVectorStore, ResearchRepository
from bio_research_ai.storage.postgres_repository import PostgresResearchRepository
from bio_research_ai.storage.sqlite_repository import SQLiteResearchRepository
from jsomics_api.config import Settings


def build_orchestrator(settings: Settings) -> ResearchOrchestrator:
    """Construct the orchestrator from the best available storage backend."""

    if settings.SUPABASE_DATABASE_URL:
        print(f"[engine] Using Postgres: {_redact(settings.SUPABASE_DATABASE_URL)}")
        repository = PostgresResearchRepository(settings.SUPABASE_DATABASE_URL)

    elif settings.SQLITE_PATH:
        print(f"[engine] Using SQLite: {settings.SQLITE_PATH}")
        repository = SQLiteResearchRepository(settings.SQLITE_PATH)

    elif settings.DATA_PATH and settings.DATA_PATH.exists():
        print(f"[engine] Loading JSONL data: {settings.DATA_PATH}")
        repository = ResearchRepository.from_jsonl(settings.DATA_PATH)

    else:
        print("[engine] No storage configured — using in-memory repository (empty until ingestion)")
        repository = ResearchRepository()

    vector_store = InMemoryVectorStore()
    vector_store.add_many(repository.all())

    return ResearchOrchestrator(
        repository=repository,
        vector_store=vector_store,
    )


def _redact(url: str) -> str:
    """Hide password in DB URL for safe logging."""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        credentials, host = rest.split("@", 1)
        user = credentials.split(":")[0]
        return f"{scheme}://{user}:***@{host}"
    return url
