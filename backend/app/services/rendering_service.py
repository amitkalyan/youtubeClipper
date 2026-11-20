"""Vertical previews and approved exports. Frames are not kept in a list.

A 360 px, 1 fps proxy is written to disk, read one picture at a time, then deleted.
The full 1080x1920 encode runs only after the preview is approved. Zoom stays off.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from app import db
from app.config import get_settings
from app.errors import CancelledError, ClipperError
from app.services import caption_service, storage_service, video_service

logger = logging.getLogger("clipper.render")

PREVIEW_SIZE = (360, 640)
EXPORT_SIZE = (1080, 1920)
AAC_RATES = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}


def crop_window(
    source_w: int,
    source_h: int,
    *,
    face_x: float | None,
    face_y: float | None,
    face: bool,
    use_manual: bool,
    manual_offset: float,
) -> dict:
    if source_w < 2 or source_h < 2:
        raise ClipperError("The source video has no usable picture size.")
    full = {
        "x": 0,
        "y": 0,
        "w": source_w,
        "h": source_h,
        "mode": "pad",
        "face": face,
        "face_y": face_y,
    }
    if source_h * 9 >= source_w * 16:
        return full
    crop_h = _even(source_h)
    crop_w = _even(round(crop_h * 9 / 16))
    if crop_w > source_w:
        return full
    slack = source_w - crop_w
    if use_manual:
        offset = max(-1.0, min(1.0, float(manual_offset)))
        origin = slack / 2 + offset * slack / 2
        mode = "manual"
    elif face and face_x is not None:
        origin = float(face_x) - crop_w / 2
        mode = "face"
    else:
        origin = slack / 2
        mode = "center"
    x = _clamp_even(int(round(origin)), slack)
    return {
        "x": x,
        "y": 0,
        "w": crop_w,
        "h": crop_h,
        "mode": mode,
        "face": face,
        "face_y": face_y,
    }


def build_preview(
    project_id: str,
    clip: dict,
    source: Path,
    transcript: dict,
    *,
    width: int,
    height: int,
    sample_rate: int | None,
    has_audio: bool,
    should_cancel: Callable[[], bool],
) -> None:
    plan = _measure(
        source,
        clip,
        width,
        height,
        should_cancel=should_cancel,
    )
    _check(should_cancel)
    folder = _preview_dir(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    label = _label(clip)
    crop_path = folder / f"{label}.json"
    ass_path = folder / f"{label}.ass"
    dest = folder / f"{label}.mp4"
    storage_service.write_json(crop_path, plan)
    _write_ass(ass_path, clip, transcript, PREVIEW_SIZE, int(plan["caption_alignment"]))
    _encode(
        source,
        dest,
        ass_path,
        segments=_source_segments(clip),
        window=plan["encode"],
        size=PREVIEW_SIZE,
        crf=30,
        preset="ultrafast",
        audio_bitrate="96k",
        sample_rate=sample_rate,
        has_audio=has_audio,
        should_cancel=should_cancel,
    )
    db.save_render(
        clip["id"],
        project_id,
        status="preview_ready",
        crop_mode=plan["encode"]["mode"],
        crop_path=str(crop_path),
        preview_path=str(dest.resolve()),
        error=None,
    )
    db.set_measured_av(clip["id"], int(plan["av_quality"]))
    logger.info("Preview ready project=%s clip=%s mode=%s", project_id, label, plan["encode"]["mode"])


def build_export(
    project_id: str,
    clip: dict,
    source: Path,
    transcript: dict,
    *,
    width: int,
    height: int,
    sample_rate: int | None,
    has_audio: bool,
    should_cancel: Callable[[], bool],
) -> None:
    if clip.get("render_status") not in {"approved", "exported"}:
        raise ClipperError("Approve the preview before exporting the full short.")
    plan = _load_plan(clip, source, width, height, should_cancel)
    _check(should_cancel)
    folder = get_settings().output_dir() / project_id / _label(clip)
    folder.mkdir(parents=True, exist_ok=True)
    ass_path = folder / "captions.ass"
    srt_path = folder / "subtitles.srt"
    dest = folder / "short.mp4"
    alignment = int(plan.get("caption_alignment") or 2)
    cues = _cues(clip, transcript)
    ass_path.write_text(
        caption_service.build_ass(cues, play_x=EXPORT_SIZE[0], play_y=EXPORT_SIZE[1], alignment=alignment),
        encoding="utf-8",
    )
    srt_path.write_text(caption_service.build_srt(cues), encoding="utf-8")
    _encode(
        source,
        dest,
        ass_path,
        segments=_source_segments(clip),
        window=plan["encode"],
        size=EXPORT_SIZE,
        crf=23,
        preset="veryfast",
        audio_bitrate="128k",
        sample_rate=sample_rate,
        has_audio=has_audio,
        should_cancel=should_cancel,
    )
    db.save_render(
        clip["id"],
        project_id,
        status="exported",
        crop_mode=plan["encode"]["mode"],
        export_path=str(dest.resolve()),
        subtitle_path=str(srt_path.resolve()),
        error=None,
    )
    logger.info("Export ready project=%s clip=%s", project_id, _label(clip))


def delete_owned(path_value: object) -> None:
    if not path_value:
        return
    path = Path(str(path_value))
    if not path.is_file():
        return
    roots = (get_settings().data_dir.resolve(), get_settings().output_dir().resolve())
    resolved = path.resolve()
    if any(resolved.is_relative_to(root) for root in roots):
        resolved.unlink()


def _measure(source: Path, clip: dict, width: int, height: int, *, should_cancel: Callable[[], bool]) -> dict:
    frames = _preview_dir(clip["project_id"]) / f"{_label(clip)}_frames"
    if frames.exists():
        shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True, exist_ok=True)
    pattern = frames / "frame_%03d.jpg"
    windows: list[dict] = []
    try:
        for part_index, segment in enumerate(_source_segments(clip)):
            _check(should_cancel)
            part_pattern = frames / f"frame_{part_index:02d}_%03d.jpg"
            try:
                video_service.run_ffmpeg(
                    [
                        "-ss",
                        f"{segment['start']:.3f}",
                        "-t",
                        f"{max(0.2, segment['end'] - segment['start']):.3f}",
                        "-i",
                        str(source),
                        "-an",
                        "-vf",
                        "fps=1,scale=360:-2",
                        "-q:v",
                        "8",
                        str(part_pattern),
                    ],
                    should_cancel=should_cancel,
                    output=part_pattern,
                    cancelled_message="Cancelled while reading the preview frames.",
                )
            except CancelledError:
                raise
            except ClipperError:
                pass
        if not any(frames.glob("frame_*.jpg")):
            _check(should_cancel)
            one = frames / "frame_001.jpg"
            first = _source_segments(clip)[0]
            video_service.run_ffmpeg(
                [
                    "-ss",
                    f"{first['start']:.3f}",
                    "-i",
                    str(source),
                    "-an",
                    "-vf",
                    "scale=360:-2",
                    "-frames:v",
                    "1",
                    str(one),
                ],
                should_cancel=should_cancel,
                output=one,
                cancelled_message="Cancelled while reading the preview frames.",
            )
        for index, frame in enumerate(sorted(frames.glob("frame_*.jpg"))):
            _check(should_cancel)
            face_x, face_y, found = _detect_face(frame, width, height)
            window = crop_window(
                width,
                height,
                face_x=face_x,
                face_y=face_y,
                face=found,
                use_manual=bool(clip.get("use_manual")),
                manual_offset=float(clip.get("manual_offset") or 0),
            )
            window["t"] = index
            windows.append(window)
    finally:
        shutil.rmtree(frames, ignore_errors=True)
    if not windows:
        raise ClipperError("No preview frames could be read from this clip.")
    encode = _encode_choice(windows)
    faces = [item for item in windows if item.get("face") and item.get("face_y") is not None]
    face_y = None
    if faces:
        ordered = sorted(float(item["face_y"]) for item in faces)
        face_y = ordered[len(ordered) // 2]
    return {
        "zoom": False,
        "source_width": width,
        "source_height": height,
        "av_quality": 5 if any(item.get("face") for item in windows) else 4,
        "caption_alignment": caption_service.caption_alignment(face_y, height),
        "windows": windows,
        "encode": encode,
    }


def _detect_face(frame: Path, source_w: int, source_h: int) -> tuple[float | None, float | None, bool]:
    try:
        import cv2
    except ImportError as exc:
        raise ClipperError(
            "OpenCV is not installed. Run pip install -r backend/requirements.txt."
        ) from exc
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        raise ClipperError("The face detector data is missing from the OpenCV install.")
    image = cv2.imread(str(frame))
    if image is None:
        return None, None, False
    try:
        proxy_h, proxy_w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
    finally:
        del image
    if len(faces) == 0 or proxy_w < 1 or proxy_h < 1:
        return None, None, False
    x, y, w, h = max(faces, key=lambda item: int(item[2]) * int(item[3]))
    center_x = (float(x) + float(w) / 2) * source_w / proxy_w
    center_y = (float(y) + float(h) / 2) * source_h / proxy_h
    return center_x, center_y, True


def _encode_choice(windows: list[dict]) -> dict:
    if windows[0]["mode"] == "pad":
        return {key: windows[0][key] for key in ("x", "y", "w", "h", "mode")}
    faces = [item for item in windows if item["mode"] == "face"]
    pool = sorted(faces or windows, key=lambda item: int(item["x"]))
    chosen = pool[len(pool) // 2]
    return {key: chosen[key] for key in ("x", "y", "w", "h", "mode")}


def _load_plan(clip: dict, source: Path, width: int, height: int, should_cancel: Callable[[], bool]) -> dict:
    raw = clip.get("crop_path")
    if raw and Path(str(raw)).is_file():
        return storage_service.read_json(Path(str(raw)))
    return _measure(source, clip, width, height, should_cancel=should_cancel)


def _encode(
    source: Path,
    dest: Path,
    ass_path: Path,
    *,
    segments: list[dict],
    window: dict,
    size: tuple[int, int],
    crf: int,
    preset: str,
    audio_bitrate: str,
    sample_rate: int | None,
    has_audio: bool,
    should_cancel: Callable[[], bool],
) -> None:
    picture = _picture_filter(window, size)
    if len(segments) == 1:
        segment = segments[0]
        args = [
            "-ss",
            f"{segment['start']:.3f}",
            "-t",
            f"{max(0.2, segment['end'] - segment['start']):.3f}",
            "-i",
            str(source),
            "-vf",
            f"{picture},ass={ass_path.name}",
            "-map",
            "0:v:0",
        ]
        args.extend(["-map", "0:a:0"] if has_audio else ["-an"])
    else:
        graph = _join_filter(segments, picture, ass_path.name, has_audio)
        args = ["-i", str(source), "-filter_complex", graph, "-map", "[v]"]
        args.extend(["-map", "[ac]"] if has_audio else ["-an"])
    args.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-threads",
            str(get_settings().effective_threads()),
        ]
    )
    if has_audio:
        args.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
                "-ar",
                str(_aac_rate(sample_rate)),
            ]
        )
    args.extend(["-movflags", "+faststart", str(dest)])
    video_service.run_ffmpeg(
        args,
        should_cancel=should_cancel,
        output=dest,
        cwd=ass_path.parent,
        cancelled_message="Cancelled during rendering.",
    )


def _write_ass(path: Path, clip: dict, transcript: dict, size: tuple[int, int], alignment: int) -> None:
    path.write_text(
        caption_service.build_ass(
            _cues(clip, transcript),
            play_x=size[0],
            play_y=size[1],
            alignment=alignment,
        ),
        encoding="utf-8",
    )


def _cues(clip: dict, transcript: dict) -> list[dict]:
    return caption_service.cues_for_segments(
        transcript.get("sentences") or [],
        _source_segments(clip),
        str(clip.get("opening_hook") or ""),
    )


def _source_segments(clip: dict) -> list[dict]:
    raw = clip.get("segments")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if isinstance(raw, list):
        segments = []
        for item in raw:
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
    start = float(clip.get("start_seconds", clip.get("start", 0.0)))
    end = float(clip.get("end_seconds", clip.get("end", start)))
    if end <= start:
        end = start + max(0.2, float(clip.get("duration_seconds") or clip.get("duration") or 0.2))
    return [{"start": start, "end": end}]


def _picture_filter(window: dict, size: tuple[int, int]) -> str:
    width, height = size
    if window.get("mode") == "pad":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=bilinear,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        )
    return (
        f"crop={int(window['w'])}:{int(window['h'])}:{int(window['x'])}:{int(window['y'])},"
        f"scale={width}:{height}:flags=bilinear,setsar=1"
    )


def _join_filter(segments: list[dict], picture: str, ass_name: str, has_audio: bool) -> str:
    chains: list[str] = []
    for index, segment in enumerate(segments):
        chains.append(
            f"[0:v]trim=start={segment['start']:.3f}:end={segment['end']:.3f},"
            f"setpts=PTS-STARTPTS,{picture}[v{index}]"
        )
        if has_audio:
            chains.append(
                f"[0:a]atrim=start={segment['start']:.3f}:end={segment['end']:.3f},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
    if has_audio:
        joined = "".join(f"[v{index}][a{index}]" for index in range(len(segments)))
        chains.append(f"{joined}concat=n={len(segments)}:v=1:a=1[vc][ac]")
    else:
        joined = "".join(f"[v{index}]" for index in range(len(segments)))
        chains.append(f"{joined}concat=n={len(segments)}:v=1:a=0[vc]")
    chains.append(f"[vc]ass={ass_name}[v]")
    return ";".join(chains)


def _preview_dir(project_id: str) -> Path:
    return storage_service.project_dir(project_id) / "work" / "previews"


def _label(clip: dict) -> str:
    return f"clip_{int(clip['ordinal']) + 1:03d}"


def _aac_rate(sample_rate: int | None) -> int:
    if sample_rate in AAC_RATES:
        return int(sample_rate)
    return 48000


def _even(value: int) -> int:
    value = int(value)
    if value < 2:
        return 2
    return value - (value % 2)


def _clamp_even(origin: int, slack: int) -> int:
    origin = max(0, min(int(slack), origin))
    origin = origin - (origin % 2)
    if origin > slack:
        origin = slack - (slack % 2)
    return max(0, origin)


def _check(should_cancel: Callable[[], bool]) -> None:
    if should_cancel():
        raise CancelledError("Cancelled during rendering.")
