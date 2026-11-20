"""End-to-end Phase 1 check: a local speech video becomes a real Whisper transcript."""

from __future__ import annotations

import subprocess

import pytest

from app.services.video_service import hidden_window_flag, probe
from tests.media_factory import mux_speech_video
from tests.test_api_workflow import upload, wait_project

SPOKEN = "Hello. This is the local clipper transcription test."


def _synthesize(path, text: str) -> None:
    safe = str(path).replace("'", "''")
    script = "\n".join(
        [
            "Add-Type -AssemblyName System.Speech",
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            f"$synth.SetOutputToWaveFile('{safe}')",
            "$synth.Speak(@'",
            text,
            "'@)",
            "$synth.Dispose()",
        ]
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=hidden_window_flag(),
    )
    if proc.returncode != 0 or not path.is_file() or path.stat().st_size < 1000:
        pytest.skip("Windows speech synthesis is unavailable: " + (proc.stderr or "")[-400:])


def test_local_speech_video_produces_a_transcript(client, tmp_path):
    pytest.importorskip("faster_whisper")
    wav = tmp_path / "speech.wav"
    video = tmp_path / "speech.mp4"
    _synthesize(wav, SPOKEN)
    mux_speech_video(wav, video)
    http, data = client
    created = upload(http, video, title="Phase 1 speech sample")
    finished = wait_project(http, created["id"], timeout=600)
    assert finished["status"] == "ready", finished
    transcript = http.get(f"/api/projects/{created['id']}/transcript")
    assert transcript.status_code == 200
    body = transcript.json()
    assert body["sentences"], body
    assert body["text"].strip(), body
    for sentence in body["sentences"]:
        assert sentence["end"] + 0.05 >= sentence["start"]
    lowered = body["text"].lower()
    assert any(token in lowered for token in ("hello", "clipper", "local", "test")), body["text"]
    audio = data / "projects" / created["id"] / "work" / "audio.wav"
    info = probe(audio)
    assert info.sample_rate == 16000
    assert info.channels == 1
