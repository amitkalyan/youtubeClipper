"""Titles and thumbnails stay tied to the spoken transcript."""

from __future__ import annotations

import json

from PIL import Image

from app.errors import ClipperError
from app.services.metadata_service import draft_metadata, edit_metadata
from app.services.thumbnail_service import draw_headline
from tests.media_factory import make_tone_video
from tests.test_api_workflow import sample_document, upload, wait_project

import pytest


def clip() -> dict:
    return {
        "transcript": "Hello world.",
        "opening_hook": "Hello",
        "suggested_title": "Hello",
        "category": "memorable statement",
    }


def test_draft_drops_hype_and_words_that_were_not_spoken():
    raw = json.dumps(
        {
            "titles": ["Hello there now", "A guaranteed viral hello", "Hello world today"],
            "description": 'Hello world. He said "a secret quote". This will go viral.',
            "hashtags": ["#Hello", "#World", "#Extra", "#TooMany", "#More", "#Sixth"],
            "headline": "secret rocket",
            "cta": "Must watch the rest",
            "category": "not real",
            "keywords": ["Hello", "rocket", "world"],
        }
    )
    saved = draft_metadata(raw, clip())
    assert len(saved["titles"]) == 3
    assert all("viral" not in title.lower() for title in saved["titles"])
    assert "secret quote" not in saved["description"].lower()
    assert "viral" not in saved["description"].lower()
    assert saved["headline"] == "Hello"
    assert saved["hashtags"] == ["#hello", "#world"]
    assert "rocket" not in saved["keywords"]
    assert saved["category"] == "memorable statement"
    assert "must watch" not in saved["cta"].lower()


def test_edit_rejects_a_headline_that_was_not_spoken():
    with pytest.raises(ClipperError):
        edit_metadata(
            {
                "titles": ["Hello", "Hello world", "Hello again"],
                "selected_title": "Hello",
                "description": "Hello world.",
                "hashtags": ["#hello"],
                "headline": "secret rocket",
                "cta": "Watch the rest of this video.",
                "keywords": ["hello"],
            },
            clip(),
            None,
        )


def test_headline_is_drawn_on_one_jpeg(tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (320, 180), (20, 20, 20)).save(frame)
    dest = tmp_path / "thumb.jpg"
    draw_headline(frame, dest, "Hello world", alignment=2)
    with Image.open(dest) as image:
        assert image.format == "JPEG"
        assert image.size == (320, 180)


def test_metadata_job_writes_a_thumbnail_and_keeps_an_edit(client, tmp_path, monkeypatch):
    http, _data = client
    tone = tmp_path / "tone.mp4"
    make_tone_video(tone, seconds=1)

    def fake_transcribe(audio_path, *, media_duration, on_progress, should_cancel, model_loader=None):
        on_progress(1.0, "Transcribed")
        return sample_document()

    def fake_chat(prompt, *, should_cancel, keep_alive, system=None):
        return json.dumps(
            {
                "titles": ["Hello world", "Hello", "Hello again"],
                "description": "Hello world.",
                "hashtags": ["#Hello", "#World", "#Clip"],
                "headline": "Hello world",
                "cta": "Watch the rest of this video.",
                "category": "memorable statement",
                "keywords": ["hello", "world"],
            }
        )

    monkeypatch.setattr("app.services.transcription_service.transcribe_file", fake_transcribe)
    monkeypatch.setattr("app.services.ollama_service.chat", fake_chat)
    monkeypatch.setattr("app.services.ollama_service.unload", lambda: None)
    created = upload(http, tone, title="Package")
    ready = wait_project(http, created["id"])
    assert ready["status"] == "ready"

    from app import db

    db.replace_clips(
        created["id"],
        [
            {
                "ordinal": 0,
                "start": 0.0,
                "end": 1.0,
                "duration": 1.0,
                "transcript": "Hello world.",
                "opening_hook": "Hello",
                "category": "memorable statement",
                "score": 3,
                "score_breakdown": {
                    "opening_hook": 0,
                    "interesting_content": 0,
                    "emotional_impact": 0,
                    "context": 0,
                    "complete_thought": 0,
                    "shareability": 0,
                    "av_quality": 3,
                },
                "reason": "Sample",
                "suggested_title": "Hello",
            }
        ],
    )
    started = http.post(f"/api/projects/{created['id']}/metadata", json={})
    assert started.status_code == 202, started.text
    done = wait_project(http, created["id"], timeout=60)
    assert done["error"] in (None, ""), done
    rows = http.get(f"/api/projects/{created['id']}/metadata").json()
    assert rows[0]["headline"] == "Hello world"
    assert rows[0]["has_thumbnail"] is True
    clip_id = db.list_clips(created["id"])[0]["id"]
    image = http.get(f"/api/projects/{created['id']}/clips/{clip_id}/thumbnail")
    assert image.status_code == 200
    assert image.content[:2] == b"\xff\xd8"
    saved = db.get_metadata(created["id"], clip_id)
    with Image.open(saved["thumbnail_path"]) as thumb:
        assert thumb.size == (1080, 1920)

    edited = http.put(
        f"/api/projects/{created['id']}/clips/{clip_id}/metadata",
        json={
            "titles": ["Hello", "Hello world", "Hello again"],
            "selected_title": "Hello",
            "description": "Hello world.",
            "hashtags": ["#hello", "#world"],
            "headline": "Hello",
            "cta": "Watch the rest of this video.",
            "keywords": ["hello", "world"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["headline"] == "Hello"
    assert edited.json()["selected_title"] == "Hello"
    rejected = http.put(
        f"/api/projects/{created['id']}/clips/{clip_id}/metadata",
        json={**edited.json(), "headline": "secret rocket", "has_thumbnail": True},
    )
    assert rejected.status_code == 400
