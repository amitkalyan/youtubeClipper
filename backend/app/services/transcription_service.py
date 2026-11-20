"""Faster-Whisper on CPU. The model is loaded for one file, then released."""

from __future__ import annotations

import gc
import logging
import os
from collections.abc import Callable
from pathlib import Path

from app.config import Settings, get_settings
from app.errors import CancelledError, TranscriptionError

logger = logging.getLogger("clipper.transcription")


def transcribe_file(
    audio_path: Path,
    *,
    media_duration: float,
    on_progress: Callable[[float, str], None],
    should_cancel: Callable[[], bool],
    model_loader: Callable[[], object] | None = None,
) -> dict:
    settings = get_settings()
    settings.assert_hardware_profile()
    loader = model_loader or (lambda: _load_model(settings))
    try:
        model = loader()
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(
            "Could not load the Whisper model. The first run needs network access to download "
            f"the '{settings.whisper_model}' model. {exc}"
        ) from exc
    try:
        if should_cancel():
            raise CancelledError("Transcription cancelled.")
        segments_iter, info = model.transcribe(  # type: ignore[attr-defined]
            str(audio_path),
            beam_size=1,
            word_timestamps=True,
            vad_filter=settings.whisper_vad_filter,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        raw_segments: list[dict] = []
        for segment in segments_iter:
            if should_cancel():
                raise CancelledError("Transcription cancelled.")
            raw_segments.append(_segment_to_dict(segment))
            ratio = 0.0
            if media_duration > 0:
                ratio = min(1.0, float(segment.end) / media_duration)
            on_progress(ratio, f"Transcribed through {float(segment.end):.1f}s")
        detected = getattr(info, "duration", None)
        chosen = media_duration if media_duration and media_duration > 0 else detected
        document = assemble_transcript(
            raw_segments,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration=float(chosen) if chosen is not None else None,
            model=settings.whisper_model,
        )
        problems = hard_problems(document)
        if problems:
            raise TranscriptionError(
                "Transcript timestamps failed validation: " + "; ".join(problems)
            )
        document["warnings"] = collect_warnings(document, document.get("duration"))
        return document
    except CancelledError:
        raise
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc
    finally:
        _release_model(model)


def assemble_transcript(
    raw_segments: list[dict],
    *,
    language: str | None,
    language_probability: float | None,
    duration: float | None,
    model: str,
) -> dict:
    sentences = group_sentences(raw_segments)
    text = " ".join(sentence["text"] for sentence in sentences).strip()
    probability = None
    if language_probability is not None:
        probability = round(float(language_probability), 4)
    return {
        "language": language,
        "language_probability": probability,
        "model": model,
        "duration": round(float(duration), 3) if duration is not None else None,
        "text": text,
        "segments": raw_segments,
        "sentences": sentences,
        "warnings": [],
    }


def group_sentences(raw_segments: list[dict]) -> list[dict]:
    """Split on spoken punctuation. Tokens are copied, never rewritten."""
    sentences: list[dict] = []
    bucket: list[dict] = []

    def flush() -> None:
        if not bucket:
            return
        text = "".join(word["word"] for word in bucket).strip()
        words = [dict(word) for word in bucket]
        bucket.clear()
        if not text:
            return
        sentences.append(
            {
                "id": len(sentences),
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": text,
                "words": words,
            }
        )

    for segment in raw_segments:
        words = segment.get("words") or []
        if not words:
            flush()
            text = str(segment.get("text") or "").strip()
            if text:
                sentences.append(
                    {
                        "id": len(sentences),
                        "start": segment["start"],
                        "end": segment["end"],
                        "text": text,
                        "words": [],
                    }
                )
            continue
        for word in words:
            bucket.append(word)
            token = str(word["word"]).strip()
            if token.endswith((".", "?", "!", "…")):
                flush()
    flush()
    return sentences


def hard_problems(document: dict) -> list[str]:
    problems: list[str] = []
    for sentence in document.get("sentences") or []:
        start = float(sentence["start"])
        end = float(sentence["end"])
        if end + 0.05 < start:
            problems.append(f"Sentence {sentence['id']} ends before it starts.")
        previous_start: float | None = None
        for word in sentence.get("words") or []:
            word_start = float(word["start"])
            word_end = float(word["end"])
            if word_end + 0.05 < word_start:
                problems.append(f"A word in sentence {sentence['id']} has backwards timestamps.")
                break
            if previous_start is not None and word_start + 0.05 < previous_start:
                problems.append(f"Words in sentence {sentence['id']} are out of order.")
                break
            previous_start = word_start
    return problems


def collect_warnings(document: dict, media_duration: float | None) -> list[str]:
    warnings: list[str] = []
    sentences = document.get("sentences") or []
    if not sentences:
        warnings.append("No speech detected.")
    previous_end: float | None = None
    for sentence in sentences:
        start = float(sentence["start"])
        end = float(sentence["end"])
        if previous_end is not None and start + 0.2 < previous_end:
            warnings.append(f"Sentence {sentence['id']} overlaps the previous sentence.")
        if media_duration is not None and end > float(media_duration) + 0.75:
            warnings.append(f"Sentence {sentence['id']} extends past the end of the audio.")
        previous_end = end
    return warnings


def _load_model(settings: Settings) -> object:
    cache = settings.resolved_model_cache()
    whisper_dir = cache / "whisper"
    hf_dir = cache / "hf"
    whisper_dir.mkdir(parents=True, exist_ok=True)
    hf_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(hf_dir))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_dir / "hub"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    threads = str(settings.effective_threads())
    os.environ["OMP_NUM_THREADS"] = threads
    os.environ["MKL_NUM_THREADS"] = threads
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionError(
            "faster-whisper is not installed. Install backend/requirements.txt."
        ) from exc
    logger.info(
        "Loading Whisper model=%s device=%s compute=%s threads=%s",
        settings.whisper_model,
        settings.whisper_device,
        settings.whisper_compute_type,
        settings.effective_threads(),
    )
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        cpu_threads=settings.effective_threads(),
        num_workers=1,
        download_root=str(whisper_dir),
    )


def _release_model(model: object) -> None:
    inner = getattr(model, "model", None)
    unload = getattr(inner, "unload_model", None)
    if not callable(unload):
        unload = getattr(model, "unload", None)
    if callable(unload):
        try:
            unload()
        except Exception:
            logger.exception("Could not unload the speech model")
    del model
    gc.collect()


def _segment_to_dict(segment: object) -> dict:
    words = []
    for word in getattr(segment, "words", None) or []:
        probability = getattr(word, "probability", None)
        words.append(
            {
                "word": str(word.word),
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3),
                "probability": round(float(probability), 4) if probability is not None else None,
            }
        )
    return {
        "start": round(float(segment.start), 3),  # type: ignore[attr-defined]
        "end": round(float(segment.end), 3),  # type: ignore[attr-defined]
        "text": str(getattr(segment, "text", "") or "").strip(),
        "words": words,
    }
