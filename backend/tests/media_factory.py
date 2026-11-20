"""Tiny synthetic videos so tests never need a downloaded film."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.video_service import hidden_window_flag, resolve_ffmpeg, tool_status


def require_ffmpeg() -> None:
    if not tool_status("ffmpeg")["available"] or not tool_status("ffprobe")["available"]:
        pytest.skip("FFmpeg is not available. Run scripts/fetch-ffmpeg.ps1.")


def make_tone_video(path: Path, seconds: float = 1.0) -> None:
    require_ffmpeg()
    duration = f"{seconds:.2f}"
    _run(
        [
            resolve_ffmpeg(),
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=320x180:r=10:d={duration}",
            "-shortest",
            "-map",
            "1:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(path),
        ]
    )


def make_silent_video(path: Path) -> None:
    require_ffmpeg()
    _run(
        [
            resolve_ffmpeg(),
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:r=5:d=1",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def mux_speech_video(wav: Path, dest: Path) -> None:
    require_ffmpeg()
    _run(
        [
            resolve_ffmpeg(),
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav),
            "-f",
            "lavfi",
            "-i",
            "color=c=0x202020:s=320x180:r=10",
            "-shortest",
            "-t",
            "30",
            "-map",
            "1:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(dest),
        ]
    )


def _run(command: list[str]) -> None:
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=hidden_window_flag(),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1500:]
        raise RuntimeError(detail or "ffmpeg failed")
