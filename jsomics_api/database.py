from __future__ import annotations
import os


def get_supabase():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("[JSOMICS] WARNING: Supabase not configured — running without DB")
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        print(f"[JSOMICS] WARNING: Supabase init failed: {e}")
        return None


supabase = get_supabase()
