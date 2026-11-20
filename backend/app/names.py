"""Display names taken from the upload. No path components survive."""

from __future__ import annotations

from pathlib import Path

from app.errors import ClipperError


def clean_filename(name: str | None) -> str:
    base = Path(name or "video.mp4").name.replace("\x00", "").strip()
    return base[:180] or "video.mp4"


def resolve_title(title: str, filename: str) -> str:
    chosen = " ".join(title.split())
    if not chosen:
        chosen = " ".join(Path(filename).stem.split())[:120] or "Untitled video"
    if len(chosen) > 120:
        raise ClipperError("Title must be 120 characters or fewer.")
    return chosen
