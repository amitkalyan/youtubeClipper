"""YouTube link parsing and a downloaded file running through the existing job."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services import storage_service
from app.services.youtube_service import build_download_command, parse_youtube_url, progress_ratio
from tests.media_factory import make_tone_video
from tests.test_api_workflow import sample_document, wait_project


@pytest.fixture
def tone_video(tmp_path):
    path = tmp_path / "tone.mp4"
    make_tone_video(path, seconds=1)
    return path


def test_parse_accepts_one_video_link():
    assert parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=12s") == "dQw4w9WgXcQ"
    assert parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123") == "dQw4w9WgXcQ"


def test_parse_rejects_other_pages():
    from app.errors import InvalidMediaError

    for value in (
        "",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/playlist?list=PL1234567890",
        "https://www.youtube.com/@somechannel",
        "https://www.youtube.com/watch?v=short",
    ):
        with pytest.raises(InvalidMediaError):
            parse_youtube_url(value)


def test_download_command_is_one_video_and_capped(tmp_path):
    command = build_download_command(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        tmp_path,
        tmp_path / "part",
    )
    text = " ".join(command)
    assert "--no-playlist" in command
    assert "height<=1080" in text
    assert "--cookies-from-browser" not in text
    assert "cookies" not in text
    assert command[-1] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_progress_ratio_reads_download_lines():
    assert progress_ratio("[download]  42.5% of 10.00MiB") == 0.425
    assert progress_ratio("Destination: source.mp4") is None


def test_youtube_endpoint_uses_the_downloaded_file(client, tone_video, monkeypatch):
    http, _data = client

    def fake_download(url, project_id, *, should_cancel, on_progress):
        dest = storage_service.project_dir(project_id) / "source.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(tone_video, dest)
        on_progress(1.0, "Downloaded")
        return dest, "Remote title that should be ignored"

    def fake_transcribe(audio_path, *, media_duration, on_progress, should_cancel, model_loader=None):
        on_progress(1.0, "Transcribed through 1.0s")
        return sample_document()

    monkeypatch.setattr("app.services.youtube_service.download_video", fake_download)
    monkeypatch.setattr("app.services.transcription_service.transcribe_file", fake_transcribe)

    denied = http.post(
        "/api/projects/youtube",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "confirmed_rights": False},
    )
    assert denied.status_code == 400

    other_site = http.post(
        "/api/projects/youtube",
        json={"url": "https://example.com/watch?v=dQw4w9WgXcQ", "confirmed_rights": True},
    )
    assert other_site.status_code == 400

    created = http.post(
        "/api/projects/youtube",
        json={
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "title": "From a link",
            "confirmed_rights": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    finished = wait_project(http, body["id"])
    assert finished["status"] == "ready"
    assert finished["title"] == "From a link"
    assert finished["has_audio"] is True
    assert Path(finished["stored_path"]).is_file()
