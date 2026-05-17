from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.database import supabase

router = APIRouter()

class SignUpBody(BaseModel):
    email: str
    password: str
    full_name: str | None = None

class SignInBody(BaseModel):
    email: str
    password: str

@router.post("/signup", status_code=201)
async def signup(body: SignUpBody):
    if not supabase:
        raise HTTPException(503, "Supabase not configured")
    try:
        res = supabase.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {"data": {"full_name": body.full_name or ""}},
        })
    except Exception as exc:
        raise HTTPException(400, str(exc))
    if not res.user:
        raise HTTPException(400, "Signup failed")
    return {
        "user_id": str(res.user.id),
        "email": res.user.email,
        "access_token": res.session.access_token if res.session else None,
    }

@router.post("/signin")
async def signin(body: SignInBody):
    if not supabase:
        raise HTTPException(503, "Supabase not configured")
    try:
        res = supabase.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not res.session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in failed")
    return {"access_token": res.session.access_token, "user_id": str(res.user.id), "email": res.user.email}

@router.post("/signout")
async def signout(user: AuthUser = Depends(get_current_user)):
    if supabase:
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
    return {"message": "Signed out"}

@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "plan": user.plan}
