"""
JSOMICS — Rate limit middleware

Enforces per-user daily API call limits by plan:
  free:       100 calls/day
  researcher: 10,000 calls/day
  lab:        unlimited

Uses Supabase query_log table to count. Fails open on DB errors.
"""
from __future__ import annotations

from datetime import date

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from jsomics_api.config import settings

RATE_LIMITED = ("/v1/research", "/v1/ingest")


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not any(request.url.path.startswith(p) for p in RATE_LIMITED):
            return await call_next(request)

        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return await call_next(request)

        plan    = getattr(request.state, "plan", "free")
        limit   = settings.plan_limits.get(plan, settings.RATE_LIMIT_FREE)
        count   = _count_today(user_id)
        remaining = max(0, limit - count)

        if count >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": f"Daily limit of {limit} calls reached for plan '{plan}'.",
                    "upgrade_url": "https://jsomics.com/#pricing",
                },
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": str(limit)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining - 1))
        response.headers["X-RateLimit-Limit"]     = str(limit)
        return response


def _count_today(user_id: str) -> int:
    from jsomics_api.database import supabase
    if not supabase:
        return 0
    try:
        today  = date.today().isoformat()
        result = (
            supabase.table("query_log")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("created_at", today)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0  # fail open
