"""
JSOMICS — Research router

POST /v1/research

This is the heart of the merge:
  - Auth + rate limiting from JSOMICS
  - Full research logic from bio_research_ai's ResearchOrchestrator
  - Usage logging to Supabase query_log

The ResearchOrchestrator lives in app.state.orchestrator (created at startup).
For inline_evidence requests it forks a new orchestrator with the extra records.
"""
from __future__ import annotations

import time
from fastapi import APIRouter, Depends, HTTPException, Request

from bio_research_ai.agents.orchestrator import ResearchOrchestrator
from bio_research_ai.api.schemas import ResearchRequest, ResearchResponse
from bio_research_ai.api.main import (
    evidence_input_to_record,
    evidence_to_response,
    knowledge_triple_to_response,
    provenance_to_response,
)
from bio_research_ai.models import ResearchQuery
from bio_research_ai.storage import InMemoryVectorStore
from bio_research_ai.storage.repository import ResearchRepository

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings
from jsomics_api.database import supabase

router = APIRouter()


@router.post("/research", response_model=ResearchResponse)
async def research(
    body: ResearchRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Multi-agent biomedical research endpoint.

    Runs through the ResearchOrchestrator which dispatches to:
    - LiteratureMiningAgent   (PubMed text + knowledge graph triples)
    - BiomarkerIdentifierAgent (gene symbol NER + direction inference)
    - PathwayAnalystAgent      (KEGG pathway hits)
    - DrugTargetDiscoveryAgent (multi-dimensional target scoring)

    Returns a fully structured ResearchReport with evidence provenance,
    confidence scores, guardrails, and suggested follow-up queries.
    """
    start = time.time()

    # Inject user into request.state so rate limit middleware can count it
    request.state.user_id = user.id
    request.state.plan    = user.plan

    # Get base orchestrator from app state (built once at startup)
    orchestrator: ResearchOrchestrator = request.app.state.orchestrator

    # If caller supplied inline evidence, fork a temporary orchestrator
    if body.inline_evidence:
        inline_records = [
            evidence_input_to_record(item, disease=body.disease)
            for item in body.inline_evidence
        ]
        forked_repo = ResearchRepository()
        forked_repo.add_many(orchestrator.repository.all() + inline_records)
        forked_vs = InMemoryVectorStore()
        forked_vs.add_many(forked_repo.all())
        orchestrator = ResearchOrchestrator(
            repository=forked_repo,
            vector_store=forked_vs,
        )

    # Run the research
    try:
        report = orchestrator.research(
            ResearchQuery(
                query=body.query,
                disease=body.disease,
                mode=body.mode,
                evidence_level=body.evidence_level,
                max_results=body.max_results,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Research engine error: {exc}")

    took_ms = int((time.time() - start) * 1000)

    # Log to Supabase (non-blocking, fail-safe)
    _log_query(user.id, body, len(report.evidence))

    # Build response (matching bio_research_ai schema exactly)
    return ResearchResponse(
        query=report.query.query,
        disease=report.query.disease,
        agents_invoked=report.agents_invoked,
        executive_summary=report.executive_summary,
        confidence_overall=report.confidence_overall,
        answer=report.answer,
        confidence=report.confidence,
        biomarkers=[
            {
                "marker_id": b.marker_id,
                "name": b.name,
                "marker_type": b.marker_type,
                "direction": b.direction,
                "score": b.score,
                "confidence": b.confidence,
                "evidence": [evidence_to_response(e) for e in b.evidence],
            }
            for b in report.biomarkers
        ],
        pathways=[
            {
                "pathway_id": p.pathway_id,
                "name": p.name,
                "score": p.score,
                "confidence": p.confidence,
                "source": p.source,
                "evidence": [evidence_to_response(e) for e in p.evidence],
            }
            for p in report.pathways
        ],
        drug_targets=[
            {
                "gene": t.gene,
                "protein": t.protein,
                "target_class": t.target_class,
                "genetic_score": t.genetic_score,
                "biological_score": t.biological_score,
                "druggability_score": t.druggability_score,
                "clinical_score": t.clinical_score,
                "total_score": t.total_score,
                "rationale": t.rationale,
                "existing_drugs": [
                    {"name": d.name, "mechanism": d.mechanism, "stage": d.stage, "indication": d.indication}
                    for d in t.existing_drugs
                ],
                "combination_partners": t.combination_partners,
                "safety_concerns": t.safety_concerns,
                "uniprot_id": t.uniprot_id,
                "pdb_structures": t.pdb_structures,
            }
            for t in report.drug_targets
        ],
        literature_findings=[
            {
                "finding": lf.finding,
                "genes": lf.genes,
                "diseases": lf.diseases,
                "drugs": lf.drugs,
                "pathways": lf.pathways,
                "relationships": [knowledge_triple_to_response(tr) for tr in lf.relationships],
                "evidence_grade": lf.evidence_grade,
                "consensus": lf.consensus,
                "supporting_evidence": [evidence_to_response(e) for e in lf.supporting_evidence],
            }
            for lf in report.literature_findings
        ],
        knowledge_graph_triples=[
            knowledge_triple_to_response(tr) for tr in report.knowledge_graph_triples
        ],
        evidence=[evidence_to_response(e) for e in report.evidence],
        limitations=report.limitations,
        caveats=report.caveats,
        cross_agent_insights=report.cross_agent_insights,
        unified_references=report.unified_references,
        suggested_next_queries=report.suggested_next_queries,
        research_use_only=report.research_use_only,
        disclaimer=report.disclaimer,
        provenance={
            **provenance_to_response(report, _make_bio_settings()),
            "took_ms": took_ms,
        },
    )


def _log_query(user_id: str, body: ResearchRequest, evidence_count: int) -> None:
    """Write to Supabase query_log for rate limiting + analytics. Never blocks the response."""
    if not supabase:
        return
    try:
        supabase.table("query_log").insert({
            "user_id": user_id,
            "query": body.query,
            "modalities": [body.mode],
            "result_count": evidence_count,
        }).execute()
    except Exception:
        pass


def _make_bio_settings():
    """Construct a bio_research_ai Settings-compatible object from JSOMICS settings."""
    from bio_research_ai.config import Settings as BioSettings
    return BioSettings(
        app_name=settings.APP_NAME,
        environment=settings.ENV,
        ncbi_email=settings.NCBI_EMAIL,
        ncbi_api_key=settings.NCBI_API_KEY,
        database_url=settings.SUPABASE_DATABASE_URL,
        sqlite_path=settings.SQLITE_PATH,
    )
