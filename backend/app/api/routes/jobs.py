"""Processing history."""

from fastapi import APIRouter

from app import db
from app.errors import ClipperError, NotFoundError
from app.schemas import JobOut, job_to_dict
from app.services.job_manager import job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(limit: int = 50) -> list[dict]:
    bounded = min(max(limit, 1), 200)
    return [job_to_dict(row) for row in db.list_jobs(bounded)]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> dict:
    row = db.get_job(job_id)
    if row is None:
        raise NotFoundError("Job not found.")
    return job_to_dict(row)


@router.post("/{job_id}/cancel", response_model=JobOut, status_code=202)
def cancel_job(job_id: str) -> dict:
    row = db.get_job(job_id)
    if row is None:
        raise NotFoundError("Job not found.")
    if row["status"] not in {"queued", "running"}:
        raise ClipperError("This job is already finished.")
    project = db.get_project(row["project_id"])
    if project is None or project.get("current_job_id") != job_id:
        raise ClipperError("This job is not the active job for that project.")
    job_manager.request_cancel(row["project_id"])
    updated = db.get_job(job_id)
    if updated is None:
        raise NotFoundError("Job not found.")
    return job_to_dict(updated)
