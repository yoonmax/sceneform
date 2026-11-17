"""Reconstruction jobs: create, observe, cancel, retry."""

from __future__ import annotations

import asyncio
import json
import platform

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..config import settings
from ..schemas.models import JobCreate
from ..storage.db import db, now
from ..storage.files import run_dir, verify
from ..workers import jobs
from .deps import owned_project, owner

router = APIRouter(tags=["reconstruction"])
_capabilities_cache: dict | None = None


def capabilities(refresh: bool = False) -> dict:
    global _capabilities_cache
    if _capabilities_cache is None or refresh:
        from ..pipeline.gaussian_splat import detect_trainers

        trainers = detect_trainers()
        _capabilities_cache = {
            "reconstruction": True,
            "quick": {"available": True, "sfm": "COLMAP (CPU)", "depth": "Depth Anything V2 Small"},
            "high": {
                "available": any(t.available for t in trainers),
                "trainers": [t.__dict__ for t in trainers],
            },
            "mesh": True,
            "platform": f"{platform.system()} {platform.machine()}",
            "limits": {
                "maxUploadMB": settings.max_upload_bytes // (1 << 20),
                "maxImages": settings.max_images,
                "maxVideoSeconds": settings.max_video_seconds,
                "retentionHours": settings.retention_hours,
                "concurrentJobs": settings.max_concurrent_jobs,
            },
        }
    return _capabilities_cache


@router.get("/api/capabilities")
def get_capabilities():
    return capabilities()


@router.post("/api/projects/{project_id}/jobs")
def create_job(project_id: str, body: JobCreate, who: str = Depends(owner)):
    p = owned_project(project_id, who)
    n_assets = db().execute("SELECT COUNT(*) c FROM assets WHERE project_id=?", (p["id"],)).fetchone()["c"]
    if not n_assets:
        raise HTTPException(400, "Upload a video or photos before starting.")
    active = db().execute("SELECT COUNT(*) c FROM jobs WHERE owner=? AND state IN ('queued','running')", (who,)).fetchone()["c"]
    if active >= settings.max_queued_jobs_per_owner:
        raise HTTPException(429, "You already have reconstructions in progress. Wait for one to finish.")
    if db().execute("SELECT 1 FROM jobs WHERE project_id=? AND state IN ('queued','running')", (p["id"],)).fetchone():
        raise HTTPException(409, "This project is already being processed.")
    if body.mode == "high" and not capabilities()["high"]["available"]:
        raise HTTPException(
            422, "High-quality reconstruction needs a supported GPU trainer, which this server doesn't have. "
                 "Use Fast preview, or run sceneform on a machine with Apple Silicon or an NVIDIA GPU.")
    config = body.settings.model_dump()
    config["title"] = p["name"]
    db().execute("UPDATE projects SET settings=?, updated_at=? WHERE id=?", (json.dumps(config), now(), p["id"]))
    job = jobs.create_job(p["id"], who, body.mode, config)
    return jobs.public_job(job)


def _owned_job(job_id: str, who: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None or job["owner"] != who:
        raise HTTPException(404, "Job not found.")
    return job


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, who: str = Depends(owner)):
    job = _owned_job(job_id, who)
    out = jobs.public_job(job)
    q = db().execute("SELECT COUNT(*) c FROM jobs WHERE state='queued' AND created_at < ?", (job["created_at"],)).fetchone()
    out["queuePosition"] = q["c"] if job["state"] == "queued" else None
    return out


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, who: str = Depends(owner)):
    _owned_job(job_id, who)
    try:
        return jobs.public_job(jobs.request_cancel(job_id))
    except jobs.InvalidTransition as exc:
        raise HTTPException(409, f"This job can't be cancelled ({exc}).")


@router.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, who: str = Depends(owner)):
    _owned_job(job_id, who)
    try:
        return jobs.public_job(jobs.retry(job_id))
    except jobs.InvalidTransition as exc:
        raise HTTPException(409, f"This job can't be retried ({exc}).")


@router.get("/api/jobs/{job_id}/logs")
def job_logs(job_id: str, tail: int = Query(default=400, le=5000), who: str = Depends(owner)):
    job = _owned_job(job_id, who)
    path = run_dir(job["project_id"], job["run_id"]) / "events.jsonl"
    if not path.exists():
        return {"events": []}
    lines = path.read_text().splitlines()[-tail:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return {"events": events}


@router.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, sig: str = Query(...)):
    """Server-sent events with job state; ``sig`` is the project signature
    (EventSource cannot send custom headers)."""
    job = jobs.get_job(job_id)
    if job is None or not verify(job["project_id"], sig):
        raise HTTPException(404, "Job not found.")

    async def stream():
        last = None
        for _ in range(60 * 60 * 6):
            j = jobs.get_job(job_id)
            if j is None:
                break
            payload = json.dumps(jobs.public_job(j))
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            if j["state"] in jobs.TERMINAL:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
