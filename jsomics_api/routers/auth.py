from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr, field_validator

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings
from jsomics_api.database import supabase

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignUpBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)

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


@router.post("/signup", status_code=201)
async def signup(body: SignUpBody):
    if not supabase:
        raise HTTPException(503, "Supabase not configured")
    try:
        res = supabase.auth.sign_up({
            "email": body.email,
            "password": body.password.get_secret_value(),
            "options": {"data": {"full_name": body.full_name or ""}},
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
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "plan": user.plan}
