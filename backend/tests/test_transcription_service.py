"""Sentence grouping and model release. The real model is covered by the end-to-end test."""

from __future__ import annotations

import pytest

from app.errors import CancelledError
from app.services.transcription_service import (
    group_sentences,
    hard_problems,
    transcribe_file,
)


@pytest.fixture(autouse=True)
def safe_profile(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "base")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("WHISPER_THREADS", "2")


class _Info:
    language = "en"
    language_probability = 0.91
    duration = 2.0


class _Word:
    def __init__(self, word: str, start: float, end: float, probability: float = 0.9) -> None:
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class _Segment:
    def __init__(self, start: float, end: float, text: str, words: list[_Word]) -> None:
        self.start = start
        self.end = end
        self.text = text
        self.words = words


class _Model:
    def __init__(self, segments: list[_Segment]) -> None:
        self.segments = segments
        self.unloaded = False

    def transcribe(self, path: str, **kwargs: object):
        def generate():
            yield from self.segments

        return generate(), _Info()

    def unload(self) -> None:
        self.unloaded = True


def test_sentences_use_only_spoken_tokens():
    segments = [
        {
            "start": 0.0,
            "end": 1.2,
            "text": "This is one. And two.",
            "words": [
                {"word": " This", "start": 0.0, "end": 0.2, "probability": 0.9},
                {"word": " is", "start": 0.2, "end": 0.3, "probability": 0.9},
                {"word": " one.", "start": 0.3, "end": 0.6, "probability": 0.9},
                {"word": " And", "start": 0.7, "end": 0.9, "probability": 0.9},
                {"word": " two.", "start": 0.9, "end": 1.2, "probability": 0.9},
            ],
        }
    ]
    sentences = group_sentences(segments)
    assert [item["text"] for item in sentences] == ["This is one.", "And two."]
    spoken = "".join(word["word"] for word in segments[0]["words"])
    got = "".join(word["word"] for sentence in sentences for word in sentence["words"])
    assert got == spoken


def test_segment_without_word_times_stays_intact():
    sentences = group_sentences(
        [{"start": 0.0, "end": 1.0, "text": "No word times.", "words": []}]
    )
    assert sentences[0]["text"] == "No word times."
    assert sentences[0]["words"] == []


def test_rejects_backwards_sentence():
    problems = hard_problems(
        {"sentences": [{"id": 0, "start": 1.0, "end": 0.2, "text": "Nope", "words": []}]}
    )
    assert problems


def test_rejects_words_out_of_order():
    problems = hard_problems(
        {
            "sentences": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "b a",
                    "words": [
                        {"word": " b", "start": 0.8, "end": 1.0},
                        {"word": " a", "start": 0.1, "end": 0.2},
                    ],
                }
            ]
        }
    )
    assert any("out of order" in item for item in problems)


def test_transcribe_releases_model_and_warns_past_duration(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not-read-by-the-fake-model")
    model = _Model(
        [
            _Segment(
                0.0,
                2.0,
                "Hello world.",
                [_Word(" Hello", 0.0, 0.4), _Word(" world.", 0.4, 1.0)],
            )
        ]
    )
    seen: list[float] = []
    document = transcribe_file(
        audio,
        media_duration=0.1,
        on_progress=lambda ratio, message: seen.append(ratio),
        should_cancel=lambda: False,
        model_loader=lambda: model,
    )
    assert model.unloaded is True
    assert document["text"] == "Hello world."
    assert document["sentences"][0]["words"][0]["word"] == " Hello"
    assert seen == [1.0]
    assert any("extends past" in warning for warning in document["warnings"])


def test_cancel_still_unloads_the_model(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"unused")
    model = _Model(
        [
            _Segment(0.0, 1.0, "Hello.", [_Word(" Hello.", 0.0, 1.0)]),
            _Segment(1.0, 2.0, "Again.", [_Word(" Again.", 1.0, 2.0)]),
        ]
    )
    checks = {"n": 0}

    def should_cancel() -> bool:
        checks["n"] += 1
        return checks["n"] >= 2

    with pytest.raises(CancelledError):
        transcribe_file(
            audio,
            media_duration=2.0,
            on_progress=lambda ratio, message: None,
            should_cancel=should_cancel,
            model_loader=lambda: model,
        )
    assert model.unloaded is True
