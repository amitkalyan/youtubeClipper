"""API shapes. Extra transcript fields such as raw segments are ignored on read."""

from __future__ import annotations

import json

from pydantic import BaseModel


class YoutubeIn(BaseModel):
    url: str
    title: str = ""
    confirmed_rights: bool = False


class ProjectOut(BaseModel):
    id: str
    title: str
    status: str
    error: str | None = None
    progress: float
    progress_message: str
    created_at: str
    updated_at: str
    source_url: str | None = None
    original_filename: str | None = None
    stored_path: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    has_audio: bool = False
    has_video: bool = False
    has_transcript: bool = False
    clip_count: int = 0
    current_job_id: str | None = None


class ScoreBreakdownOut(BaseModel):
    opening_hook: int
    interesting_content: int
    emotional_impact: int
    context: int
    complete_thought: int
    shareability: int
    av_quality: int


class ClipRenderOut(BaseModel):
    status: str = "none"
    crop_mode: str | None = None
    manual_offset: float = 0
    use_manual: bool = False
    has_preview: bool = False
    has_export: bool = False
    error: str | None = None


class SpeechPart(BaseModel):
    start: float
    end: float


class ClipOut(BaseModel):
    id: str
    project_id: str
    ordinal: int
    start: float
    end: float
    duration: float
    transcript: str
    opening_hook: str
    category: str
    score: int
    score_breakdown: ScoreBreakdownOut
    reason: str
    suggested_title: str
    segments: list[SpeechPart] = []
    render: ClipRenderOut = ClipRenderOut()


class MetadataOut(BaseModel):
    clip_id: str
    project_id: str
    titles: list[str]
    selected_title: str
    description: str
    hashtags: list[str]
    headline: str
    cta: str
    category: str
    keywords: list[str]
    has_thumbnail: bool = False


class MetadataIn(BaseModel):
    titles: list[str]
    selected_title: str
    description: str
    hashtags: list[str]
    headline: str
    cta: str
    keywords: list[str]


class PreviewIn(BaseModel):
    clip_id: str | None = None


class ExportIn(BaseModel):
    clip_id: str


class CropIn(BaseModel):
    offset: float = 0
    use_detector: bool = False


class WordOut(BaseModel):
    word: str
    start: float
    end: float
    probability: float | None = None


class SentenceOut(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[WordOut]


class TranscriptOut(BaseModel):
    language: str | None = None
    language_probability: float | None = None
    model: str
    duration: float | None = None
    text: str
    sentences: list[SentenceOut]
    warnings: list[str] = []


class JobOut(BaseModel):
    id: str
    project_id: str
    project_title: str
    status: str
    stage: str
    progress: float
    message: str
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class ToolStatus(BaseModel):
    available: bool
    path: str
    version: str | None = None


class WhisperStatus(BaseModel):
    model: str
    device: str
    compute_type: str
    threads: int
    configured_threads: int
    vad_filter: bool
    profile_ok: bool
    profile_message: str | None = None


class OllamaModelIn(BaseModel):
    model: str


class OllamaStatus(BaseModel):
    host: str
    model: str
    models: list[str] = []
    used_in_phase: int
    note: str


class JobCapacity(BaseModel):
    max_concurrent: int
    max_queued: int
    running_project_id: str | None = None
    queued: int


class HealthOut(BaseModel):
    status: str
    phase: int
    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    whisper: WhisperStatus
    ollama: OllamaStatus
    jobs: JobCapacity
    data_dir: str
    output_dir: str
    max_upload_bytes: int


def _maybe_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)  # type: ignore[arg-type]


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]


def project_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "error": row.get("error"),
        "progress": float(row.get("progress") or 0),
        "progress_message": row.get("progress_message") or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "source_url": row.get("source_url"),
        "original_filename": row.get("original_filename"),
        "stored_path": row.get("stored_path"),
        "file_size_bytes": _maybe_int(row.get("file_size_bytes")),
        "duration_seconds": _maybe_float(row.get("duration_seconds")),
        "width": _maybe_int(row.get("width")),
        "height": _maybe_int(row.get("height")),
        "fps": _maybe_float(row.get("fps")),
        "video_codec": row.get("video_codec"),
        "audio_codec": row.get("audio_codec"),
        "audio_sample_rate": _maybe_int(row.get("audio_sample_rate")),
        "audio_channels": _maybe_int(row.get("audio_channels")),
        "has_audio": bool(row.get("has_audio")),
        "has_video": bool(row.get("has_video")),
        "has_transcript": bool(row.get("has_transcript")),
        "clip_count": int(row.get("clip_count") or 0),
        "current_job_id": row.get("current_job_id"),
    }


def _clip_segments(row: dict) -> list[dict]:
    raw = row.get("segments")
    parsed = raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
    if isinstance(parsed, list):
        segments = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                start = float(item["start"])
                end = float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end > start:
                segments.append({"start": start, "end": end})
        if segments:
            return segments
    return [{"start": float(row["start_seconds"]), "end": float(row["end_seconds"])}]


def clip_to_dict(row: dict) -> dict:
    breakdown = row.get("score_breakdown") or {}
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "ordinal": int(row["ordinal"]),
        "start": float(row["start_seconds"]),
        "end": float(row["end_seconds"]),
        "duration": float(row["duration_seconds"]),
        "transcript": row["transcript"],
        "opening_hook": row["opening_hook"],
        "category": row["category"],
        "score": int(row["score"]),
        "score_breakdown": {
            "opening_hook": int(breakdown.get("opening_hook") or 0),
            "interesting_content": int(breakdown.get("interesting_content") or 0),
            "emotional_impact": int(breakdown.get("emotional_impact") or 0),
            "context": int(breakdown.get("context") or 0),
            "complete_thought": int(breakdown.get("complete_thought") or 0),
            "shareability": int(breakdown.get("shareability") or 0),
            "av_quality": int(breakdown.get("av_quality") or 0),
        },
        "reason": row["reason"],
        "suggested_title": row["suggested_title"],
        "segments": _clip_segments(row),
        "render": {
            "status": row.get("render_status") or "none",
            "crop_mode": row.get("crop_mode"),
            "manual_offset": float(row.get("manual_offset") or 0),
            "use_manual": bool(row.get("use_manual")),
            "has_preview": bool(row.get("preview_path")),
            "has_export": bool(row.get("export_path")),
            "error": row.get("render_error"),
        },
    }


def metadata_to_dict(row: dict) -> dict:
    return {
        "clip_id": row["clip_id"],
        "project_id": row["project_id"],
        "titles": list(row.get("titles") or []),
        "selected_title": row.get("selected_title") or "",
        "description": row.get("description") or "",
        "hashtags": list(row.get("hashtags") or []),
        "headline": row.get("headline") or "",
        "cta": row.get("cta") or "",
        "category": row.get("category") or "",
        "keywords": list(row.get("keywords") or []),
        "has_thumbnail": bool(row.get("thumbnail_path")),
    }


def job_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "project_title": row.get("project_title") or "",
        "status": row["status"],
        "stage": row.get("stage") or "",
        "progress": float(row.get("progress") or 0),
        "message": row.get("message") or "",
        "error": row.get("error"),
        "created_at": row["created_at"],
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }
