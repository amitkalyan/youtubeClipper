"""Upload a local video and read its transcript. Files are streamed to disk."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app import db
from app.config import ALLOWED_EXTENSIONS, get_settings
from app.errors import (
    AudioTrackMissingError,
    ClipperError,
    InvalidMediaError,
    JobBusyError,
    NotFoundError,
    UploadTooLargeError,
)
from app.names import clean_filename, resolve_title
from app.schemas import (
    ClipOut,
    CropIn,
    ExportIn,
    MetadataIn,
    MetadataOut,
    PreviewIn,
    ProjectOut,
    TranscriptOut,
    YoutubeIn,
    clip_to_dict,
    metadata_to_dict,
    project_to_dict,
)
from app.services import metadata_service, rendering_service, storage_service, thumbnail_service, video_service
from app.services.youtube_service import canonical_url, parse_youtube_url
from app.services.job_manager import job_manager

logger = logging.getLogger("clipper.api")
router = APIRouter(prefix="/projects", tags=["projects"])
CHUNK_BYTES = 1024 * 1024


@router.get("", response_model=list[ProjectOut])
def list_projects(limit: int = 100) -> list[dict]:
    bounded = min(max(limit, 1), 200)
    return [project_to_dict(row) for row in db.list_projects(bounded)]


@router.post("/upload", response_model=ProjectOut, status_code=201)
async def upload_project(
    file: UploadFile = File(...),
    title: str = Form(""),
) -> dict:
    settings = get_settings()
    video_service.assert_tools_available()
    original = clean_filename(file.filename)
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise InvalidMediaError(
            "Upload a video file (.mp4, .mov, .mkv, .webm, .avi, or .m4v)."
        )
    chosen = resolve_title(title, original)
    declared = getattr(file, "size", None)
    if declared is not None and declared > settings.max_upload_bytes:
        raise UploadTooLargeError(_too_large(settings.max_upload_bytes))

    project_id = db.create_project(chosen)
    dest = storage_service.source_path(project_id, suffix)
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with dest.open("wb") as handle:
            while True:
                chunk = await file.read(CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise UploadTooLargeError(_too_large(settings.max_upload_bytes))
                handle.write(chunk)
    except UploadTooLargeError:
        dest.unlink(missing_ok=True)
        _mark_failed(project_id, _too_large(settings.max_upload_bytes))
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        _mark_failed(project_id, "The upload did not finish.")
        raise
    finally:
        await file.close()

    if written == 0:
        dest.unlink(missing_ok=True)
        message = "The uploaded file is empty."
        db.fail_project(project_id, message)
        return _project(project_id)

    try:
        info = await asyncio.to_thread(video_service.probe, dest)
    except ClipperError as exc:
        dest.unlink(missing_ok=True)
        db.fail_project(project_id, str(exc))
        return _project(project_id)

    if not info.has_video:
        dest.unlink(missing_ok=True)
        db.fail_project(project_id, "No video stream found in that file.")
        return _project(project_id)

    db.insert_source(
        project_id,
        original_filename=original,
        stored_path=str(dest.resolve()),
        info=info,
        file_size=written,
    )
    if not info.has_audio:
        db.fail_project(project_id, "This video has no audio track to transcribe.")
        return _project(project_id)

    try:
        job_manager.enqueue(project_id)
    except JobBusyError:
        db.update_project(
            project_id,
            status="uploaded",
            progress=0,
            progress_message="Processor is busy. Start transcription when the current job finishes.",
            error=None,
        )
    logger.info("Uploaded project=%s bytes=%s", project_id, written)
    return _project(project_id)


@router.post("/youtube", response_model=ProjectOut, status_code=201)
def create_youtube_project(body: YoutubeIn) -> dict:
    if not body.confirmed_rights:
        raise InvalidMediaError("Confirm that you have the right to download and edit this video.")
    video_service.assert_tools_available()
    video_id = parse_youtube_url(body.url)
    watch = canonical_url(video_id)
    supplied = " ".join(body.title.split())
    title = resolve_title(supplied, "video.mp4") if supplied else "YouTube video"
    project_id = db.create_project(
        title,
        source_url=watch,
        message="YouTube link saved. Waiting to download.",
    )
    try:
        job_manager.enqueue(project_id)
    except JobBusyError:
        db.update_project(
            project_id,
            status="uploaded",
            progress=0,
            progress_message="Processor is busy. Start the download when the current job finishes.",
            error=None,
        )
    logger.info("Queued YouTube project=%s video=%s", project_id, video_id)
    return _project(project_id)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str) -> dict:
    return _project(storage_service.assert_project_id(project_id))


@router.get("/{project_id}/transcript", response_model=TranscriptOut)
def get_transcript(project_id: str) -> TranscriptOut:
    project_id = storage_service.assert_project_id(project_id)
    if db.get_project(project_id) is None:
        raise NotFoundError("Project not found.")
    record = db.get_transcript(project_id)
    if record is None:
        raise ClipperError("The transcript is not ready yet.")
    path = Path(record["json_path"])
    if not path.is_file():
        raise ClipperError("The transcript file is missing.")
    try:
        return TranscriptOut.model_validate(storage_service.read_json(path))
    except ValidationError as exc:
        raise ClipperError("The saved transcript could not be read.") from exc


@router.get("/{project_id}/media")
def get_media(project_id: str) -> FileResponse:
    project_id = storage_service.assert_project_id(project_id)
    row = db.get_project(project_id)
    if row is None or not row.get("stored_path"):
        raise NotFoundError("Media file not found.")
    path = Path(row["stored_path"]).resolve()
    root = get_settings().data_dir.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise NotFoundError("Media file not found.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.post("/{project_id}/process", response_model=ProjectOut)
def process_project(project_id: str) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("Project not found.")
    has_file = bool(row.get("stored_path")) and Path(row["stored_path"]).is_file()
    if not has_file:
        if not row.get("source_url"):
            raise InvalidMediaError("The source video file is missing.")
        job_manager.enqueue(project_id)
        return _project(project_id)
    if not row.get("has_audio"):
        raise AudioTrackMissingError("This video has no audio track to transcribe.")
    job_manager.enqueue(project_id)
    return _project(project_id)


@router.post("/{project_id}/highlights", response_model=ProjectOut, status_code=202)
def start_highlights(project_id: str) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("Project not found.")
    if not row.get("has_transcript"):
        raise ClipperError("Transcribe the video before looking for highlights.")
    job_manager.enqueue(project_id, kind="highlight")
    return _project(project_id)


@router.get("/{project_id}/highlights", response_model=list[ClipOut])
def list_highlights(project_id: str) -> list[dict]:
    project_id = storage_service.assert_project_id(project_id)
    if db.get_project(project_id) is None:
        raise NotFoundError("Project not found.")
    return [clip_to_dict(row) for row in db.list_clips(project_id)]


@router.post("/{project_id}/previews", response_model=ProjectOut, status_code=202)
def start_previews(project_id: str, body: PreviewIn | None = None) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("Project not found.")
    if not db.list_clips(project_id):
        raise ClipperError("Find highlights before building a preview.")
    clip_id = body.clip_id if body else None
    if clip_id is not None and db.get_clip(project_id, clip_id) is None:
        raise NotFoundError("Clip not found.")
    job_manager.enqueue(project_id, kind="preview", target_id=clip_id)
    return _project(project_id)


@router.post("/{project_id}/exports", response_model=ProjectOut, status_code=202)
def start_export(project_id: str, body: ExportIn) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    if db.get_project(project_id) is None:
        raise NotFoundError("Project not found.")
    clip = db.get_clip(project_id, body.clip_id)
    if clip is None:
        raise NotFoundError("Clip not found.")
    if clip.get("render_status") not in {"approved", "exported"}:
        raise ClipperError("Approve the preview before exporting the full short.")
    job_manager.enqueue(project_id, kind="export", target_id=body.clip_id)
    return _project(project_id)


@router.post("/{project_id}/clips/{clip_id}/crop", response_model=ClipOut)
def update_crop(project_id: str, clip_id: str, body: CropIn) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    if body.offset < -1 or body.offset > 1:
        raise ClipperError("The crop offset has to stay between -1 and 1.")
    previous = db.set_clip_framing(
        project_id,
        clip_id,
        offset=body.offset,
        use_manual=not body.use_detector,
    )
    for path in previous.values():
        rendering_service.delete_owned(path)
    clip = db.get_clip(project_id, clip_id)
    if clip is None:
        raise NotFoundError("Clip not found.")
    return clip_to_dict(clip)


@router.post("/{project_id}/clips/{clip_id}/approve", response_model=ClipOut)
def approve_clip(project_id: str, clip_id: str) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    clip = db.get_clip(project_id, clip_id)
    if clip is None:
        raise NotFoundError("Clip not found.")
    preview = clip.get("preview_path")
    if clip.get("render_status") != "preview_ready" or not preview or not Path(str(preview)).is_file():
        raise ClipperError("Build a low-resolution preview before approving this short.")
    db.approve_clip(project_id, clip_id)
    updated = db.get_clip(project_id, clip_id)
    if updated is None:
        raise NotFoundError("Clip not found.")
    return clip_to_dict(updated)


@router.get("/{project_id}/clips/{clip_id}/preview")
def get_preview(project_id: str, clip_id: str) -> FileResponse:
    return _clip_media(project_id, clip_id, "preview_path", get_settings().data_dir)


@router.get("/{project_id}/clips/{clip_id}/export")
def get_export(project_id: str, clip_id: str) -> FileResponse:
    return _clip_media(project_id, clip_id, "export_path", get_settings().output_dir())


@router.post("/{project_id}/metadata", response_model=ProjectOut, status_code=202)
def start_metadata(project_id: str, body: PreviewIn | None = None) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    if db.get_project(project_id) is None:
        raise NotFoundError("Project not found.")
    clip_id = body.clip_id if body else None
    if clip_id is not None and db.get_clip(project_id, clip_id) is None:
        raise NotFoundError("Clip not found.")
    if not db.list_clips(project_id):
        raise ClipperError("Find a short before drafting titles and a thumbnail.")
    job_manager.enqueue(project_id, kind="metadata", target_id=clip_id)
    return _project(project_id)


@router.get("/{project_id}/metadata", response_model=list[MetadataOut])
def get_metadata(project_id: str) -> list[dict]:
    project_id = storage_service.assert_project_id(project_id)
    if db.get_project(project_id) is None:
        raise NotFoundError("Project not found.")
    return [metadata_to_dict(row) for row in db.list_metadata(project_id)]


@router.put("/{project_id}/clips/{clip_id}/metadata", response_model=MetadataOut)
def update_metadata(project_id: str, clip_id: str, body: MetadataIn) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    clip = db.get_clip(project_id, clip_id)
    if clip is None:
        raise NotFoundError("Clip not found.")
    previous = db.get_metadata(project_id, clip_id)
    if previous is None or not previous.get("frame_path"):
        raise ClipperError("Draft the thumbnail before editing this package.")
    draft = metadata_service.edit_metadata(body.model_dump(), clip, previous)
    frame = Path(str(previous["frame_path"]))
    thumb = Path(str(previous["thumbnail_path"]))
    meta = Path(str(previous["metadata_path"]))
    if not frame.is_file():
        raise ClipperError("The thumbnail frame is missing. Draft it again.")
    alignment = 2
    plan_path = clip.get("crop_path")
    if plan_path and Path(str(plan_path)).is_file():
        plan = storage_service.read_json(Path(str(plan_path)))
        alignment = int(plan.get("caption_alignment") or 2)
    thumbnail_service.draw_headline(frame, thumb, draft["headline"], alignment=alignment)
    thumbnail_service.write_metadata_file(meta, draft)
    draft["thumbnail_path"] = str(thumb.resolve())
    draft["frame_path"] = str(frame.resolve())
    draft["metadata_path"] = str(meta.resolve())
    db.save_metadata(clip_id, project_id, draft)
    thumbnail_service.publish(project_id, int(clip["ordinal"]), thumb, meta)
    saved = db.get_metadata(project_id, clip_id)
    if saved is None:
        raise NotFoundError("Clip not found.")
    return metadata_to_dict(saved)


@router.get("/{project_id}/clips/{clip_id}/thumbnail")
def get_thumbnail(project_id: str, clip_id: str) -> FileResponse:
    project_id = storage_service.assert_project_id(project_id)
    saved = db.get_metadata(project_id, clip_id)
    if saved is None or not saved.get("thumbnail_path"):
        raise NotFoundError("That thumbnail is not ready.")
    path = Path(str(saved["thumbnail_path"])).resolve()
    root = get_settings().data_dir.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise NotFoundError("That thumbnail is not ready.")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/{project_id}/cancel", response_model=ProjectOut, status_code=202)
def cancel_project(project_id: str) -> dict:
    project_id = storage_service.assert_project_id(project_id)
    job_manager.request_cancel(project_id)
    return _project(project_id)


def _clip_media(project_id: str, clip_id: str, field: str, root: Path) -> FileResponse:
    project_id = storage_service.assert_project_id(project_id)
    clip = db.get_clip(project_id, clip_id)
    if clip is None or not clip.get(field):
        raise NotFoundError("That video is not ready.")
    path = Path(str(clip[field])).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise NotFoundError("That video is not ready.")
    return FileResponse(path, media_type="video/mp4")


def _project(project_id: str) -> dict:
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("Project not found.")
    return project_to_dict(row)


def _too_large(limit: int) -> str:
    return f"File exceeds the upload limit of {limit} bytes."


def _mark_failed(project_id: str, message: str) -> None:
    try:
        db.fail_project(project_id, message)
    except Exception:
        logger.exception("Could not record a failed upload for %s", project_id)
