"""Daily authenticated request limits."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status

from jsomics_api.auth import AuthUser
from jsomics_api.config import settings


def enforce_daily_rate_limit(user: AuthUser) -> dict[str, str]:
    """Raise if the user's daily limit is exhausted and return response headers."""
    limit = settings.plan_limits.get(user.plan, settings.RATE_LIMIT_FREE)
    count = _count_today(user.id)

    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily limit of {limit} calls reached for plan '{user.plan}'.",
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": str(limit)},
        )

    return {
        "X-RateLimit-Remaining": str(max(0, limit - count - 1)),
        "X-RateLimit-Limit": str(limit),
    }


def _count_today(user_id: str) -> int:
    from jsomics_api.database import supabase

    if not supabase:
        return 0
    try:
        today = date.today().isoformat()
        result = (
            supabase.table("query_log")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("created_at", today)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0
