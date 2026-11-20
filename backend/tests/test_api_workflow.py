"""Upload, queue, cancel, and save a transcript. Whisper itself is mocked here."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.errors import CancelledError
from tests.media_factory import make_silent_video, make_tone_video

TERMINAL = {"ready", "failed", "cancelled"}


def sample_document() -> dict:
    words = [
        {"word": " Hello", "start": 0.0, "end": 0.4, "probability": 0.9},
        {"word": " world.", "start": 0.4, "end": 1.0, "probability": 0.9},
    ]
    sentence = {"id": 0, "start": 0.0, "end": 1.0, "text": "Hello world.", "words": words}
    return {
        "language": "en",
        "language_probability": 0.99,
        "model": "base",
        "duration": 1.0,
        "text": "Hello world.",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Hello world.", "words": words}],
        "sentences": [sentence],
        "warnings": [],
    }


def upload(http, path: Path, title: str = "Demo") -> dict:
    with path.open("rb") as handle:
        response = http.post(
            "/api/projects/upload",
            data={"title": title},
            files={"file": (path.name, handle, "video/mp4")},
        )
    assert response.status_code == 201, response.text
    return response.json()


def wait_project(http, project_id: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = http.get(f"/api/projects/{project_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {project_id}. Last state: {last}")


@pytest.fixture
def tone_video(tmp_path):
    path = tmp_path / "tone.mp4"
    make_tone_video(path, seconds=1)
    return path


def test_health_reports_cpu_profile(client):
    http, _data = client
    response = http.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == 4
    assert body["ffmpeg"]["available"] is True
    assert body["ffprobe"]["available"] is True
    assert body["whisper"]["model"] == "base"
    assert body["whisper"]["device"] == "cpu"
    assert body["whisper"]["compute_type"] == "int8"
    assert body["jobs"]["max_concurrent"] == 1
    assert body["ollama"]["model"]
    assert isinstance(body["ollama"]["models"], list)


def test_upload_transcribe_and_save(client, tone_video, monkeypatch):
    http, data = client

    def fake_transcribe(audio_path, *, media_duration, on_progress, should_cancel, model_loader=None):
        on_progress(1.0, "Transcribed through 1.0s")
        return sample_document()

    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_file",
        fake_transcribe,
    )
    created = upload(http, tone_video, title="Tone")
    finished = wait_project(http, created["id"])
    assert finished["status"] == "ready"
    assert finished["width"] == 320
    assert finished["height"] == 180
    assert finished["has_audio"] is True
    assert finished["has_transcript"] is True

    transcript = http.get(f"/api/projects/{created['id']}/transcript")
    assert transcript.status_code == 200
    body = transcript.json()
    assert body["text"] == "Hello world."
    assert body["sentences"][0]["words"][0]["start"] == 0.0

    audio = data / "projects" / created["id"] / "work" / "audio.wav"
    saved = data / "projects" / created["id"] / "work" / "transcript.json"
    assert audio.is_file() and audio.stat().st_size > 1000
    assert saved.is_file()
    from app.services.video_service import probe

    info = probe(audio)
    assert info.sample_rate == 16000
    assert info.channels == 1

    jobs = http.get("/api/jobs").json()
    assert any(job["project_id"] == created["id"] and job["status"] == "completed" for job in jobs)
    media = http.get(f"/api/projects/{created['id']}/media")
    assert media.status_code == 200
    assert media.content[:8] != b""


def test_second_project_waits_for_the_running_job(client, tone_video, monkeypatch):
    http, _data = client
    started = threading.Event()
    release = threading.Event()

    def fake_transcribe(audio_path, *, media_duration, on_progress, should_cancel, model_loader=None):
        started.set()
        deadline = time.time() + 20
        while time.time() < deadline:
            if should_cancel():
                raise CancelledError("Transcription cancelled.")
            if release.is_set():
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("The test did not release the transcription.")
        on_progress(1.0, "Done")
        return sample_document()

    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_file",
        fake_transcribe,
    )
    try:
        first = upload(http, tone_video, title="First")
        assert started.wait(20)
        second_path = tone_video.with_name("tone-2.mp4")
        second_path.write_bytes(tone_video.read_bytes())
        second = upload(http, second_path, title="Second")
        queued = http.get(f"/api/projects/{second['id']}")
        assert queued.json()["status"] == "queued"
        release.set()
        assert wait_project(http, first["id"])["status"] == "ready"
        assert wait_project(http, second["id"])["status"] == "ready"
    finally:
        release.set()


def test_cancel_during_transcription(client, tone_video, monkeypatch):
    http, _data = client
    started = threading.Event()
    release = threading.Event()

    def fake_transcribe(audio_path, *, media_duration, on_progress, should_cancel, model_loader=None):
        started.set()
        deadline = time.time() + 20
        while time.time() < deadline:
            if should_cancel():
                raise CancelledError("Transcription cancelled.")
            if release.is_set():
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("Cancellation was not observed.")
        return sample_document()

    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_file",
        fake_transcribe,
    )
    try:
        created = upload(http, tone_video, title="Cancel me")
        assert started.wait(20)
        response = http.post(f"/api/projects/{created['id']}/cancel")
        assert response.status_code == 202
        finished = wait_project(http, created["id"])
        assert finished["status"] == "cancelled"
    finally:
        release.set()


def test_silent_video_is_kept_as_a_failed_project(client, tmp_path):
    http, _data = client
    video = tmp_path / "silent.mp4"
    make_silent_video(video)
    created = upload(http, video, title="Silent")
    assert created["status"] == "failed"
    assert "audio" in (created["error"] or "").lower()


def test_invalid_video_bytes_fail_cleanly(client, tmp_path):
    http, data = client
    fake = tmp_path / "notes.mp4"
    fake.write_text("not a video", encoding="utf-8")
    created = upload(http, fake, title="Notes")
    assert created["status"] == "failed"
    assert not (data / "projects" / created["id"] / "source.mp4").exists()


def test_rejects_non_video_extension(client, tmp_path):
    http, _data = client
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    with notes.open("rb") as handle:
        response = http.post(
            "/api/projects/upload",
            data={"title": "Notes"},
            files={"file": ("notes.txt", handle, "text/plain")},
        )
    assert response.status_code == 400


def test_rejects_oversize_upload(client, tone_video, monkeypatch):
    http, _data = client
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "100")
    with tone_video.open("rb") as handle:
        response = http.post(
            "/api/projects/upload",
            data={"title": "Big"},
            files={"file": ("tone.mp4", handle, "video/mp4")},
        )
    assert response.status_code == 413
