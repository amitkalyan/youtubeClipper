"""Download one public YouTube video to disk. The file is never held in Python."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import ALLOWED_EXTENSIONS, get_settings
from app.errors import CancelledError, ClipperError, InvalidMediaError, UploadTooLargeError
from app.services import storage_service
from app.services.video_service import hidden_window_flag, resolve_ffmpeg

logger = logging.getLogger("clipper.youtube")

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {"youtube.com", "youtube-nocookie.com", "youtu.be", "music.youtube.com"}
_PROGRESS = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
_FORMAT = (
    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
    "b[height<=1080][ext=mp4]/"
    "bv*[height<=720]+ba/"
    "b[height<=720]"
)


def parse_youtube_url(value: str) -> str:
    text = (value or "").strip()
    if not text or len(text) > 500:
        raise InvalidMediaError("Enter one YouTube video link.")
    if not re.match(r"^https?://", text, re.IGNORECASE):
        lowered = text.lower()
        if lowered.startswith("youtu.be/") or "youtube.com" in lowered or "youtube-nocookie.com" in lowered:
            text = "https://" + text
        else:
            raise InvalidMediaError("Enter a YouTube link, such as https://www.youtube.com/watch?v=…")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise InvalidMediaError("Enter a normal https YouTube link.")
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host not in _HOSTS:
        raise InvalidMediaError("Enter a YouTube link. Other websites are not downloaded.")
    video_id = _video_id(host, parsed.path, parse_qs(parsed.query))
    if video_id is None:
        raise InvalidMediaError(
            "That link does not point at one video. Channel pages and playlists are not downloaded."
        )
    return video_id


def canonical_url(video_id: str) -> str:
    if not _VIDEO_ID.fullmatch(video_id):
        raise InvalidMediaError("Enter one YouTube video link.")
    return f"https://www.youtube.com/watch?v={video_id}"


def download_video(
    url: str,
    project_id: str,
    *,
    should_cancel: Callable[[], bool],
    on_progress: Callable[[float, str], None],
) -> tuple[Path, str]:
    video_id = parse_youtube_url(url)
    watch = canonical_url(video_id)
    destination = storage_service.project_dir(project_id)
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / "work" / "download"
    temporary.mkdir(parents=True, exist_ok=True)
    _delete_sources(destination)
    _check(should_cancel)
    on_progress(0.0, "Reading the YouTube video.")
    title = _remote_title(watch, should_cancel)
    on_progress(0.05, f"Downloading {title[:80]}")
    command = build_download_command(watch, destination, temporary)
    logger.info("Downloading YouTube video id=%s project=%s", video_id, project_id)
    try:
        _run_download(command, destination, should_cancel, on_progress)
    except CancelledError:
        _delete_sources(destination)
        _clear_tree(temporary)
        raise
    except ClipperError:
        _delete_sources(destination)
        _clear_tree(temporary)
        raise
    saved = _finished_file(destination)
    _clear_tree(temporary)
    limit = get_settings().max_upload_bytes
    if saved.stat().st_size > limit:
        saved.unlink(missing_ok=True)
        raise UploadTooLargeError(f"That video is larger than the {limit} byte limit.")
    on_progress(1.0, "Download finished.")
    return saved, title


def build_download_command(url: str, destination: Path, temporary: Path) -> list[str]:
    ffmpeg = resolve_ffmpeg()
    ffmpeg_location = str(Path(ffmpeg).parent) if Path(ffmpeg).is_file() else ffmpeg
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "--restrict-filenames",
        "--windows-filenames",
        "--merge-output-format",
        "mp4",
        "--concurrent-fragments",
        "1",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--socket-timeout",
        "30",
        "--max-filesize",
        str(get_settings().max_upload_bytes),
        "--ffmpeg-location",
        ffmpeg_location,
        "-f",
        _FORMAT,
        "-o",
        "source.%(ext)s",
        "--paths",
        str(destination),
        "--paths",
        f"temp:{temporary}",
        "--no-write-subs",
        "--no-write-auto-subs",
        "--no-embed-subs",
        "--no-write-thumbnail",
        url,
    ]


def progress_ratio(line: str) -> float | None:
    match = _PROGRESS.search(line)
    if match is None:
        return None
    return max(0.0, min(1.0, float(match.group(1)) / 100))


def _video_id(host: str, path: str, query: dict[str, list[str]]) -> str | None:
    raw = ""
    if host == "youtu.be":
        raw = path.strip("/").split("/")[0]
    elif query.get("v"):
        raw = query["v"][0]
    else:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v", "watch"}:
            raw = parts[1]
    if not _VIDEO_ID.fullmatch(raw):
        return None
    return raw


def _remote_title(url: str, should_cancel: Callable[[], bool]) -> str:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--skip-download",
        "--no-warnings",
        "--no-progress",
        "--print",
        "LIVE=%(is_live)s",
        "--print",
        "TITLE=%(title)s",
        url,
    ]
    output = _capture(command, should_cancel)
    live = ""
    title_lines: list[str] = []
    for line in output.splitlines():
        if line.startswith("LIVE="):
            live = line[5:].strip()
        elif line.startswith("TITLE="):
            title_lines.append(line[6:])
        elif title_lines:
            title_lines.append(line)
    if live.lower() in {"true", "yes"}:
        raise InvalidMediaError("Live streams are not downloaded. Upload a finished video file instead.")
    cleaned = " ".join(" ".join(title_lines).split())
    return cleaned[:120] or "YouTube video"


def _capture(command: list[str], should_cancel: Callable[[], bool]) -> str:
    _check(should_cancel)
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=90,
            creationflags=hidden_window_flag(),
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidMediaError("YouTube did not answer in time. Try the link again, or upload a file.") from exc
    except FileNotFoundError as exc:
        raise ClipperError("Python could not start the YouTube downloader.") from exc
    if proc.returncode != 0:
        raise InvalidMediaError(_public_error(f"{proc.stdout}\n{proc.stderr}"))
    output = proc.stdout or ""
    if "TITLE=" not in output and "LIVE=" not in output:
        raise InvalidMediaError("YouTube did not return a video for that link.")
    return output


def _run_download(
    command: list[str],
    destination: Path,
    should_cancel: Callable[[], bool],
    on_progress: Callable[[float, str], None],
) -> None:
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=hidden_window_flag(),
        )
    except FileNotFoundError as exc:
        raise ClipperError("Python could not start the YouTube downloader.") from exc
    collected: list[str] = []
    limit = get_settings().max_upload_bytes
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if should_cancel():
                _stop(proc)
                raise CancelledError("Cancelled.")
            if _largest_partial(destination) > limit:
                _stop(proc)
                raise UploadTooLargeError(f"That video is larger than the {limit} byte limit.")
            text = line.strip()
            if text:
                collected.append(text)
                if len(collected) > 40:
                    collected = collected[-20:]
            ratio = progress_ratio(line)
            if ratio is not None:
                on_progress(ratio, f"Downloading {int(ratio * 100)}%.")
        code = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            _stop(proc)
    if code != 0:
        logger.warning("yt-dlp failed: %s", " | ".join(collected[-8:]))
        raise InvalidMediaError(_public_error("\n".join(collected)))


def _public_error(output: str) -> str:
    lowered = output.lower()
    if "no module named yt_dlp" in lowered:
        return "YouTube downloads need yt-dlp. Install the backend requirements and restart the API."
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        return "YouTube refused this download. Upload a file you already have instead."
    if "private video" in lowered:
        return "That video is private."
    if "video unavailable" in lowered or "this video is unavailable" in lowered:
        return "That YouTube video is unavailable."
    if "live event" in lowered or "is live" in lowered:
        return "Live streams are not downloaded. Upload a finished video file instead."
    if "file is larger than max-filesize" in lowered or "max-filesize" in lowered:
        limit = get_settings().max_upload_bytes
        return f"That video is larger than the {limit} byte limit."
    return "Could not download that YouTube video. Check the link, or upload the file instead."


def _finished_file(destination: Path) -> Path:
    files = [
        path
        for path in destination.glob("source.*")
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS and not path.name.endswith(".part")
    ]
    if not files:
        raise InvalidMediaError("The download finished without a video file.")
    mp4 = [path for path in files if path.suffix.lower() == ".mp4"]
    chosen = max(mp4 or files, key=lambda path: path.stat().st_size)
    for extra in destination.glob("source.*"):
        if extra != chosen:
            extra.unlink(missing_ok=True)
    return chosen


def _largest_partial(destination: Path) -> int:
    size = 0
    for path in destination.glob("source.*"):
        try:
            size = max(size, path.stat().st_size)
        except OSError:
            continue
    work = destination / "work" / "download"
    if work.is_dir():
        for path in work.rglob("*"):
            if path.is_file():
                try:
                    size = max(size, path.stat().st_size)
                except OSError:
                    continue
    return size


def _delete_sources(destination: Path) -> None:
    for path in destination.glob("source.*"):
        path.unlink(missing_ok=True)


def _clear_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _check(should_cancel: Callable[[], bool]) -> None:
    if should_cancel():
        raise CancelledError("Cancelled.")
