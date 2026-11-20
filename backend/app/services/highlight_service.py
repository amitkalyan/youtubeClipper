"""Ask Ollama for moments, then keep only sentence-aligned 20 second to 1 minute clips."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.errors import CancelledError, OllamaError
from app.services import clip_validation_service, ollama_service

logger = logging.getLogger("clipper.highlights")

_CHUNK_CHARS = 2800


def find_clips(
    document: dict,
    *,
    on_progress: Callable[[float, str], None],
    should_cancel: Callable[[], bool],
    chat: Callable[..., str] | None = None,
) -> list[dict]:
    sentences = [sentence for sentence in document.get("sentences") or [] if isinstance(sentence, dict)]
    if not clip_validation_service.has_short_window(sentences):
        on_progress(1.0, "The spoken audio is under 20 seconds, so there is no other speech to add.")
        return []
    if chat is None and not _ollama_ready():
        logger.info("Ollama is off. Joining speech without a model.")
        return _joined_clips(sentences, on_progress, offline=True)
    chunks = chunk_lines(_lines(sentences))
    caller = chat or ollama_service.chat
    raw: list[dict] = []
    try:
        for index, chunk in enumerate(chunks):
            if should_cancel():
                raise CancelledError("Cancelled.")
            on_progress(
                index / max(len(chunks), 1),
                f"Scoring transcript part {index + 1} of {len(chunks)}.",
            )
            last = index == len(chunks) - 1
            try:
                text = caller(
                    _prompt(chunk),
                    should_cancel=should_cancel,
                    keep_alive=0 if last else "10m",
                )
            except OllamaError as exc:
                logger.warning("Ollama scoring stopped: %s", exc)
                break
            raw.extend(ollama_service.parse_clip_response(text))
    finally:
        if chat is None:
            ollama_service.unload()
    clips = clip_validation_service.validate_candidates(sentences, raw) if raw else []
    if clips:
        logger.info("Highlight candidates kept=%s suggested=%s", len(clips), len(raw))
        on_progress(1.0, f"{len(clips)} clip candidate{'s' if len(clips) != 1 else ''}.")
        return clips
    return _joined_clips(sentences, on_progress, offline=False)


def _ollama_ready() -> bool:
    installed = ollama_service.installed_models()
    return bool(installed)


def _joined_clips(
    sentences: list[dict],
    on_progress: Callable[[float, str], None],
    *,
    offline: bool,
) -> list[dict]:
    clips = clip_validation_service.combine_sentences(sentences)
    logger.info("Joined neighboring sentences clips=%s offline=%s", len(clips), offline)
    if not clips:
        on_progress(1.0, "The spoken audio is under 20 seconds, so there is no other speech to add.")
        return []
    count = f"{len(clips)} short{'s' if len(clips) != 1 else ''}"
    if offline:
        message = f"Ollama is off. Joined speech into {count}."
    else:
        message = f"Joined neighboring sentences into {count}."
    on_progress(1.0, message)
    return clips


def chunk_lines(lines: list[str], limit: int = _CHUNK_CHARS) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + 1
        if current and size + extra > limit:
            chunks.append(current)
            current = current[-2:]
            size = sum(len(item) + 1 for item in current)
        current.append(line)
        size += extra
    if current:
        chunks.append(current)
    return chunks or [[]]


def _lines(sentences: list[dict]) -> list[str]:
    lines = []
    for sentence in sentences:
        text = " ".join(str(sentence.get("text") or "").split())
        lines.append(
            f"{int(sentence['id'])}|{float(sentence['start']):.2f}|{float(sentence['end']):.2f}|{text}"
        )
    return lines


def _prompt(lines: list[str]) -> str:
    joined = "\n".join(lines)
    return f"""Choose moments that last from 20 seconds to 1 minute.

Rules:
- Use only the sentences below. Copy their words into transcript.
- sentence_ids must be a contiguous list of the id numbers you used.
- start and end must match the first and last selected sentence.
- Each moment must be at least 20 seconds and at most 60 seconds.
- One sentence is often shorter than 20 seconds of speech. Join it with other spoken sentences from this transcript until the speech reaches 20 seconds. Stop at 60 seconds.
- A pause longer than 2 seconds does not count. Leave that pause out and continue with the next speech.
- Do not overlap clips. Do not invent quotes.
- opening_hook must be an exact phrase from transcript.
- category is one of: strong opening, surprising fact, opinion, emotional moment, educational, storytelling, controversial statement, practical tip, curiosity question, memorable statement.
- Score caps: opening_hook 25, interesting_content 20, emotional_impact 15, context 15, complete_thought 10, shareability 10, av_quality 3.
- You have not seen the picture, so av_quality cannot be above 3.
- score equals the sum of the breakdown.
- Return at most 4 clips. If none qualify, return {{"clips": []}}.

Each line is id|start|end|text
{joined}
"""
