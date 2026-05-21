from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

from bio_research_ai.ingestion.kegg import KeggClient
from bio_research_ai.ingestion.pubmed import PubMedClient
from bio_research_ai.models import IngestionRecord
from jsomics_api.config import settings


@dataclass
class LiveEvidenceBundle:
    records: list[IngestionRecord] = field(default_factory=list)
    agent_status: dict[str, str] = field(default_factory=dict)
    agent_timings_ms: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def build_search_query(query: str, disease: str | None = None) -> str:
    query = query.strip()
    disease = (disease or "").strip()
    if disease and disease.lower() not in query.lower():
        return f"{query} {disease}"
    return query


async def fetch_live_evidence(query: str, disease: str | None, max_results: int) -> list[IngestionRecord]:
    bundle = await fetch_live_evidence_bundle(query=query, disease=disease, max_results=max_results)
    return bundle.records


async def fetch_live_evidence_bundle(
    query: str,
    disease: str | None,
    max_results: int,
    omics: list[str] | None = None,
    search_depth: str = "quick",
) -> LiveEvidenceBundle:
    """Fetch multiomics evidence in parallel, with source-level timeouts and partial results.

    No external record is stored in Supabase here; this function is designed for temporary
    Vercel KV/Redis caching and fast, cache-first UI jobs.
    """
    omics = [x.lower() for x in (omics or ["literature", "biomarkers", "pathways"])]
    search_query = build_search_query(query, disease)
    depth_factor = {"quick": 1, "deep": 2, "systematic": 3}.get(search_depth, 1)
    pubmed_limit = max(5, min(max_results * depth_factor * 2, 60))
    kegg_limit = max(3, min(max_results * depth_factor, 25))
    timeout = max(4.0, float(getattr(settings, "SOURCE_TIMEOUT_SECONDS", 10)))

    jobs: list[tuple[str, Callable[[], list[IngestionRecord]]]] = []
    if any(x in omics for x in ["literature", "biomarkers", "transcriptomics", "genomics"]):
        jobs.append(("pubmed", lambda: _fetch_pubmed(search_query, disease, pubmed_limit)))
    if any(x in omics for x in ["pathways", "genomics", "proteomics"]):
        jobs.append(("kegg", lambda: _fetch_kegg(search_query, disease, kegg_limit)))

    bundle = LiveEvidenceBundle(agent_status={name: "running" for name, _ in jobs})
    results = await asyncio.gather(*[_run_source(name, fn, timeout) for name, fn in jobs], return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            bundle.errors.append(str(result))
            continue
        name, records, status, took_ms, error = result
        bundle.agent_status[name] = status
        bundle.agent_timings_ms[name] = took_ms
        if error:
            bundle.errors.append(error)
        bundle.records.extend(records)
    bundle.records = _dedupe(bundle.records)[: max_results * max(depth_factor, 1) * 3]
    return bundle


async def _run_source(name: str, fn: Callable[[], list[IngestionRecord]], timeout: float):
    started = time.perf_counter()
    try:
        records = await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
        return name, records, "done", int((time.perf_counter() - started) * 1000), None
    except asyncio.TimeoutError:
        return name, [], "timeout", int((time.perf_counter() - started) * 1000), f"{name} timed out after {timeout:g}s"
    except Exception as exc:
        return name, [], "error", int((time.perf_counter() - started) * 1000), f"{name} failed: {exc}"


def _fetch_pubmed(query: str, disease: str | None, limit: int) -> list[IngestionRecord]:
    client = PubMedClient(email=settings.NCBI_EMAIL, api_key=settings.NCBI_API_KEY, tool="jsomics")
    return client.ingest(query=query, disease=disease, limit=limit)


def _fetch_kegg(query: str, disease: str | None, limit: int) -> list[IngestionRecord]:
    client = KeggClient()
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
