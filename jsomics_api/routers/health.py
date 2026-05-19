"""JSOMICS — Health router"""
from __future__ import annotations

import os
import time
from fastapi import APIRouter, Request

from jsomics_api.config import settings

router   = APIRouter()
_started = time.time()


@router.get("/health", tags=["system"])
async def health(request: Request):
    """Liveness probe — Railway pings this."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    return {
        "status": "ok",
        "environment": settings.ENV,
        "auth_enabled": bool(settings.SUPABASE_JWT_SECRET or os.getenv("BIO_RESEARCH_API_KEYS")),
        "uptime_s": round(time.time() - _started),
        "evidence_records": len(orchestrator.repository.all()) if orchestrator else 0,
    }


@router.get("/ready", tags=["system"])
async def ready(request: Request):
    """Readiness probe — checks engine and DB."""
    from jsomics_api.database import supabase
    db_ok = False
    if supabase:
        try:
            supabase.table("profiles").select("id").limit(1).execute()
            db_ok = True
        except Exception:
            pass

    orchestrator = getattr(request.app.state, "orchestrator", None)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status": "ready" if db_ok else "degraded",
            "database": "ok" if db_ok else "unreachable",
            "evidence_records": len(orchestrator.repository.all()) if orchestrator else 0,
        },
    )
