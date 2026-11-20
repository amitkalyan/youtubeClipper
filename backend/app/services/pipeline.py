"""Phase 1 stages: probe, extract audio, transcribe, save, unload."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from app import db
from app.errors import AudioTrackMissingError, CancelledError, ClipperError, NotFoundError
from app.names import resolve_title
from app.services import (
    highlight_service,
    metadata_service,
    ollama_service,
    rendering_service,
    storage_service,
    thumbnail_service,
    transcription_service,
    video_service,
    youtube_service,
)

logger = logging.getLogger("clipper.pipeline")


def run_phase1(
    project_id: str,
    job_id: str,
    should_cancel: Callable[[], bool],
) -> None:
    started = time.perf_counter()
    try:
        _check(should_cancel)
        row = db.get_project(project_id)
        if row is None:
            raise NotFoundError("Project not found.")
        source = _ensure_source(project_id, job_id, row, should_cancel)
        db.set_progress(
            project_id,
            job_id,
            project_status="extracting_audio",
            job_status="running",
            stage="extract_audio",
            progress=10,
            message="Extracting a 16 kHz mono audio track.",
        )
        logger.info("Extracting audio project=%s", project_id)
        _check(should_cancel)
        info = video_service.probe(source)
        db.update_source_metadata(project_id, info)
        if not info.has_audio:
            raise AudioTrackMissingError("This video has no audio track to transcribe.")
        audio = storage_service.audio_path(project_id)
        video_service.extract_audio(source, audio, should_cancel=should_cancel)
        _check(should_cancel)
        db.set_progress(
            project_id,
            job_id,
            project_status="transcribing",
            job_status="running",
            stage="transcribe",
            progress=32,
            message="Loading the speech model. The first run downloads the base model.",
        )
        logger.info("Transcribing project=%s duration=%.1f", project_id, info.duration_seconds)

        def on_progress(ratio: float, message: str) -> None:
            db.set_progress(
                project_id,
                job_id,
                project_status="transcribing",
                job_status="running",
                stage="transcribe",
                progress=35 + max(0.0, min(1.0, ratio)) * 60,
                message=message,
            )

        document = transcription_service.transcribe_file(
            audio,
            media_duration=info.duration_seconds,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        _check(should_cancel)
        db.set_progress(
            project_id,
            job_id,
            project_status="transcribing",
            job_status="running",
            stage="save",
            progress=96,
            message="Saving the transcript.",
        )
        path = storage_service.transcript_path(project_id)
        storage_service.write_json(path, document)
        preview = (document.get("text") or "").strip()
        if len(preview) > 240:
            preview = preview[:237] + "..."
        duration = document.get("duration")
        db.upsert_transcript(
            project_id,
            language=document.get("language"),
            model=str(document.get("model") or "base"),
            duration_seconds=float(duration) if duration is not None else None,
            segment_count=len(document.get("segments") or []),
            sentence_count=len(document.get("sentences") or []),
            json_path=str(path),
            text_preview=preview,
        )
        message = _cut_shorts(project_id, job_id, document, should_cancel)
        db.complete_job(project_id, job_id, message=message)
        logger.info(
            "Transcript ready project=%s sentences=%s elapsed=%.1fs",
            project_id,
            len(document.get("sentences") or []),
            time.perf_counter() - started,
        )
    except CancelledError as exc:
        db.cancel_job(project_id, job_id, message=str(exc) or "Cancelled.")
        logger.info("Cancelled project=%s", project_id)
    except ClipperError as exc:
        db.fail_job(project_id, job_id, error=str(exc))
        logger.warning("Job failed project=%s error=%s", project_id, exc)
    except Exception:
        logger.exception("Unexpected job failure project=%s", project_id)
        db.fail_job(
            project_id,
            job_id,
            error="Unexpected error during processing. See data/logs/app.log.",
        )


def run_highlights(
    project_id: str,
    job_id: str,
    should_cancel: Callable[[], bool],
) -> None:
    try:
        _check(should_cancel)
        row = db.get_project(project_id)
        record = db.get_transcript(project_id)
        if row is None or record is None:
            raise ClipperError("Transcribe the video before looking for highlights.")
        path = Path(record["json_path"])
        if not path.is_file():
            raise ClipperError("The transcript file is missing.")
        document = storage_service.read_json(path)
        db.set_progress(
            project_id,
            job_id,
            project_status="analyzing",
            job_status="running",
            stage="highlight",
            progress=5,
            message="Reading the saved transcript. Whisper stays unloaded.",
        )

        def on_progress(ratio: float, message: str) -> None:
            db.set_progress(
                project_id,
                job_id,
                project_status="analyzing",
                job_status="running",
                stage="highlight",
                progress=8 + max(0.0, min(1.0, ratio)) * 87,
                message=message,
            )

        clips = highlight_service.find_clips(
            document,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        _check(should_cancel)
        db.replace_clips(project_id, clips)
        if not clips:
            message = "The spoken audio is under 20 seconds, so there is no other speech to add."
        else:
            message = _finish_previews(project_id, job_id, len(clips), should_cancel)
        db.complete_job(project_id, job_id, message=message)
        logger.info("Highlights ready project=%s clips=%s", project_id, len(clips))
    except CancelledError as exc:
        db.cancel_highlight(project_id, job_id, message=str(exc) or "Highlight detection cancelled.")
        logger.info("Highlight cancelled project=%s", project_id)
    except ClipperError as exc:
        db.fail_highlight(project_id, job_id, error=str(exc))
        logger.warning("Highlight failed project=%s error=%s", project_id, exc)
    except Exception:
        logger.exception("Unexpected highlight failure project=%s", project_id)
        db.fail_highlight(
            project_id,
            job_id,
            error="Highlight detection failed. The transcript was kept. See data/logs/app.log.",
        )


def run_metadata(
    project_id: str,
    job_id: str,
    should_cancel: Callable[[], bool],
) -> None:
    try:
        _check(should_cancel)
        row = db.get_project(project_id)
        if row is None:
            raise NotFoundError("Project not found.")
        source = Path(row["stored_path"]) if row.get("stored_path") else None
        if source is None or not source.is_file():
            raise ClipperError("The source video file is missing.")
        width = int(row.get("width") or 0)
        height = int(row.get("height") or 0)
        if width < 2 or height < 2:
            info = video_service.probe(source)
            width = int(info.width or 0)
            height = int(info.height or 0)
        job = db.get_job(job_id) or {}
        target = job.get("target_id")
        clips = db.list_clips(project_id)
        if target:
            clips = [clip for clip in clips if clip["id"] == target]
        if not clips:
            raise ClipperError("Find a short before drafting titles and a thumbnail.")
        total = len(clips)
        try:
            for index, clip in enumerate(clips):
                _check(should_cancel)
                db.set_progress(
                    project_id,
                    job_id,
                    project_status="packaging",
                    job_status="running",
                    stage="metadata",
                    progress=5 + (index / total) * 90,
                    message=f"Drafting the title and thumbnail ({index + 1} of {total}).",
                )
                text = ollama_service.chat(
                    metadata_service.prompt_for(clip),
                    should_cancel=should_cancel,
                    keep_alive=0 if index == total - 1 else "10m",
                    system=metadata_service.system_prompt(),
                )
                _store_package(project_id, clip, text, source, width, height, should_cancel)
        finally:
            ollama_service.unload()
        label = "short" if total == 1 else "shorts"
        db.complete_job(project_id, job_id, message=f"Titles and thumbnails are ready for {total} {label}.")
        logger.info("Metadata ready project=%s clips=%s", project_id, total)
    except CancelledError as exc:
        db.cancel_render(project_id, job_id, message=str(exc) or "Metadata drafting cancelled.")
        logger.info("Metadata cancelled project=%s", project_id)
    except ClipperError as exc:
        db.fail_render(project_id, job_id, error=str(exc))
        logger.warning("Metadata failed project=%s error=%s", project_id, exc)
    except Exception:
        logger.exception("Unexpected metadata failure project=%s", project_id)
        db.fail_render(
            project_id,
            job_id,
            error="Titles and the thumbnail were not saved. The transcript was kept. See data/logs/app.log.",
        )


def _store_package(
    project_id: str,
    clip: dict,
    raw_text: str,
    source: Path,
    width: int,
    height: int,
    should_cancel: Callable[[], bool],
) -> None:
    draft = metadata_service.draft_metadata(raw_text, clip)
    label = f"clip_{int(clip['ordinal']) + 1:03d}"
    folder = thumbnail_service.package_dir(project_id)
    frame = folder / f"{label}-frame.jpg"
    thumb = folder / f"{label}.jpg"
    meta = folder / f"{label}.json"
    clip["source_width"] = width
    clip["source_height"] = height
    window = thumbnail_service.grab_frame(source, frame, clip, should_cancel=should_cancel)
    thumbnail_service.draw_headline(
        frame,
        thumb,
        draft["headline"],
        alignment=int(window.get("caption_alignment") or 2),
    )
    thumbnail_service.write_metadata_file(meta, draft)
    draft["thumbnail_path"] = str(thumb.resolve())
    draft["frame_path"] = str(frame.resolve())
    draft["metadata_path"] = str(meta.resolve())
    db.save_metadata(clip["id"], project_id, draft)
    thumbnail_service.publish(project_id, int(clip["ordinal"]), thumb, meta)


def run_preview(
    project_id: str,
    job_id: str,
    should_cancel: Callable[[], bool],
) -> None:
    _run_render(project_id, job_id, should_cancel, export=False)


def run_export(
    project_id: str,
    job_id: str,
    should_cancel: Callable[[], bool],
) -> None:
    _run_render(project_id, job_id, should_cancel, export=True)


def _run_render(
    project_id: str,
    job_id: str,
    should_cancel: Callable[[], bool],
    *,
    export: bool,
) -> None:
    try:
        _check(should_cancel)
        row = db.get_project(project_id)
        if row is None:
            raise NotFoundError("Project not found.")
        source = Path(row["stored_path"]) if row.get("stored_path") else None
        if source is None or not source.is_file():
            raise ClipperError("The source video file is missing.")
        record = db.get_transcript(project_id)
        if record is None:
            raise ClipperError("Transcribe the video before rendering a short.")
        document = storage_service.read_json(Path(record["json_path"]))
        width = int(row.get("width") or 0)
        height = int(row.get("height") or 0)
        if width < 2 or height < 2:
            info = video_service.probe(source)
            width = int(info.width or 0)
            height = int(info.height or 0)
        if width < 2 or height < 2:
            raise ClipperError("The source video has no usable picture size.")
        job = db.get_job(job_id) or {}
        target = job.get("target_id")
        clips = db.list_clips(project_id)
        if target:
            clips = [clip for clip in clips if clip["id"] == target]
        if not clips:
            raise ClipperError("There is no highlight to render.")
        sample_rate = row.get("audio_sample_rate")
        has_audio = bool(row.get("has_audio"))
        total = len(clips)
        for index, clip in enumerate(clips):
            _check(should_cancel)
            if export:
                message = "Exporting the approved short at 1080×1920."
            else:
                message = f"Building a low-resolution preview ({index + 1} of {total})."
            db.set_progress(
                project_id,
                job_id,
                project_status="rendering",
                job_status="running",
                stage="export" if export else "preview",
                progress=5 + (index / total) * 90,
                message=message,
            )
            kwargs = {
                "width": width,
                "height": height,
                "sample_rate": int(sample_rate) if sample_rate else None,
                "has_audio": has_audio,
                "should_cancel": should_cancel,
            }
            if export:
                rendering_service.build_export(project_id, clip, source, document, **kwargs)
                saved = db.get_metadata(project_id, clip["id"])
                if saved:
                    thumbnail_service.publish(
                        project_id,
                        int(clip["ordinal"]),
                        Path(saved["thumbnail_path"]) if saved.get("thumbnail_path") else None,
                        Path(saved["metadata_path"]) if saved.get("metadata_path") else None,
                    )
            else:
                rendering_service.build_preview(project_id, clip, source, document, **kwargs)
        if export:
            done = "The 1080×1920 short is in the output folder."
        else:
            done = "Low-resolution preview is ready. Approve a clip before the full export."
        db.complete_job(project_id, job_id, message=done)
        logger.info("Render finished project=%s export=%s clips=%s", project_id, export, total)
    except CancelledError as exc:
        db.cancel_render(project_id, job_id, message=str(exc) or "Rendering cancelled.")
        logger.info("Render cancelled project=%s", project_id)
    except ClipperError as exc:
        db.fail_render(project_id, job_id, error=str(exc))
        logger.warning("Render failed project=%s error=%s", project_id, exc)
    except Exception:
        logger.exception("Unexpected render failure project=%s", project_id)
        db.fail_render(
            project_id,
            job_id,
            error="Rendering failed. The transcript was kept. See data/logs/app.log.",
        )


def _cut_shorts(
    project_id: str,
    job_id: str,
    document: dict,
    should_cancel: Callable[[], bool],
) -> str:
    """After Whisper is unloaded, choose 20 second to 1 minute moments and preview them."""
    _check(should_cancel)
    db.set_progress(
        project_id,
        job_id,
        project_status="analyzing",
        job_status="running",
        stage="highlight",
        progress=96,
        message="Whisper is unloaded. Choosing moments from 20 seconds to 1 minute.",
    )

    def on_progress(ratio: float, message: str) -> None:
        db.set_progress(
            project_id,
            job_id,
            project_status="analyzing",
            job_status="running",
            stage="highlight",
            progress=96 + max(0.0, min(1.0, ratio)) * 2,
            message=message,
        )

    try:
        clips = highlight_service.find_clips(
            document,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
    except CancelledError:
        raise
    except ClipperError as exc:
        logger.warning("Shorts were not cut project=%s error=%s", project_id, exc)
        return f"Transcript saved. Shorts were not cut yet: {exc}"
    except Exception:
        logger.exception("Short selection failed project=%s", project_id)
        return "Transcript saved. Shorts were not cut yet. See data/logs/app.log."
    _check(should_cancel)
    db.replace_clips(project_id, clips)
    if not clips:
        return "The spoken audio is under 20 seconds, so there is no other speech to add."
    return _finish_previews(
        project_id,
        job_id,
        len(clips),
        should_cancel,
        progress_base=97,
        progress_span=3,
    )


def _finish_previews(
    project_id: str,
    job_id: str,
    clip_count: int,
    should_cancel: Callable[[], bool],
    *,
    progress_base: float = 5,
    progress_span: float = 90,
) -> str:
    try:
        _render_clip_previews(
            project_id,
            job_id,
            should_cancel,
            progress_base=progress_base,
            progress_span=progress_span,
        )
    except CancelledError:
        raise
    except ClipperError as exc:
        logger.warning("Preview failed project=%s error=%s", project_id, exc)
        return f"{clip_count} moments were found, but the preview failed: {exc}"
    except Exception:
        logger.exception("Preview failed project=%s", project_id)
        return f"{clip_count} moments were found, but the preview failed. See data/logs/app.log."
    label = "short" if clip_count == 1 else "shorts"
    return (
        f"{clip_count} {label} ready to review. Each one is 20 seconds to 1 minute. "
        "Approve one to export 1080×1920."
    )


def _render_clip_previews(
    project_id: str,
    job_id: str,
    should_cancel: Callable[[], bool],
    *,
    progress_base: float = 5,
    progress_span: float = 90,
) -> None:
    row = db.get_project(project_id)
    if row is None:
        raise NotFoundError("Project not found.")
    source = Path(row["stored_path"]) if row.get("stored_path") else None
    if source is None or not source.is_file():
        raise ClipperError("The source video file is missing.")
    record = db.get_transcript(project_id)
    if record is None:
        raise ClipperError("The transcript file is missing.")
    document = storage_service.read_json(Path(record["json_path"]))
    width = int(row.get("width") or 0)
    height = int(row.get("height") or 0)
    if width < 2 or height < 2:
        info = video_service.probe(source)
        width = int(info.width or 0)
        height = int(info.height or 0)
    if width < 2 or height < 2:
        raise ClipperError("The source video has no usable picture size.")
    clips = db.list_clips(project_id)
    if not clips:
        raise ClipperError("There is no highlight to render.")
    sample_rate = row.get("audio_sample_rate")
    has_audio = bool(row.get("has_audio"))
    total = len(clips)
    for index, clip in enumerate(clips):
        _check(should_cancel)
        db.set_progress(
            project_id,
            job_id,
            project_status="rendering",
            job_status="running",
            stage="preview",
            progress=progress_base + (index / total) * progress_span,
            message=f"Building a low-resolution preview ({index + 1} of {total}).",
        )
        rendering_service.build_preview(
            project_id,
            clip,
            source,
            document,
            width=width,
            height=height,
            sample_rate=int(sample_rate) if sample_rate else None,
            has_audio=has_audio,
            should_cancel=should_cancel,
        )


def _ensure_source(
    project_id: str,
    job_id: str,
    row: dict,
    should_cancel: Callable[[], bool],
) -> Path:
    stored = row.get("stored_path")
    if stored and Path(stored).is_file():
        return Path(stored)
    url = row.get("source_url")
    if not url:
        raise ClipperError("The source video file is missing.")

    def on_progress(ratio: float, message: str) -> None:
        db.set_progress(
            project_id,
            job_id,
            project_status="downloading",
            job_status="running",
            stage="download",
            progress=2 + max(0.0, min(1.0, ratio)) * 23,
            message=message,
        )

    path, remote_title = youtube_service.download_video(
        str(url),
        project_id,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )
    if (row.get("title") or "") == "YouTube video":
        db.update_project(project_id, title=resolve_title(remote_title, "video.mp4"))
    info = video_service.probe(path)
    if not info.has_video:
        path.unlink(missing_ok=True)
        raise ClipperError("No video stream found in the download.")
    db.save_source(
        project_id,
        original_filename=path.name,
        stored_path=str(path.resolve()),
        info=info,
        file_size=path.stat().st_size,
    )
    if not info.has_audio:
        raise AudioTrackMissingError("This video has no audio track to transcribe.")
    return path


def _check(should_cancel: Callable[[], bool]) -> None:
    if should_cancel():
        raise CancelledError("Cancelled.")
