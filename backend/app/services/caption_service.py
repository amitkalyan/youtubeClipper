"""Word-timed captions. Every word comes from the saved transcript."""

from __future__ import annotations

import re


def clip_cues(sentences: list[dict], start: float, end: float, hook: str) -> list[dict]:
    words = _words(sentences, start, end)
    if not words:
        words = _sentence_fallback(sentences, start, end)
    hook_tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9']+", hook or "")
        if len(token) > 2
    }
    cues: list[dict] = []
    for index, word in enumerate(words):
        cue_end = float(word["end"])
        if index + 1 < len(words):
            cue_end = min(cue_end, float(words[index + 1]["start"]))
        if cue_end <= float(word["start"]):
            cue_end = float(word["start"]) + 0.08
        text = _plain(str(word["text"]))
        if not text:
            continue
        tokens = {token.casefold() for token in re.findall(r"[A-Za-z0-9']+", text)}
        cues.append(
            {
                "text": text,
                "start": float(word["start"]),
                "end": cue_end,
                "emphasis": bool(tokens & hook_tokens),
            }
        )
    return cues


def cues_for_segments(sentences: list[dict], segments: list[dict], hook: str) -> list[dict]:
    """Place each spoken part on the joined timeline, after the pauses are removed."""
    cues: list[dict] = []
    offset = 0.0
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        for cue in clip_cues(sentences, start, end, hook):
            cues.append(
                {
                    "text": cue["text"],
                    "start": float(cue["start"]) + offset,
                    "end": float(cue["end"]) + offset,
                    "emphasis": cue["emphasis"],
                }
            )
        offset += max(0.0, end - start)
    return cues


def caption_alignment(face_y: float | None, height: int) -> int:
    """Bottom captions unless the face sits in the lower part of the frame."""
    if face_y is None or height <= 0:
        return 2
    if face_y > height * 0.62:
        return 8
    return 2


def build_ass(cues: list[dict], *, play_x: int, play_y: int, alignment: int) -> str:
    font = max(18, round(play_y * 0.045))
    margin = max(24, round(play_y * 0.1))
    outline = max(2, round(play_y / 220))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_x}",
        f"PlayResY: {play_y}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Caption,Segoe UI,"
        f"{font},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{outline},0,"
        f"{alignment},40,40,{margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        text = cue["text"]
        if cue["emphasis"]:
            text = r"{\b1\c&H004DB8FF&}" + text + r"{\r}"
        lines.append(
            f"Dialogue: 0,{_ass_time(cue['start'])},{_ass_time(cue['end'])},Caption,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def build_srt(cues: list[dict]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{_srt_time(cue['start'])} --> {_srt_time(cue['end'])}\n{cue['text']}\n"
        )
    return "\n".join(blocks)


def _words(sentences: list[dict], start: float, end: float) -> list[dict]:
    found: list[dict] = []
    for sentence in sentences:
        for word in sentence.get("words") or []:
            word_start = _float(word.get("start"))
            word_end = _float(word.get("end"))
            if word_start is None or word_end is None:
                continue
            if word_end <= start or word_start >= end:
                continue
            text = str(word.get("word") or "").strip()
            if not text:
                continue
            found.append(
                {
                    "text": text,
                    "start": max(0.0, word_start - start),
                    "end": max(0.08, min(end, word_end) - start),
                }
            )
    return found


def _sentence_fallback(sentences: list[dict], start: float, end: float) -> list[dict]:
    texts: list[str] = []
    for sentence in sentences:
        sentence_start = _float(sentence.get("start"))
        sentence_end = _float(sentence.get("end"))
        if sentence_start is None or sentence_end is None:
            continue
        if sentence_end <= start or sentence_start >= end:
            continue
        text = str(sentence.get("text") or "").strip()
        if text:
            texts.append(text)
    if not texts:
        return []
    return [{"text": " ".join(texts), "start": 0.0, "end": max(0.4, end - start)}]


def _plain(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _ass_time(seconds: float) -> str:
    total = int(round(max(0.0, seconds) * 100))
    centi = total % 100
    whole = total // 100
    second = whole % 60
    minute = (whole // 60) % 60
    hour = whole // 3600
    return f"{hour}:{minute:02d}:{second:02d}.{centi:02d}"


def _srt_time(seconds: float) -> str:
    total = int(round(max(0.0, seconds) * 1000))
    milli = total % 1000
    whole = total // 1000
    second = whole % 60
    minute = (whole // 60) % 60
    hour = whole // 3600
    return f"{hour:02d}:{minute:02d}:{second:02d},{milli:03d}"
