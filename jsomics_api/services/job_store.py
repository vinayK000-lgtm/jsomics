from __future__ import annotations

import time
import uuid
from typing import Any

from jsomics_api.config import settings
from jsomics_api.services.cache import get_json_key, set_json_key


def _key(job_id: str) -> str:
    return f"jsomics:job:{job_id}"


def _now() -> int:
    return int(time.time())


async def create_job(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = "job_" + uuid.uuid4().hex[:18]
    job = {
        "job_id": job_id,
        "user_id": user_id,
        "status": "queued",
        "progress": 0,
        "message": "Queued multiomics job",
        "agents": {},
        "payload": payload,
        "created_at": _now(),
        "updated_at": _now(),
        "cancel_requested": False,
        "result": None,
        "error": None,
    }
    await set_job(job)
    return job


async def get_job(job_id: str) -> dict[str, Any] | None:
    return await get_json_key(_key(job_id))


async def set_job(job: dict[str, Any]) -> None:
    job["updated_at"] = _now()
    await set_json_key(_key(job["job_id"]), job, ttl_seconds=getattr(settings, "JOB_TTL_SECONDS", 3600))


async def update_job(job_id: str, **updates: Any) -> dict[str, Any] | None:
    job = await get_job(job_id)
    if not job:
        return None
    job.update(updates)
    await set_job(job)
    return job


async def request_stop(job_id: str) -> dict[str, Any] | None:
    job = await get_job(job_id)
    if not job:
        return None
    job["cancel_requested"] = True
    if job.get("status") in {"queued", "running"}:
        job["status"] = "cancelled"
        job["progress"] = job.get("progress", 0)
        job["message"] = "Stop requested"
    await set_job(job)
    return job


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "message": job.get("message"),
        "agents": job.get("agents", {}),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "error": job.get("error"),
        "has_result": bool(job.get("result")),
    }
