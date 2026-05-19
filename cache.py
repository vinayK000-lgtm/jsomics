"""
JSOMICS — Query cache service
Caches research results in Supabase for 7 days.
Same query → returns in <200ms instead of 5-30 seconds.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone


def _make_key(query: str, disease: str | None, mode: str) -> str:
    raw = f"{query.strip().lower()}|{(disease or '').lower()}|{mode}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def get_cached(query: str, disease: str | None, mode: str) -> dict | None:
    from jsomics_api.database import supabase
    if not supabase:
        return None
    try:
        key = _make_key(query, disease, mode)
        res = (
            supabase.table("query_cache")
            .select("result, expires_at, hits")
            .eq("cache_key", key)
            .single()
            .execute()
        )
        if not res.data:
            return None
        # Check expiry
        expires = res.data.get("expires_at", "")
        if expires:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                # Expired — delete and return None
                supabase.table("query_cache").delete().eq("cache_key", key).execute()
                return None
        # Increment hit counter (fire and forget)
        try:
            supabase.table("query_cache").update(
                {"hits": (res.data.get("hits") or 1) + 1}
            ).eq("cache_key", key).execute()
        except Exception:
            pass
        print(f"[cache] HIT — key={key[:8]}... hits={res.data.get('hits')}")
        return res.data["result"]
    except Exception as e:
        print(f"[cache] get error: {e}")
        return None


async def set_cached(query: str, disease: str | None, mode: str, result: dict) -> None:
    from jsomics_api.database import supabase
    if not supabase:
        return
    try:
        key = _make_key(query, disease, mode)
        supabase.table("query_cache").upsert({
            "cache_key": key,
            "query": query,
            "disease": disease or "",
            "mode": mode,
            "result": result,
            "hits": 1,
        }).execute()
        print(f"[cache] SET — key={key[:8]}...")
    except Exception as e:
        print(f"[cache] set error: {e}")
