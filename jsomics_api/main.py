"""
JSOMICS — Merged API entry point

Combines:
  - bio_research_ai  →  multi-agent research engine (orchestrator, agents, ingestion)
  - jsomics_api      →  Supabase Auth JWT, per-user rate limiting, user profiles, admin

Start locally:
    uvicorn jsomics_api.main:app --reload --port 8000

Deploy on Railway:
    Start command: uvicorn jsomics_api.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from jsomics_api.config import settings
from jsomics_api.engine import build_orchestrator
from jsomics_api.routers import health, auth, users, research, ingest
from jsomics_api.middleware.rate_limit import RateLimitMiddleware


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[JSOMICS] Starting — env={settings.ENV}")
    # Warm up the orchestrator (connects to DB, loads vector store)
    app.state.orchestrator = build_orchestrator(settings)
    print(f"[JSOMICS] Orchestrator ready — {len(app.state.orchestrator.repository.all())} evidence records")
    yield
    print("[JSOMICS] Shutting down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="JSOMICS API",
    description=(
        "AI-powered multi-omics research intelligence. "
        "Combines PubMed literature mining, KEGG pathway analysis, "
        "biomarker identification, and drug target discovery."
    ),
    version="1.0.0",
    docs_url="/api/docs" if settings.ENV != "production" else None,
    redoc_url="/api/redoc" if settings.ENV != "production" else None,
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-API-Key"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "X-RateLimit-Limit"],
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.add_middleware(RateLimitMiddleware)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth.router,     prefix="/v1/auth",     tags=["auth"])
app.include_router(users.router,    prefix="/v1/users",    tags=["users"])
app.include_router(research.router, prefix="/v1",          tags=["research"])
app.include_router(ingest.router,   prefix="/v1/ingest",   tags=["ingest"])

# ── Serve built-in frontend (bio_research_ai/web/) ───────────────────────────
_web_dir = Path(__file__).resolve().parents[1] / "bio_research_ai" / "web"
if _web_dir.exists():
    app.mount("/app", StaticFiles(directory=_web_dir, html=True), name="web")

# ── GPT Action OpenAPI spec ───────────────────────────────────────────────────
_gpt_spec = Path(__file__).resolve().parents[1] / "gpt" / "jsomics_action_openapi.yaml"

@app.get("/.well-known/jsomics-action-openapi.yaml", include_in_schema=False)
def gpt_openapi():
    from fastapi.responses import FileResponse
    if _gpt_spec.exists():
        return FileResponse(_gpt_spec, media_type="text/yaml")
    return JSONResponse({"error": "spec not found"}, status_code=404)

# ── Global exception handler ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": str(exc)},
    )

# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "JSOMICS API",
        "version": "1.0.0",
        "status": "ok",
        "docs": "/api/docs",
        "research": "POST /v1/research",
    }
