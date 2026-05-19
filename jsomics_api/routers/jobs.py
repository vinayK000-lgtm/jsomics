from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from bio_research_ai.api.schemas import ResearchRequest, ResearchResponse
from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.middleware.rate_limit import enforce_daily_rate_limit
from jsomics_api.routers.research import execute_research
from jsomics_api.services.job_store import create_job, get_job, public_job, request_stop, set_job, update_job

router = APIRouter()


def _ensure_owner(job: dict, user: AuthUser) -> None:
    if not job or job.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Job not found")


@router.post("/jobs")
async def create_research_job(body: ResearchRequest, response: Response, user: AuthUser = Depends(get_current_user)):
    rate_headers = enforce_daily_rate_limit(user)
    job = await create_job(user.id, body.model_dump(mode="json"))
    for header, value in rate_headers.items():
        response.headers[header] = value
    return public_job(job)


@router.get("/jobs/{job_id}/status")
async def job_status(job_id: str, user: AuthUser = Depends(get_current_user)):
    job = await get_job(job_id)
    _ensure_owner(job, user)
    return public_job(job)


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str, user: AuthUser = Depends(get_current_user)):
    job = await get_job(job_id)
    _ensure_owner(job, user)
    stopped = await request_stop(job_id)
    return public_job(stopped)


@router.post("/jobs/{job_id}/run", response_model=ResearchResponse)
async def run_job(job_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    job = await get_job(job_id)
    _ensure_owner(job, user)
    if job.get("cancel_requested"):
        await update_job(job_id, status="cancelled", progress=0, message="Cancelled before execution")
        raise HTTPException(status_code=409, detail="Job cancelled")
    if job.get("result"):
        return ResearchResponse.model_validate(job["result"])

    await update_job(
        job_id,
        status="running",
        progress=12,
        message="Launching source agents",
        agents={"pubmed": "queued", "kegg": "queued", "pubchem": "queued", "llm_synthesis": "waiting"},
    )
    try:
        body = ResearchRequest.model_validate(job["payload"])
        result = await execute_research(body, request, user=user, job_id=job_id)
        final_agents = result.provenance.agent_status or {}
        final_agents["llm_synthesis"] = "done" if result.provenance.llm_enabled else "not_configured"
        data = result.model_dump(mode="json")
        job = await get_job(job_id) or job
        if job.get("cancel_requested"):
            await update_job(job_id, status="cancelled", progress=95, message="Stopped after source execution")
            raise HTTPException(status_code=409, detail="Job cancelled")
        job.update({
            "status": "done",
            "progress": 100,
            "message": "Multiomics synthesis complete",
            "agents": final_agents,
            "result": data,
            "error": None,
        })
        await set_job(job)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        await update_job(job_id, status="error", progress=100, message="Job failed", error=str(exc))
        raise


@router.get("/jobs/{job_id}/result", response_model=ResearchResponse)
async def job_result(job_id: str, user: AuthUser = Depends(get_current_user)):
    job = await get_job(job_id)
    _ensure_owner(job, user)
    if not job.get("result"):
        raise HTTPException(status_code=404, detail="Result not ready")
    return ResearchResponse.model_validate(job["result"])
