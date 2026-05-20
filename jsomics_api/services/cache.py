"""
JSOMICS — temporary query cache for Vercel serverless.

Primary: Vercel KV / Upstash Redis over REST using one of:
  - KV_REST_API_URL + KV_REST_API_TOKEN
  - UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN

Fallback: in-process memory cache. This is only best-effort on Vercel because
serverless instances are short-lived, but it keeps local development working.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import httpx

_MEMORY_CACHE: dict[str, tuple[float, Any]] = {}
DEFAULT_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "86400"))


def _redis_url() -> str:
    return (os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/")


def _redis_token() -> str:
    return os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""


def _make_key(
    query: str,
    disease: str | None,
    mode: str,
    evidence_level: str | None = None,
    max_results: int | None = None,
) -> str:
    raw = f"{query.strip().lower()}|{(disease or '').lower()}|{mode}|{evidence_level}|{max_results}"
    return "jsomics:research:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


async def get_cached(
    query: str,
    disease: str | None,
    mode: str,
    evidence_level: str | None = None,
    max_results: int | None = None,
) -> dict | None:
    key = _make_key(query, disease, mode, evidence_level, max_results)

    url = _redis_url()
    token = _redis_token()
    if url and token:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.get(f"{url}/get/{key}", headers={"Authorization": f"Bearer {token}"})
            res.raise_for_status()
            payload = res.json()
            value = payload.get("result")
            if not value:
                return None
            if isinstance(value, str):
                return json.loads(value)
            return value
        except Exception as exc:
            print(f"[cache] Upstash get failed: {exc}")

    entry = _MEMORY_CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        _MEMORY_CACHE.pop(key, None)
        return None
    return value


async def set_cached(
    query: str,
    disease: str | None,
    mode: str,
    evidence_level: str | None = None,
    max_results: int | None = None,
    result: dict | None = None,
    ttl_seconds: int | None = None,
) -> None:
    key = _make_key(query, disease, mode, evidence_level, max_results)
    ttl = ttl_seconds or DEFAULT_TTL_SECONDS
    value = json.dumps(result, default=str)

    url = _redis_url()
    token = _redis_token()
    if url and token:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.post(
                    f"{url}/set/{key}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"value": value, "ex": ttl},
                )
            res.raise_for_status()
            return
        except Exception as exc:
            print(f"[cache] Upstash set failed: {exc}")

    _MEMORY_CACHE[key] = (time.time() + ttl, result)


async def get_json_key(key: str) -> Any | None:
    """Generic JSON cache lookup used by job status/result state."""
    url = _redis_url()
    token = _redis_token()
    if url and token:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.get(f"{url}/get/{key}", headers={"Authorization": f"Bearer {token}"})
            res.raise_for_status()
            payload = res.json()
            value = payload.get("result")
            if not value:
                return None
            return json.loads(value) if isinstance(value, str) else value
        except Exception as exc:
            print(f"[cache] Upstash generic get failed: {exc}")
    entry = _MEMORY_CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        _MEMORY_CACHE.pop(key, None)
        return None
    return value


async def set_json_key(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """Generic JSON cache write used by job status/result state."""
    ttl = ttl_seconds or DEFAULT_TTL_SECONDS
    encoded = json.dumps(value, default=str)
    url = _redis_url()
    token = _redis_token()
    if url and token:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.post(
                    f"{url}/set/{key}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"value": encoded, "ex": ttl},
                )
            res.raise_for_status()
            return
        except Exception as exc:
            print(f"[cache] Upstash generic set failed: {exc}")
    _MEMORY_CACHE[key] = (time.time() + ttl, value)
