"""
JSOMICS — Auth dependency

Supports two auth modes (checked in order):
  1. Supabase JWT (Bearer token from frontend login) — preferred
  2. X-API-Key header (static key from env BIO_RESEARCH_API_KEYS) — for scripts/bots

Usage:
    @router.post("/endpoint")
    async def endpoint(user: AuthUser = Depends(get_current_user)):
        ...
"""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from jsomics_api.config import settings


class AuthUser(BaseModel):
    id: str
    email: str
    plan: str = "free"
    full_name: str | None = None
    auth_method: str = "jwt"   # "jwt" | "api_key"


bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthUser:
    """
    Validates request auth and returns an AuthUser.
    Raises HTTP 401 if neither JWT nor API key is valid.
    """
    # ── 1. Try Supabase JWT ──────────────────────────────────────────────────
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        user = _verify_jwt(token)
        if user:
            return _attach_request_user(request, user)

    # ── 2. Try X-API-Key ────────────────────────────────────────────────────
    api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if api_key and _valid_api_key(api_key):
        return _attach_request_user(
            request,
            AuthUser(
                id=f"apikey:{_fingerprint_secret(api_key)}",
                email="api@jsomics.com",
                plan="researcher",
                auth_method="api_key",
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid credentials. Provide a Supabase Bearer token or X-API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _verify_jwt(token: str) -> AuthUser | None:
    """Verify Supabase JWT. Returns AuthUser on success, None on failure."""
    # Strategy A: use PyJWT to verify offline (fast, no network)
    if settings.SUPABASE_JWT_SECRET:
        try:
            import jwt
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False, "require": ["exp", "sub"]},
            )
            user_id  = str(payload.get("sub") or "")
            if not user_id:
                return None
            email    = str(payload.get("email") or "")
            metadata = payload.get("user_metadata", {}) or {}
            plan     = _fetch_plan_from_db(user_id)
            return AuthUser(
                id=user_id,
                email=email,
                plan=plan,
                full_name=metadata.get("full_name"),
                auth_method="jwt",
            )
        except Exception:
            pass

    # Strategy B: verify via Supabase REST (requires network, slower)
    from jsomics_api.database import supabase
    if supabase:
        try:
            resp = supabase.auth.get_user(token)
            if resp and resp.user:
                u    = resp.user
                plan = _fetch_plan_from_db(str(u.id))
                return AuthUser(
                    id=str(u.id),
                    email=u.email or "",
                    plan=plan,
                    full_name=(u.user_metadata or {}).get("full_name"),
                    auth_method="jwt",
                )
        except Exception:
            pass

    return None


def _fetch_plan_from_db(user_id: str) -> str:
    """Look up user plan from Supabase profiles table. Defaults to 'free'."""
    from jsomics_api.database import supabase
    if not supabase or not user_id:
        return "free"
    try:
        result = (
            supabase.table("profiles")
            .select("plan")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return result.data.get("plan", "free") if result.data else "free"
    except Exception:
        return "free"


def _valid_api_key(key: str) -> bool:
    """Check key against BIO_RESEARCH_API_KEYS env var (comma-separated)."""
    raw = os.getenv("BIO_RESEARCH_API_KEYS", "")
    valid = [k.strip() for k in raw.split(",") if k.strip()]
    return any(hmac.compare_digest(key, candidate) for candidate in valid)


def _fingerprint_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _attach_request_user(request: Request, user: AuthUser) -> AuthUser:
    request.state.user_id = user.id
    request.state.plan = user.plan
    return user


# ── Optional user (for public endpoints) ─────────────────────────────────────
async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthUser | None:
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None
