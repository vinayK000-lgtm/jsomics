from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = "JSOMICS"
    environment: str = "development"
    ncbi_email: str | None = None
    ncbi_api_key: str | None = None
    api_keys: tuple[str, ...] = ()
    database_url: str | None = None
    data_path: Path | None = None
    sqlite_path: Path | None = None
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_jwt_secret: str | None = None
    cors_origins: tuple[str, ...] = ()
    request_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        data_path = os.getenv("BIO_RESEARCH_DATA_PATH")
        sqlite_path = os.getenv("BIO_RESEARCH_SQLITE_PATH")
        api_keys = tuple(
            key.strip()
            for key in os.getenv("BIO_RESEARCH_API_KEYS", "").split(",")
            if key.strip()
        )
        cors_origins = tuple(
            origin.strip()
            for origin in os.getenv("BIO_RESEARCH_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        return cls(
            app_name=os.getenv("BIO_RESEARCH_APP_NAME", "JSOMICS"),
            environment=os.getenv("BIO_RESEARCH_ENV", "development"),
            ncbi_email=os.getenv("NCBI_EMAIL"),
            ncbi_api_key=os.getenv("NCBI_API_KEY"),
            api_keys=api_keys,
            database_url=os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL"),
            data_path=Path(data_path) if data_path else None,
            sqlite_path=Path(sqlite_path) if sqlite_path else None,
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY"),
            supabase_jwt_secret=os.getenv("SUPABASE_JWT_SECRET"),
            cors_origins=cors_origins,
            request_timeout_seconds=float(os.getenv("BIO_RESEARCH_TIMEOUT", "30")),
        )
