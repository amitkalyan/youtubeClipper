"""Process health. A missing FFmpeg binary degrades the report and does not crash startup."""

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthOut, OllamaModelIn, OllamaStatus
from app.services.job_manager import job_manager
from app.services.ollama_service import select_model, status
from app.services.video_service import tool_status

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health() -> dict:
    settings = get_settings()
    ffmpeg = tool_status("ffmpeg")
    ffprobe = tool_status("ffprobe")
    issue = settings.hardware_profile_issue()
    snap = job_manager.snapshot()
    ready = ffmpeg["available"] and ffprobe["available"] and issue is None
    return {
        "status": "ok" if ready else "degraded",
        "phase": 4,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "whisper": {
            "model": settings.whisper_model,
            "device": settings.whisper_device,
            "compute_type": settings.whisper_compute_type,
            "threads": settings.effective_threads(),
            "configured_threads": settings.whisper_threads,
            "vad_filter": settings.whisper_vad_filter,
            "profile_ok": issue is None,
            "profile_message": issue,
        },
        "ollama": status(),
        "jobs": {
            "max_concurrent": settings.max_concurrent_jobs,
            "max_queued": settings.max_queued_jobs,
            "running_project_id": snap["running_project_id"],
            "queued": snap["queued"],
        },
        "data_dir": str(settings.data_dir),
        "output_dir": str(settings.output_dir()),
        "max_upload_bytes": settings.max_upload_bytes,
    }


@router.put("/settings/ollama-model", response_model=OllamaStatus)
def update_ollama_model(body: OllamaModelIn) -> dict:
    select_model(body.model)
    return status()
