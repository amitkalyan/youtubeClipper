"""Highlight scoring stays on real sentences and does not call Ollama in these tests."""

from __future__ import annotations

import json

import pytest

from app.errors import CancelledError, OllamaError
from app.services.clip_validation_service import has_short_window, validate_candidates
from app.services.highlight_service import chunk_lines, find_clips
from app.services.ollama_service import parse_clip_response
from tests.media_factory import make_tone_video
from tests.test_api_workflow import wait_project


@pytest.fixture
def tone_video(tmp_path):
    path = tmp_path / "tone.mp4"
    make_tone_video(path, seconds=1)
    return path


def sentences() -> list[dict]:
    return [
        {"id": 0, "start": 0.0, "end": 6.0, "text": "Here is a useful way to save the file.", "words": []},
        {"id": 1, "start": 6.2, "end": 12.0, "text": "Name it before you close the window.", "words": []},
        {"id": 2, "start": 12.2, "end": 21.0, "text": "That keeps the work from being lost.", "words": []},
        {"id": 3, "start": 20.0, "end": 24.0, "text": "Too short on its own.", "words": []},
    ]


def quote() -> str:
    return (
        "Here is a useful way to save the file. "
        "Name it before you close the window. "
        "That keeps the work from being lost."
    )


def raw_clip(**overrides) -> dict:
    payload = {
        "sentence_ids": [0, 1, 2],
        "start": 0,
        "end": 18,
        "transcript": "This paraphrase must not be stored.",
        "opening_hook": "useful way to save",
        "category": "practical tip",
        "score_breakdown": {
            "opening_hook": 20,
            "interesting_content": 16,
            "emotional_impact": 10,
            "context": 12,
            "complete_thought": 10,
            "shareability": 7,
            "av_quality": 5,
        },
        "reason": "A complete tip.",
        "suggested_title": "A guaranteed viral save",
    }
    payload.update(overrides)
    return payload


def test_validation_stores_spoken_words_and_caps_visual_score():
    kept = validate_candidates(sentences(), [raw_clip(), raw_clip(sentence_ids=[3], start=20, end=24)])
    assert len(kept) == 1
    clip = kept[0]
    assert clip["transcript"] == quote()
    assert clip["duration"] == 21.0
    assert clip["score_breakdown"]["av_quality"] == 3
    assert clip["score"] == 78
    assert clip["opening_hook"] == "useful way to save"
    assert "viral" not in clip["suggested_title"].lower()
    assert "guaranteed" not in clip["suggested_title"].lower()


def test_validation_drops_overlap_and_keeps_the_stronger_score():
    weaker = raw_clip()
    weaker["score_breakdown"] = {key: 1 for key in weaker["score_breakdown"]}
    stronger = raw_clip()
    kept = validate_candidates(sentences(), [weaker, stronger])
    assert len(kept) == 1
    assert kept[0]["score"] == 78


def test_validation_shrinks_a_span_that_is_longer_than_one_minute():
    long_sentences = [
        {"id": index, "start": index * 8.0, "end": index * 8.0 + 7.5, "text": f"Point {index} stays specific.", "words": []}
        for index in range(9)
    ]
    kept = validate_candidates(
        long_sentences,
        [
            {
                "sentence_ids": list(range(9)),
                "start": 0,
                "end": 71.5,
                "transcript": "Point 0 stays specific. Point 1 stays specific. Point 2 stays specific.",
                "score_breakdown": {"opening_hook": 10},
            }
        ],
    )
    assert len(kept) == 1
    assert kept[0]["duration"] == 55.5
    assert 20 <= kept[0]["duration"] <= 60
    assert "Point 0 stays specific." in kept[0]["transcript"]
    assert "Point 6 stays specific." in kept[0]["transcript"]
    assert "Point 7 stays specific." not in kept[0]["transcript"]


def spoken_lines() -> list[dict]:
    return [
        {"id": index, "start": index * 8.0, "end": index * 8.0 + 7.5, "text": f"Line {index} was spoken.", "words": []}
        for index in range(4)
    ]


def test_speech_under_20_seconds_is_joined_with_other_speech():
    rows = [
        {"id": 0, "start": 0.0, "end": 8.0, "text": "First speech.", "words": []},
        {"id": 1, "start": 8.2, "end": 14.0, "text": "Still the first.", "words": []},
        {"id": 2, "start": 50.0, "end": 62.0, "text": "Second speech continues.", "words": []},
    ]
    kept = validate_candidates(rows, [{"sentence_ids": [0], "transcript": "First speech."}])
    assert len(kept) == 1
    assert kept[0]["duration"] == pytest.approx(26.0, abs=0.05)
    assert kept[0]["segments"] == [
        {"start": 0.0, "end": 14.0},
        {"start": 50.0, "end": 62.0},
    ]
    assert "First speech." in kept[0]["transcript"]
    assert "Second speech continues." in kept[0]["transcript"]
    assert has_short_window(rows) is True


def test_short_suggestion_is_joined_with_neighboring_sentences():
    kept = validate_candidates(
        spoken_lines(),
        [{"sentence_ids": [1], "start": 8, "end": 15.5, "transcript": "Line 1 was spoken.", "opening_hook": "Line 1"}],
    )
    assert len(kept) == 1
    assert 20 <= kept[0]["duration"] <= 60
    assert "Line 1 was spoken." in kept[0]["transcript"]


