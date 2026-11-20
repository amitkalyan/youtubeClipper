"""One JPEG thumbnail. A single frame is written to disk, then Pillow draws the headline.

No image-generation model is called.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.errors import ClipperError
from app.services import storage_service, video_service
from app.services.rendering_service import _source_segments, crop_window

THUMB_SIZE = (1080, 1920)


def grab_frame(source: Path, dest: Path, clip: dict, *, should_cancel) -> dict:
    """Write one JPEG at the middle of the clip and return the crop window used."""
    segments = _source_segments(clip)
    duration = sum(segment["end"] - segment["start"] for segment in segments)
    moment = _moment_in_source(segments, duration / 2)
    window = _window_for(clip)
    width, height = THUMB_SIZE
    if window.get("mode") == "pad":
        video = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=bilinear,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        )
    else:
        video = (
            f"crop={int(window['w'])}:{int(window['h'])}:{int(window['x'])}:{int(window['y'])},"
            f"scale={width}:{height}:flags=bilinear"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    video_service.run_ffmpeg(
        [
            "-ss",
            f"{moment:.3f}",
            "-i",
            str(source),
            "-an",
            "-frames:v",
            "1",
            "-vf",
            video,
            "-q:v",
            "3",
            str(dest),
        ],
        should_cancel=should_cancel,
        output=dest,
        cancelled_message="Cancelled while grabbing the thumbnail frame.",
    )
    return window


def _moment_in_source(segments: list[dict], offset: float) -> float:
    cursor = 0.0
    for segment in segments:
        length = segment["end"] - segment["start"]
        if offset <= cursor + length:
            return segment["start"] + max(0.0, offset - cursor)
        cursor += length
    return segments[-1]["end"]


def draw_headline(frame: Path, dest: Path, headline: str, *, alignment: int = 2) -> None:
    image = Image.open(frame).convert("RGB")
    try:
        canvas = image.convert("RGBA")
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        width, height = canvas.size
        font = _font(max(28, height // 18))
        lines = _wrap(draw, headline, font, width - 120)[:3]
        line_height = font.size + 8
        block = line_height * len(lines)
        if alignment == 8:
            top = 80
        else:
            top = height - block - max(80, height // 10)
        draw.rectangle((0, top - 24, width, top + block + 24), fill=(0, 0, 0, 150))
        for index, line in enumerate(lines):
            text_width = draw.textlength(line, font=font)
            x = max(40, (width - text_width) / 2)
            y = top + index * line_height
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        composed = Image.alpha_composite(canvas, overlay).convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        composed.save(dest, format="JPEG", quality=85)
    finally:
        image.close()


def write_metadata_file(path: Path, payload: dict) -> None:
    body = {
        "titles": payload["titles"],
        "selected_title": payload["selected_title"],
        "description": payload["description"],
        "hashtags": payload["hashtags"],
        "headline": payload["headline"],
        "cta": payload["cta"],
        "category": payload["category"],
        "keywords": payload["keywords"],
        "image_model": "off",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def publish(project_id: str, ordinal: int, thumbnail: Path | None, metadata_file: Path | None) -> None:
    folder = get_settings().output_dir() / project_id / f"clip_{int(ordinal) + 1:03d}"
    if not (folder / "short.mp4").is_file():
        return
    if thumbnail and thumbnail.is_file():
        shutil.copyfile(thumbnail, folder / "thumbnail.jpg")
    if metadata_file and metadata_file.is_file():
        shutil.copyfile(metadata_file, folder / "metadata.json")


def package_dir(project_id: str) -> Path:
    return storage_service.project_dir(project_id) / "work" / "package"


def _window_for(clip: dict) -> dict:
    raw = clip.get("crop_path")
    if raw and Path(str(raw)).is_file():
        plan = storage_service.read_json(Path(str(raw)))
        encode = plan.get("encode")
        if isinstance(encode, dict) and {"x", "y", "w", "h", "mode"} <= set(encode):
            encode["caption_alignment"] = int(plan.get("caption_alignment") or 2)
            return encode
    row_width = int(clip.get("source_width") or 0)
    row_height = int(clip.get("source_height") or 0)
    if row_width < 2 or row_height < 2:
        raise ClipperError("The source video has no usable picture size.")
    return crop_window(
        row_width,
        row_height,
        face_x=None,
        face_y=None,
        face=False,
        use_manual=bool(clip.get("use_manual")),
        manual_offset=float(clip.get("manual_offset") or 0),
    )


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for candidate in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split() or ["Short"]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
