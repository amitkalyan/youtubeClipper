"""FFprobe and audio extraction. Video bytes stay in the FFmpeg process."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from app.config import get_settings, project_root
from app.errors import (
    AudioTrackMissingError,
    CancelledError,
    FFmpegNotFoundError,
    InvalidMediaError,
)

logger = logging.getLogger("clipper.video")


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    has_audio: bool
    has_video: bool
    file_size_bytes: int


def hidden_window_flag() -> int:
    if os.name == "nt":
        return subprocess.CREATE_NO_WINDOW
    return 0


def resolve_binary(explicit: str | None, tool: str) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FFmpegNotFoundError(f"{tool} was not found at {explicit}.")
        return str(path)
    suffix = ".exe" if os.name == "nt" else ""
    bundled = project_root() / "tools" / "ffmpeg" / f"{tool}{suffix}"
    if bundled.is_file():
        return str(bundled)
    return tool


def resolve_ffmpeg() -> str:
    return resolve_binary(get_settings().ffmpeg_path, "ffmpeg")


def resolve_ffprobe() -> str:
    return resolve_binary(get_settings().ffprobe_path, "ffprobe")


def tool_status(tool: str) -> dict:
    settings = get_settings()
    explicit = settings.ffmpeg_path if tool == "ffmpeg" else settings.ffprobe_path
    try:
        command = resolve_binary(explicit, tool)
    except FFmpegNotFoundError:
        return {"available": False, "path": explicit or tool, "version": None}
    try:
        proc = subprocess.run(
            [command, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=hidden_window_flag(),
        )
    except FileNotFoundError:
        return {"available": False, "path": command, "version": None}
    if proc.returncode != 0:
        return {"available": False, "path": command, "version": None}
    lines = (proc.stdout or proc.stderr or "").splitlines()
    version = lines[0].strip() if lines else None
    return {"available": True, "path": command, "version": version}


def assert_tools_available() -> None:
    missing = [
        name
        for name in ("ffmpeg", "ffprobe")
        if not tool_status(name)["available"]
    ]
    if missing:
        joined = " and ".join(missing)
        raise FFmpegNotFoundError(
            f"Could not run {joined}. Run scripts\\fetch-ffmpeg.ps1 or set FFMPEG_PATH and FFPROBE_PATH."
        )


def probe(path: Path) -> MediaInfo:
    command = [
        resolve_ffprobe(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=hidden_window_flag(),
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "Could not run ffprobe. Run scripts\\fetch-ffmpeg.ps1 or set FFPROBE_PATH."
        ) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[-600:]
        raise InvalidMediaError(f"Could not read this file as media. {detail}".strip())
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise InvalidMediaError("FFprobe returned data that was not JSON.") from exc

    streams = payload.get("streams") or []
    video = next((stream for stream in streams if _is_real_video(stream)), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    fmt = payload.get("format") or {}
    duration = _float(fmt.get("duration"))
    if duration is None and video is not None:
        duration = _float(video.get("duration"))
    if duration is None and audio is not None:
        duration = _float(audio.get("duration"))
    return MediaInfo(
        duration_seconds=duration or 0.0,
        width=_int(video.get("width")) if video else None,
        height=_int(video.get("height")) if video else None,
        fps=_fps((video or {}).get("avg_frame_rate") or (video or {}).get("r_frame_rate")),
        video_codec=(video or {}).get("codec_name") if video else None,
        audio_codec=(audio or {}).get("codec_name") if audio else None,
        sample_rate=_int((audio or {}).get("sample_rate")) if audio else None,
        channels=_int((audio or {}).get("channels")) if audio else None,
        has_audio=audio is not None,
        has_video=video is not None,
        file_size_bytes=path.stat().st_size if path.is_file() else 0,
    )


def run_ffmpeg(
    args: list[str],
    *,
    should_cancel: Callable[[], bool],
    output: Path,
    cwd: Path | None = None,
    cancelled_message: str = "Cancelled during rendering.",
) -> None:
    """Run one FFmpeg process. The picture stays in that process."""
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path = output.with_suffix(output.suffix + ".log")
    command = [resolve_ffmpeg(), "-nostdin", "-y", "-hide_banner", "-loglevel", "error", *args]
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
                cwd=str(cwd) if cwd is not None else None,
                creationflags=hidden_window_flag(),
            )
        except FileNotFoundError as exc:
            raise FFmpegNotFoundError(
                "Could not run ffmpeg. Run scripts\\fetch-ffmpeg.ps1 or set FFMPEG_PATH."
            ) from exc
        while proc.poll() is None:
            if should_cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                output.unlink(missing_ok=True)
                log_path.unlink(missing_ok=True)
                raise CancelledError(cancelled_message)
            time.sleep(0.4)
        code = proc.returncode
    sequence = "%" in output.name
    if sequence:
        prefix = output.name.split("%", 1)[0]
        produced = code == 0 and any(output.parent.glob(prefix + "*.jpg"))
    else:
        produced = code == 0 and output.is_file() and output.stat().st_size > 0
    if not produced:
        detail = ""
        if log_path.is_file():
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-600:]
        log_path.unlink(missing_ok=True)
        if not sequence:
            output.unlink(missing_ok=True)
        logger.warning("FFmpeg failed: %s", detail.strip())
        raise InvalidMediaError(f"FFmpeg could not finish this clip. {detail}".strip())
    log_path.unlink(missing_ok=True)


def extract_audio(source: Path, dest: Path, *, should_cancel: Callable[[], bool]) -> None:
    """Write 16 kHz mono PCM. `-vn` keeps the picture out of this Python process."""
    info = probe(source)
    if not info.has_audio:
        raise AudioTrackMissingError("This video has no audio track to transcribe.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    log_path = dest.with_suffix(".log")
    command = [
        resolve_ffmpeg(),
        "-nostdin",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
                creationflags=hidden_window_flag(),
            )
        except FileNotFoundError as exc:
            raise FFmpegNotFoundError(
                "Could not run ffmpeg. Run scripts\\fetch-ffmpeg.ps1 or set FFMPEG_PATH."
            ) from exc
        while proc.poll() is None:
            if should_cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                dest.unlink(missing_ok=True)
                raise CancelledError("Cancelled during audio extraction.")
            time.sleep(0.4)
        code = proc.returncode
    if code != 0 or not dest.is_file() or dest.stat().st_size == 0:
        detail = ""
        if log_path.is_file():
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-600:]
        log_path.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        logger.warning("Audio extraction failed for %s: %s", source.name, detail.strip())
        raise InvalidMediaError(
            "Audio extraction failed. The file may use an unsupported audio track. "
            + detail.strip()
        )
    log_path.unlink(missing_ok=True)


def _is_real_video(stream: dict) -> bool:
    if stream.get("codec_type") != "video":
        return False
    disposition = stream.get("disposition") or {}
    return disposition.get("attached_pic") != 1


def _float(value: object) -> float | None:
    if value is None or value == "N/A":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    if value is None or value == "N/A":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fps(value: object) -> float | None:
    if not isinstance(value, str) or not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        except ValueError:
            return None
    return _float(value)
