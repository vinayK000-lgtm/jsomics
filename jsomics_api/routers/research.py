from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from bio_research_ai.api.schemas import ResearchRequest, ResearchResponse
from bio_research_ai.models import ResearchQuery
from bio_research_ai.agents.orchestrator import ResearchOrchestrator
from bio_research_ai.storage import InMemoryVectorStore
from bio_research_ai.storage.repository import ResearchRepository

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings
from jsomics_api.middleware.rate_limit import enforce_daily_rate_limit
from jsomics_api.services.cache import get_cached, set_cached

router = APIRouter()
logger = logging.getLogger(__name__)


def _evidence_to_response(e):
    return {"source": e.source, "source_id": e.source_id, "title": e.title,
            "url": e.url, "year": e.year, "quality": e.quality}

def _triple_to_response(t):
    return {"subject": t.subject, "predicate": t.predicate, "object": t.object,
            "evidence": [_evidence_to_response(e) for e in t.evidence], "confidence": t.confidence}


@router.post("/research", response_model=ResearchResponse)
async def research(
    body: ResearchRequest,
    request: Request,
    response: Response,
    user: AuthUser = Depends(get_current_user),
):
    start = time.time()
    rate_headers = enforce_daily_rate_limit(user)

    orchestrator: ResearchOrchestrator = request.app.state.orchestrator
    cache_enabled = not body.inline_evidence

    if body.inline_evidence:
        from bio_research_ai.models import IngestionRecord
        inline_records = [
            IngestionRecord(dataset=item.source, record_id=item.source_id,
                           disease=body.disease, title=item.title, text=item.text,
                           source_url=item.url,
                           metadata={"year": item.year} if item.year else {})
            for item in body.inline_evidence
        ]
        repo = ResearchRepository()
        repo.add_many(orchestrator.repository.all() + inline_records)
        vs = InMemoryVectorStore()
        vs.add_many(repo.all())
        orchestrator = ResearchOrchestrator(repository=repo, vector_store=vs)

    if cache_enabled:
        cached = await get_cached(
            body.query,
            body.disease,
            str(body.mode),
            str(body.evidence_level),
            body.max_results,
        )
        if cached:
            try:
                cached["provenance"] = cached.get("provenance") or {}
                cached["provenance"]["from_cache"] = True
                cached["provenance"]["took_ms"] = int((time.time() - start) * 1000)
                result = ResearchResponse.model_validate(cached)
                _log_query(user.id, body, len(result.evidence))
                for header, value in rate_headers.items():
                    response.headers[header] = value
                return result
            except Exception:
                logger.warning("Ignoring invalid cached research response", exc_info=True)

    try:
        report = orchestrator.research(ResearchQuery(
            query=body.query, disease=body.disease,
            mode=body.mode, evidence_level=body.evidence_level,
            max_results=body.max_results,
        ))
    except Exception as exc:
        logger.exception("Research engine failed")
        detail = "Research engine error"
        if settings.ENV != "production":
            detail = f"{detail}: {exc}"
        raise HTTPException(status_code=500, detail=detail)

    took_ms = int((time.time() - start) * 1000)
    _log_query(user.id, body, len(report.evidence))
    for header, value in rate_headers.items():
        response.headers[header] = value

    result = ResearchResponse(
        query=report.query.query, disease=report.query.disease,
        agents_invoked=report.agents_invoked,
        executive_summary=report.executive_summary,
        confidence_overall=report.confidence_overall,
        answer=report.answer, confidence=report.confidence,
        biomarkers=[{"marker_id": b.marker_id, "name": b.name, "marker_type": b.marker_type,
                     "direction": b.direction, "score": b.score, "confidence": b.confidence,
                     "evidence": [_evidence_to_response(e) for e in b.evidence]}
                    for b in report.biomarkers],
        pathways=[{"pathway_id": p.pathway_id, "name": p.name, "score": p.score,
                   "confidence": p.confidence, "source": p.source,
                   "evidence": [_evidence_to_response(e) for e in p.evidence]}
                  for p in report.pathways],
        drug_targets=[{"gene": t.gene, "protein": t.protein, "target_class": t.target_class,
                       "genetic_score": t.genetic_score, "biological_score": t.biological_score,
                       "druggability_score": t.druggability_score, "clinical_score": t.clinical_score,
                       "total_score": t.total_score, "rationale": t.rationale,
                       "existing_drugs": [{"name": d.name, "mechanism": d.mechanism,
                                           "stage": d.stage, "indication": d.indication}
                                          for d in t.existing_drugs],
                       "combination_partners": t.combination_partners,
                       "safety_concerns": t.safety_concerns, "uniprot_id": t.uniprot_id,
                       "pdb_structures": t.pdb_structures}
                      for t in report.drug_targets],
        literature_findings=[{"finding": lf.finding, "genes": lf.genes,
                               "diseases": lf.diseases, "drugs": lf.drugs,
                               "pathways": lf.pathways,
                               "relationships": [_triple_to_response(tr) for tr in lf.relationships],
                               "evidence_grade": lf.evidence_grade, "consensus": lf.consensus,
                               "supporting_evidence": [_evidence_to_response(e) for e in lf.supporting_evidence]}
                              for lf in report.literature_findings],
        knowledge_graph_triples=[_triple_to_response(tr) for tr in report.knowledge_graph_triples],
        evidence=[_evidence_to_response(e) for e in report.evidence],
        limitations=report.limitations, caveats=report.caveats,
        cross_agent_insights=report.cross_agent_insights,
        unified_references=report.unified_references,
        suggested_next_queries=report.suggested_next_queries,
        research_use_only=report.research_use_only,
        disclaimer=report.disclaimer,
        provenance={"generated_by": settings.APP_NAME, "environment": settings.ENV,
                    "evidence_records": len(report.evidence),
                    "sources": sorted({e.source for e in report.evidence}),
                    "references": report.unified_references,
                    "data_path": None, "took_ms": took_ms, "from_cache": False},
    )
    if cache_enabled:
        await set_cached(
            body.query,
            body.disease,
            str(body.mode),
            str(body.evidence_level),
            body.max_results,
            result.model_dump(mode="json"),
        )
    return result


def _log_query(user_id, body, count):
    from jsomics_api.database import supabase
    if not supabase:
        return
    try:
        supabase.table("query_log").insert({
            "user_id": user_id, "query": body.query,
            "modalities": [body.mode], "result_count": count,
        }).execute()
    except Exception:
        pass
