"""
JSOMICS — Ingest router

POST /v1/ingest/pubmed   → fetch live PubMed articles into the evidence store
POST /v1/ingest/kegg     → fetch KEGG pathway entries

Only accessible to researcher/lab plan users.
Calls the exact same ingestion clients that bio_research_ai ships with.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from bio_research_ai.ingestion.pubmed import PubMedClient
from bio_research_ai.ingestion.kegg import KEGGClient

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings

router = APIRouter()


class PubMedIngestRequest(BaseModel):
    query: str = Field(min_length=3, description="PubMed search query")
    disease: str | None = None
    limit: int = Field(default=25, ge=1, le=100)


class KEGGIngestRequest(BaseModel):
    disease_keyword: str = Field(min_length=2, description="KEGG disease keyword")
    limit: int = Field(default=20, ge=1, le=50)


def _require_paid(user: AuthUser):
    if user.plan not in ("researcher", "lab"):
        raise HTTPException(
            status_code=403,
            detail="Ingestion requires Researcher or Lab plan. Upgrade at jsomics.com/#pricing",
        )


@router.post("/pubmed")
async def ingest_pubmed(
    body: PubMedIngestRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Fetch PubMed articles and add them to the live evidence store."""
    _require_paid(user)

    client = PubMedClient(
        email=settings.NCBI_EMAIL,
        api_key=settings.NCBI_API_KEY,
    )
    try:
        records = client.ingest(query=body.query, disease=body.disease, limit=body.limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PubMed fetch failed: {exc}")

    orchestrator = request.app.state.orchestrator
    orchestrator.repository.add_many(records)
    orchestrator.vector_store.add_many(records)

    return {
        "ingested": len(records),
        "query": body.query,
        "disease": body.disease,
        "records": [
            {"id": r.record_id, "title": r.title[:80]}
            for r in records[:5]
        ],
        "message": f"Added {len(records)} PubMed records to the evidence store.",
    }


@router.post("/kegg")
async def ingest_kegg(
    body: KEGGIngestRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Fetch KEGG pathway entries and add them to the live evidence store."""
    _require_paid(user)

    client = KEGGClient()
    try:
        records = client.ingest(keyword=body.disease_keyword, limit=body.limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"KEGG fetch failed: {exc}")

    orchestrator = request.app.state.orchestrator
    orchestrator.repository.add_many(records)
    orchestrator.vector_store.add_many(records)

    return {
        "ingested": len(records),
        "keyword": body.disease_keyword,
        "message": f"Added {len(records)} KEGG pathway records to the evidence store.",
    }


@router.get("/status")
async def ingest_status(
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Return the current evidence store record count."""
    orchestrator = request.app.state.orchestrator
    records = orchestrator.repository.all()
    from collections import Counter
    by_source = Counter(r.dataset for r in records)
    return {
        "total_records": len(records),
        "by_source": dict(by_source),
        "user_plan": user.plan,
    }
