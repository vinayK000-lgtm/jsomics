"""
JSOMICS — Supabase client
Single shared instance using the service-role key (server-side only).
"""
from __future__ import annotations
from jsomics_api.config import settings


def get_supabase():
    """Lazy-import so the app still starts if supabase isn't installed."""
    try:
        from supabase import create_client
        return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    except ImportError:
        return None


# Module-level singleton — None if supabase package not installed
supabase = get_supabase()
