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
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from jsomics_api.config import settings
from jsomics_api.engine import build_orchestrator
from jsomics_api.routers import health, auth, users, research, ingest, jobs
try:
    from jsomics_api.routers import geo as geo_router
    GEO_AVAILABLE = True
except ImportError as e:
    print(f"[JSOMICS] GEO router unavailable: {e}")
    GEO_AVAILABLE = False

try:
    from jsomics_api.routers import geo_jobs
    GEO_JOBS_AVAILABLE = True
except ImportError as e:
    print(f"[JSOMICS] GEO jobs router unavailable: {e}")
    GEO_JOBS_AVAILABLE = False


logger = logging.getLogger(__name__)


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
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://jsomics.com",
        "https://www.jsomics.com",
        "https://jsomics-api.fly.dev",
        "https://vinayk000-lgtm.github.io",
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-API-Key"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "X-RateLimit-Limit"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    if settings.ENV == "production":
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "img-src 'self' data: https:; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "connect-src 'self' https://*.supabase.co wss://*.supabase.co",
        )
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth.router,     prefix="/v1/auth",     tags=["auth"])
app.include_router(users.router,    prefix="/v1/users",    tags=["users"])
app.include_router(research.router, prefix="/v1",          tags=["research"])
app.include_router(jobs.router,     prefix="/v1",          tags=["jobs"])
app.include_router(ingest.router,   prefix="/v1/ingest",   tags=["ingest"])
if GEO_AVAILABLE:
    app.include_router(geo_router.router, prefix="/v1/geo", tags=["geo"])
else:
    @app.api_route("/v1/geo/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["geo"])
    async def geo_unavailable(path: str):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "GEO analysis is unavailable because scientific Python dependencies are not installed in this runtime.",
            },
        )
if GEO_JOBS_AVAILABLE:
    app.include_router(geo_jobs.router, prefix="/v1/geo", tags=["geo-jobs"])

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
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
    content = {"error": "internal_server_error"}
    if settings.ENV != "production":
        content["detail"] = str(exc)
    return JSONResponse(
        status_code=500,
        content=content,
    )

# ── Frontend config (public Supabase credentials only) ───────────────────────
@app.get("/api/config", include_in_schema=False)
async def frontend_config():
    return {
        "supabase_url": settings.SUPABASE_URL,
        "supabase_anon_key": settings.SUPABASE_ANON_KEY,
        "app_name": settings.APP_NAME,
        "env": settings.ENV,
        "live_evidence_enabled": settings.LIVE_EVIDENCE_ENABLED,
    }


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "JSOMICS API",
        "version": "1.0.0",
        "status": "ok",
        "frontend": "https://jsomics.com",
        "docs": "/api/docs",
    }
