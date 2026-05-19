"""
JSOMICS — Unified configuration

Reads all env vars in one place. Railway injects these automatically.
Copy .env.example → .env for local development.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


class Settings:
    # ── App ───────────────────────────────────────────────────────────────────
    ENV: str
    APP_NAME: str

    # ── Supabase ──────────────────────────────────────────────────────────────
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str           # used to verify JWTs without network call
    SUPABASE_DATABASE_URL: str | None  # postgres://... connection string
    PUBLIC_SITE_URL: str

    # ── NCBI / PubMed ─────────────────────────────────────────────────────────
    NCBI_EMAIL: str | None
    NCBI_API_KEY: str | None

    # ── Temporary cache / LLM ─────────────────────────────────────────────────
    KV_REST_API_URL: str | None
    KV_REST_API_TOKEN: str | None
    UPSTASH_REDIS_REST_URL: str | None
    UPSTASH_REDIS_REST_TOKEN: str | None
    CACHE_TTL_SECONDS: int
    LLM_PROVIDER: str
    OPENAI_API_KEY: str | None
    OPENAI_MODEL: str
    ANTHROPIC_API_KEY: str | None
    ANTHROPIC_MODEL: str
    LIVE_EVIDENCE_ENABLED: bool

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: tuple[str, ...]

    # ── Rate limits (calls/day per plan) ─────────────────────────────────────
    RATE_LIMIT_FREE: int
    RATE_LIMIT_RESEARCHER: int
    RATE_LIMIT_LAB: int

    # ── Storage paths (optional local fallbacks) ──────────────────────────────
    SQLITE_PATH: Path | None
    DATA_PATH: Path | None

    def __init__(self) -> None:
        self.ENV       = os.getenv("ENV", "development")
        self.APP_NAME  = os.getenv("APP_NAME", "JSOMICS")

        # Supabase — required in production
        self.SUPABASE_URL              = os.getenv("SUPABASE_URL", "")
        self.SUPABASE_ANON_KEY         = os.getenv("SUPABASE_ANON_KEY", "")
        self.SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.SUPABASE_JWT_SECRET       = os.getenv("SUPABASE_JWT_SECRET", "")
        self.SUPABASE_DATABASE_URL     = (
            os.getenv("SUPABASE_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        self.PUBLIC_SITE_URL = os.getenv(
            "PUBLIC_SITE_URL",
            "https://jsomics.com" if self.ENV == "production" else "",
        ).rstrip("/")

        # NCBI
        self.NCBI_EMAIL   = os.getenv("NCBI_EMAIL")
        self.NCBI_API_KEY = os.getenv("NCBI_API_KEY")

        # Temporary cache / LLM
        self.KV_REST_API_URL = os.getenv("KV_REST_API_URL")
        self.KV_REST_API_TOKEN = os.getenv("KV_REST_API_TOKEN")
        self.UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
        self.UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        self.CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "86400"))
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        self.ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        self.LIVE_EVIDENCE_ENABLED = os.getenv("LIVE_EVIDENCE_ENABLED", "true").lower() not in {"0", "false", "no"}

        # CORS
        default_origins = (
            "https://jsomics.com,https://www.jsomics.com"
            if self.ENV == "production"
            else (
                "https://jsomics.com,https://www.jsomics.com,"
                "http://localhost:3000,http://127.0.0.1:5500"
            )
        )
        raw_origins = os.getenv("ALLOWED_ORIGINS", default_origins)
        self.ALLOWED_ORIGINS = tuple(o.strip() for o in raw_origins.split(",") if o.strip())

        # Rate limits
        self.RATE_LIMIT_FREE       = int(os.getenv("RATE_LIMIT_FREE", "100"))
        self.RATE_LIMIT_RESEARCHER = int(os.getenv("RATE_LIMIT_RESEARCHER", "10000"))
        self.RATE_LIMIT_LAB        = int(os.getenv("RATE_LIMIT_LAB", "999999"))

        # Local storage paths (optional)
        sqlite = os.getenv("SQLITE_PATH") or os.getenv("BIO_RESEARCH_SQLITE_PATH")
        data   = os.getenv("DATA_PATH")   or os.getenv("BIO_RESEARCH_DATA_PATH")
        self.SQLITE_PATH = Path(sqlite) if sqlite else None
        self.DATA_PATH   = Path(data)   if data   else None

    @property
    def supabase_ok(self) -> bool:
        return bool(self.SUPABASE_URL and self.SUPABASE_SERVICE_ROLE_KEY)

    @property
    def plan_limits(self) -> dict[str, int]:
        return {
            "free":       self.RATE_LIMIT_FREE,
            "researcher": self.RATE_LIMIT_RESEARCHER,
            "lab":        self.RATE_LIMIT_LAB,
        }


settings = Settings()
