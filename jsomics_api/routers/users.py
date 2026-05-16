"""JSOMICS — Users router"""
from __future__ import annotations

from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings
from jsomics_api.database import supabase

router = APIRouter()


@router.get("/me")
async def get_profile(user: AuthUser = Depends(get_current_user)):
    today      = date.today().isoformat()
    calls_today = 0
    if supabase:
        try:
            r = (
                supabase.table("query_log")
                .select("id", count="exact")
                .eq("user_id", user.id)
                .gte("created_at", today)
                .execute()
            )
            calls_today = r.count or 0
        except Exception:
            pass

    return {
        "id":             user.id,
        "email":          user.email,
        "full_name":      user.full_name,
        "plan":           user.plan,
        "api_calls_today": calls_today,
        "daily_limit":    settings.plan_limits.get(user.plan, settings.RATE_LIMIT_FREE),
    }


@router.get("/me/usage")
async def get_usage(days: int = 7, user: AuthUser = Depends(get_current_user)):
    since = (date.today() - timedelta(days=days)).isoformat()
    rows  = []
    if supabase:
        try:
            r = (
                supabase.table("query_log")
                .select("created_at, modalities, query")
                .eq("user_id", user.id)
                .gte("created_at", since)
                .order("created_at", desc=True)
                .execute()
            )
            rows = r.data or []
        except Exception:
            pass

    return {"user_id": user.id, "period_days": days, "total_calls": len(rows), "calls": rows}
