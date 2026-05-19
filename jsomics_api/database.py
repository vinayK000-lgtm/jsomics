import os

def get_supabase():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key or not url.startswith("http"):
        print("[JSOMICS] No valid Supabase config - running without DB")
        return None
    try:
        from supabase import create_client
        client = create_client(url, key)
        print(f"[JSOMICS] Supabase connected: {url}")
        return client
    except Exception:
        print("[JSOMICS] Supabase connection failed - running without DB")
        return None

supabase = get_supabase()