def test_empty_model_response_joins_neighboring_sentences():
    clips = find_clips(
        {"sentences": spoken_lines()},
        on_progress=lambda ratio, message: None,
        should_cancel=lambda: False,
        chat=lambda prompt, *, should_cancel, keep_alive: '{"clips": []}',
    )
    assert len(clips) == 1
    assert 20 <= clips[0]["duration"] <= 60
    assert clips[0]["transcript"].startswith("Line 0 was spoken.")
    assert "Line 3 was spoken." in clips[0]["transcript"]


def test_ollama_off_creates_shorts_without_calling_the_model(monkeypatch):
    def chat(*args, **kwargs):
        raise AssertionError("Ollama should not be called")

    monkeypatch.setattr("app.services.ollama_service.installed_models", lambda: None)
    monkeypatch.setattr("app.services.ollama_service.chat", chat)
    monkeypatch.setattr("app.services.ollama_service.unload", lambda: None)
    messages: list[str] = []
    clips = find_clips(
        {"sentences": spoken_lines()},
        on_progress=lambda ratio, message: messages.append(message),
        should_cancel=lambda: False,
    )
    assert len(clips) == 1
    assert 20 <= clips[0]["duration"] <= 60
    assert clips[0]["transcript"].startswith("Line 0 was spoken.")
    assert any(message.startswith("Ollama is off.") for message in messages)


def test_ollama_error_still_creates_shorts():
    def chat(prompt: str, *, should_cancel, keep_alive):
        raise OllamaError("Cannot reach Ollama.")

    clips = find_clips(
        {"sentences": spoken_lines()},
        on_progress=lambda ratio, message: None,
        should_cancel=lambda: False,
        chat=chat,
    )
    assert len(clips) == 1
    assert 20 <= clips[0]["duration"] <= 60


def test_cancel_during_scoring_is_not_replaced_with_shorts():
    def chat(prompt: str, *, should_cancel, keep_alive):
        raise CancelledError("Cancelled.")

    with pytest.raises(CancelledError):
        find_clips(
            {"sentences": spoken_lines()},
            on_progress=lambda ratio, message: None,
            should_cancel=lambda: False,
            chat=chat,
        )


def test_short_transcript_does_not_call_the_model():
    called = False

    def chat(prompt: str, *, should_cancel, keep_alive):
        nonlocal called
        called = True
        return '{"clips": []}'

    clips = find_clips(
        {"sentences": [{"id": 0, "start": 0.0, "end": 4.0, "text": "Hello.", "words": []}]},
        on_progress=lambda ratio, message: None,
        should_cancel=lambda: False,
        chat=chat,
    )
    assert clips == []
    assert called is False
    assert has_short_window([{"id": 0, "start": 0.0, "end": 4.0}]) is False


def test_chunks_overlap_and_json_fences_parse():
    lines = ["x" * 1500, "y" * 1500, "z" * 1500]
    chunks = chunk_lines(lines, limit=1600)
    assert len(chunks) >= 2
    assert chunks[1][0] == lines[0]
    parsed = parse_clip_response('```json\n{"clips": [{"start": 1}]}\n```')
    assert parsed == [{"start": 1}]
    with pytest.raises(OllamaError):
        parse_clip_response("not json")


def test_highlight_job_keeps_only_validated_clips(client, tone_video, monkeypatch):
    http, _data = client
    document = {
        "language": "en",
        "language_probability": 0.9,
        "model": "base",
        "duration": 24.0,
        "text": quote(),
        "segments": [],
        "sentences": sentences(),
        "warnings": [],
    }

    def fake_transcribe(audio_path, *, media_duration, on_progress, should_cancel, model_loader=None):
        on_progress(1.0, "Transcribed")
        return document

    def fake_chat(prompt, *, should_cancel, keep_alive):
        return json.dumps({"clips": [raw_clip()]})

    monkeypatch.setattr("app.services.transcription_service.transcribe_file", fake_transcribe)
    monkeypatch.setattr("app.services.ollama_service.installed_models", lambda: ["llama3.2:latest"])
    monkeypatch.setattr("app.services.ollama_service.chat", fake_chat)
    monkeypatch.setattr("app.services.ollama_service.unload", lambda: None)

    with tone_video.open("rb") as handle:
        created = http.post(
            "/api/projects/upload",
            data={"title": "Tips"},
            files={"file": (tone_video.name, handle, "video/mp4")},
        )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    assert wait_project(http, project_id)["status"] == "ready"

    started = http.post(f"/api/projects/{project_id}/highlights")
    assert started.status_code == 202, started.text
    finished = wait_project(http, project_id)
    assert finished["status"] == "ready"
    assert finished["clip_count"] == 1
    clips = http.get(f"/api/projects/{project_id}/highlights")
    assert clips.status_code == 200
    body = clips.json()
    assert body[0]["transcript"] == quote()
    assert body[0]["score_breakdown"]["av_quality"] == 4
    assert body[0]["score"] == 79
    assert body[0]["render"]["status"] == "preview_ready"
