from __future__ import annotations

from typing import Annotated
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bio_research_ai.agents import ResearchOrchestrator
from bio_research_ai.api.schemas import EvidenceInput, ResearchRequest, ResearchResponse
from bio_research_ai.config import Settings
from bio_research_ai.models import Evidence, IngestionRecord, ResearchQuery
from bio_research_ai.storage import (
    InMemoryVectorStore,
    PostgresResearchRepository,
    ResearchRepository,
    SQLiteResearchRepository,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    orchestrator = build_orchestrator(settings)
    web_dir = Path(__file__).resolve().parents[1] / "web"

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Evidence-grounded biomedical research agent API.",
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key"],
        )
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")
    require_api_key = api_key_dependency(settings)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/privacy", include_in_schema=False)
    def privacy() -> FileResponse:
        return FileResponse(web_dir / "privacy.html")

    @app.get("/.well-known/jsomics-action-openapi.yaml", include_in_schema=False)
    def jsomics_action_openapi() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parents[2] / "gpt" / "jsomics_action_openapi.yaml",
            media_type="text/yaml",
        )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "environment": settings.environment,
            "auth_enabled": bool(settings.api_keys),
        }

    @app.get("/ready")
    def ready() -> dict[str, object]:
        data_path = settings.sqlite_path or settings.data_path
        return {
            "status": "ready",
            "evidence_records": len(orchestrator.repository.all()),
            "data_path": str(data_path) if data_path else None,
        }

    @app.post("/v1/research", response_model=ResearchResponse)
    def research(
        request: ResearchRequest,
        _: None = Depends(require_api_key),
    ) -> ResearchResponse:
        active_orchestrator = orchestrator
        if request.inline_evidence:
            inline_records = [
                evidence_input_to_record(item, disease=request.disease)
                for item in request.inline_evidence
            ]
            active_orchestrator = ResearchOrchestrator.from_records(
                orchestrator.repository.all() + inline_records
            )

        report = active_orchestrator.research(
            ResearchQuery(
                query=request.query,
                disease=request.disease,
                mode=request.mode,
                evidence_level=request.evidence_level,
                max_results=request.max_results,
            )
        )
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
                    "marker_id": item.marker_id,
                    "name": item.name,
                    "marker_type": item.marker_type,
                    "direction": item.direction,
                    "score": item.score,
                    "confidence": item.confidence,
                    "evidence": [evidence_to_response(evidence) for evidence in item.evidence],
                }
                for item in report.biomarkers
            ],
            pathways=[
                {
                    "pathway_id": item.pathway_id,
                    "name": item.name,
                    "score": item.score,
                    "confidence": item.confidence,
                    "source": item.source,
                    "evidence": [evidence_to_response(evidence) for evidence in item.evidence],
                }
                for item in report.pathways
            ],
            drug_targets=[
                {
                    "gene": item.gene,
                    "protein": item.protein,
                    "target_class": item.target_class,
                    "genetic_score": item.genetic_score,
                    "biological_score": item.biological_score,
                    "druggability_score": item.druggability_score,
                    "clinical_score": item.clinical_score,
                    "total_score": item.total_score,
                    "rationale": item.rationale,
                    "existing_drugs": [
                        {
                            "name": drug.name,
                            "mechanism": drug.mechanism,
                            "stage": drug.stage,
                            "indication": drug.indication,
                        }
                        for drug in item.existing_drugs
                    ],
                    "combination_partners": item.combination_partners,
                    "safety_concerns": item.safety_concerns,
                    "uniprot_id": item.uniprot_id,
                    "pdb_structures": item.pdb_structures,
                }
                for item in report.drug_targets
            ],
            literature_findings=[
                {
                    "finding": item.finding,
                    "genes": item.genes,
                    "diseases": item.diseases,
                    "drugs": item.drugs,
                    "pathways": item.pathways,
                    "relationships": [
                        knowledge_triple_to_response(triple) for triple in item.relationships
                    ],
                    "evidence_grade": item.evidence_grade,
                    "consensus": item.consensus,
                    "supporting_evidence": [
                        evidence_to_response(evidence) for evidence in item.supporting_evidence
                    ],
                }
                for item in report.literature_findings
            ],
            knowledge_graph_triples=[
                knowledge_triple_to_response(item) for item in report.knowledge_graph_triples
            ],
            evidence=[evidence_to_response(item) for item in report.evidence],
            limitations=report.limitations,
            caveats=report.caveats,
            cross_agent_insights=report.cross_agent_insights,
            unified_references=report.unified_references,
            suggested_next_queries=report.suggested_next_queries,
            research_use_only=report.research_use_only,
            disclaimer=report.disclaimer,
            provenance=provenance_to_response(report, settings),
        )

    return app


def api_key_dependency(settings: Settings):
    def require_api_key(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> None:
        if authorization and settings.supabase_jwt_secret:
            validate_supabase_bearer_token(authorization, settings.supabase_jwt_secret)
            return
        if not settings.api_keys:
            return
        if x_api_key in settings.api_keys:
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
        )

    return require_api_key


def validate_supabase_bearer_token(authorization: str, jwt_secret: str) -> None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header.",
        )
    try:
        import jwt

        jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase JWT auth requires PyJWT.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Supabase token.",
        ) from exc


def build_orchestrator(settings: Settings | Path | None) -> ResearchOrchestrator:
    if isinstance(settings, Path) or settings is None:
        settings = Settings(data_path=settings)

    if settings.database_url:
        repository = PostgresResearchRepository(settings.database_url)
    elif settings.sqlite_path:
        repository = SQLiteResearchRepository(settings.sqlite_path)
    elif settings.data_path:
        repository = ResearchRepository.from_jsonl(settings.data_path)
    else:
        repository = ResearchRepository()
    vector_store = InMemoryVectorStore()
    vector_store.add_many(repository.all())
    return ResearchOrchestrator(repository=repository, vector_store=vector_store)


def evidence_input_to_record(item: EvidenceInput, disease: str | None) -> IngestionRecord:
    metadata: dict[str, str | int | float | bool | None] = {}
    if item.year:
        metadata["year"] = item.year
    return IngestionRecord(
        dataset=item.source,
        record_id=item.source_id,
        disease=disease,
        title=item.title,
        text=item.text,
        source_url=item.url,
        metadata=metadata,
    )


def evidence_to_response(evidence: Evidence) -> dict[str, object]:
    return {
        "source": evidence.source,
        "source_id": evidence.source_id,
        "title": evidence.title,
        "url": evidence.url,
        "year": evidence.year,
        "quality": evidence.quality,
    }


def knowledge_triple_to_response(triple: object) -> dict[str, object]:
    return {
        "subject": getattr(triple, "subject"),
        "predicate": getattr(triple, "predicate"),
        "object": getattr(triple, "object"),
        "evidence": [evidence_to_response(item) for item in getattr(triple, "evidence")],
        "confidence": getattr(triple, "confidence"),
    }


def provenance_to_response(report: object, settings: Settings) -> dict[str, object]:
    evidence = getattr(report, "evidence")
    sources = sorted({item.source for item in evidence})
    references = getattr(report, "unified_references")
    data_path = settings.sqlite_path or settings.data_path
    return {
        "generated_by": settings.app_name,
        "environment": settings.environment,
        "evidence_records": len(evidence),
        "sources": sources,
        "references": references,
        "data_path": str(data_path) if data_path else None,
    }


app = create_app()
