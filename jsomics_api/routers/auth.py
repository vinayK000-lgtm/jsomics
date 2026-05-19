from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr, field_validator

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings
from jsomics_api.database import supabase

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOCAL_REDIRECT_HOSTS = {"localhost", "127.0.0.1", "::1"}


class SignUpBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    redirect_to: str | None = Field(default=None, max_length=500)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_RE.fullmatch(email):
            raise ValueError("Enter a valid email address.")
        return email

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class SignInBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_RE.fullmatch(email):
            raise ValueError("Enter a valid email address.")
        return email


class PublicAuthConfig(BaseModel):
    supabase_url: str
    supabase_anon_key: str
    redirect_base: str | None = None


def _allowed_redirect_origins() -> set[str]:
    origins = {origin.rstrip("/") for origin in settings.ALLOWED_ORIGINS}
    if settings.PUBLIC_SITE_URL:
        origins.add(settings.PUBLIC_SITE_URL)
    return {origin.lower() for origin in origins if origin}


def _validate_redirect_to(value: str) -> str:
    redirect = value.strip()
    try:
        parts = urlsplit(redirect)
    except ValueError:
        raise HTTPException(400, "Invalid redirect URL")

    if not parts.scheme or not parts.netloc or parts.username or parts.password or parts.fragment:
        raise HTTPException(400, "Invalid redirect URL")

    host = (parts.hostname or "").lower()
    scheme = parts.scheme.lower()
    origin = f"{scheme}://{parts.netloc}".lower().rstrip("/")
    allowed = _allowed_redirect_origins()
    local_dev = settings.ENV != "production" and host in LOCAL_REDIRECT_HOSTS

    if scheme not in {"http", "https"}:
        raise HTTPException(400, "Redirect URL must use HTTP or HTTPS")
    if origin not in allowed and not local_dev:
        raise HTTPException(400, "Redirect URL is not allowed")
    if scheme != "https" and not local_dev:
        raise HTTPException(400, "Redirect URL must use HTTPS")
    return redirect


@router.get("/config", response_model=PublicAuthConfig)
async def auth_config():
    return {
        "supabase_url": settings.SUPABASE_URL,
        "supabase_anon_key": settings.SUPABASE_ANON_KEY,
        "redirect_base": settings.PUBLIC_SITE_URL or None,
    }


@router.post("/signup", status_code=201)
async def signup(body: SignUpBody):
    if not supabase:
        raise HTTPException(503, "Supabase not configured")
    redirect_to = _validate_redirect_to(body.redirect_to) if body.redirect_to else None
    try:
        options = {"data": {"full_name": body.full_name or ""}}
        if redirect_to:
            options["email_redirect_to"] = redirect_to
        res = supabase.auth.sign_up({
            "email": body.email,
            "password": body.password.get_secret_value(),
            "options": options,
        })
    except Exception as exc:
        detail = "Signup failed. Check your details or use a different email."
        if settings.ENV != "production":
            detail = f"{detail} ({exc})"
        raise HTTPException(400, detail)
    if not res.user:
        raise HTTPException(400, "Signup failed")
    return {
        "user_id": str(res.user.id),
        "email": res.user.email,
        "access_token": res.session.access_token if res.session else None,
        "token_type": "bearer" if res.session else None,
    }


@router.post("/signin")
async def signin(body: SignInBody):
    if not supabase:
        raise HTTPException(503, "Supabase not configured")
    try:
        res = supabase.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password.get_secret_value(),
        })
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not res.session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in failed")
    return {
        "access_token": res.session.access_token,
        "token_type": "bearer",
        "user_id": str(res.user.id),
        "email": res.user.email,
    }


@router.post("/signout")
async def signout(user: AuthUser = Depends(get_current_user)):
    return {"message": "Signed out"}


@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "plan": user.plan,
    }
