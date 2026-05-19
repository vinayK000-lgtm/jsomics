from __future__ import annotations

import asyncio
from dataclasses import replace

from bio_research_ai.ingestion.kegg import KeggClient
from bio_research_ai.ingestion.pubchem import PubChemClient
from bio_research_ai.ingestion.pubmed import PubMedClient
from bio_research_ai.models import IngestionRecord
from jsomics_api.config import settings


def build_search_query(query: str, disease: str | None = None) -> str:
    query = query.strip()
    disease = (disease or "").strip()
    if disease and disease.lower() not in query.lower():
        return f"{query} {disease}"
    return query


async def fetch_live_evidence(query: str, disease: str | None, max_results: int) -> list[IngestionRecord]:
    """Fetch temporary evidence at request time. Nothing is saved to Supabase."""
    search_query = build_search_query(query, disease)
    pubmed_limit = max(5, min(max_results * 2, 30))
    kegg_limit = max(3, min(max_results, 10))
    pubchem_limit = max(1, min(max_results // 2 or 1, 5))

    tasks = [
        asyncio.to_thread(_fetch_pubmed, search_query, disease, pubmed_limit),
        asyncio.to_thread(_fetch_kegg, search_query, disease, kegg_limit),
        asyncio.to_thread(_fetch_pubchem, query, disease, pubchem_limit),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    records: list[IngestionRecord] = []
    for result in results:
        if isinstance(result, Exception):
            print(f"[live evidence] source failed: {result}")
            continue
        records.extend(result)
    return _dedupe(records)[: max_results * 3]


def _fetch_pubmed(query: str, disease: str | None, limit: int) -> list[IngestionRecord]:
    client = PubMedClient(email=settings.NCBI_EMAIL, api_key=settings.NCBI_API_KEY, tool="jsomics")
    return client.ingest(query=query, disease=disease, limit=limit)


def _fetch_kegg(query: str, disease: str | None, limit: int) -> list[IngestionRecord]:
    client = KeggClient()
    return client.ingest(query=query, disease=disease, limit=limit)


def _fetch_pubchem(query: str, disease: str | None, limit: int) -> list[IngestionRecord]:
    # PubChem is compound-centric. It may return nothing for gene-only searches such as BARC1.
    client = PubChemClient()
    return client.ingest(query=query, disease=disease, limit=limit)


def _dedupe(records: list[IngestionRecord]) -> list[IngestionRecord]:
    seen: set[tuple[str, str]] = set()
    deduped: list[IngestionRecord] = []
    for record in records:
        key = (record.dataset, record.record_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped
