"""Turn model suggestions into sentence-aligned 20 second to 1 minute clips.

The stored quote is always the transcript text. The model cannot add words.
"""

from __future__ import annotations

import re

WEIGHTS = {
    "opening_hook": 25,
    "interesting_content": 20,
    "emotional_impact": 15,
    "context": 15,
    "complete_thought": 10,
    "shareability": 10,
    "av_quality": 3,
}
CATEGORIES = {
    "strong opening",
    "surprising fact",
    "opinion",
    "emotional moment",
    "educational",
    "storytelling",
    "controversial statement",
    "practical tip",
    "curiosity question",
    "memorable statement",
}
MIN_DURATION = 20.0
MAX_DURATION = 60.0
SPEECH_GAP = 2.0


def validate_candidates(sentences: list[dict], raw_clips: list[dict], *, limit: int = 10) -> list[dict]:
    prepared: list[dict] = []
    for raw in raw_clips:
        if not isinstance(raw, dict):
            continue
        window = _window_for(sentences, raw)
        if window is None:
            continue
        prepared.append(_record(window, raw))
    prepared.sort(key=lambda item: (-item["score"], item["start"]))
    kept: list[dict] = []
    for item in prepared:
        if len(kept) >= limit:
            break
        if any(_overlaps(item, other) for other in kept):
            continue
        if any(_same_quote(item, other) for other in kept):
            continue
        kept.append(item)
    kept.sort(key=lambda item: (item["start"], item["end"]))
    for index, item in enumerate(kept):
        item["ordinal"] = index
    return kept


def combine_sentences(sentences: list[dict], *, limit: int = 10) -> list[dict]:
    """Join neighboring sentences into non-overlapping 20 second to 1 minute clips."""
    ordered = _ordered(sentences)
    windows: list[list[dict]] = []
    index = 0
    while index < len(ordered):
        window = _combine_from(ordered, index)
        if window is None:
            index += 1
            continue
        next_index = index + len(window)
        while next_index < len(ordered) and _combine_from(ordered, next_index) is None:
            longer = ordered[index : next_index + 1]
            if _packed_duration(longer) > MAX_DURATION + 0.05:
                break
            window = longer
            next_index += 1
        windows.append(window)
        index = next_index
    if len(windows) > limit:
        windows = _spread(windows, limit)
    clips = [
        _record(
            window,
            {
                "reason": "Neighboring sentences were joined so this short lasts between 20 seconds and 1 minute.",
                "category": "memorable statement",
                "score_breakdown": {
                    "opening_hook": 8,
                    "interesting_content": 8,
                    "emotional_impact": 4,
                    "context": 6,
                    "complete_thought": 8,
                    "shareability": 4,
                    "av_quality": 3,
                },
            },
        )
        for window in windows
    ]
    for ordinal, item in enumerate(clips):
        item["ordinal"] = ordinal
    return clips


def has_short_window(sentences: list[dict]) -> bool:
    ordered = _ordered(sentences)
    for start_index in range(len(ordered)):
        for end_index in range(start_index, len(ordered)):
            span = _packed_duration(ordered[start_index : end_index + 1])
            if span > MAX_DURATION + 0.05:
                break
            if span >= MIN_DURATION - 0.05:
                return True
    return False


def _window_for(sentences: list[dict], raw: dict) -> list[dict] | None:
    ordered = _ordered(sentences)
    by_id = _by_sentence_ids(ordered, raw.get("sentence_ids"))
    covered = by_id if by_id is not None else _by_time(ordered, raw.get("start"), raw.get("end"))
    if not covered:
        return None
    span = _packed_duration(covered)
    if span > MAX_DURATION + 0.05:
        return _shrink(covered, str(raw.get("transcript") or ""))
    if span >= MIN_DURATION - 0.05:
        return covered
    return _grow(ordered, covered)


def _by_sentence_ids(sentences: list[dict], raw_ids: object) -> list[dict] | None:
    if not isinstance(raw_ids, list) or not raw_ids:
        return None
    ids: list[int] = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            return None
    ids = sorted(set(ids))
    if ids != list(range(ids[0], ids[-1] + 1)):
        return None
    chosen = [sentence for sentence in sentences if int(sentence["id"]) in ids]
    if len(chosen) != len(ids):
        return None
    return chosen


def _by_time(sentences: list[dict], start: object, end: object) -> list[dict]:
    start_value = _number(start)
    end_value = _number(end)
    if start_value is None or end_value is None or end_value <= start_value:
        return []
    indexes = [
        index
        for index, sentence in enumerate(sentences)
        if _overlap_amount(sentence, start_value, end_value) >= 0.35
    ]
    if not indexes:
        return []
    return sentences[indexes[0] : indexes[-1] + 1]


def _grow(ordered: list[dict], covered: list[dict]) -> list[dict] | None:
    """Add neighboring sentences until the moment lasts at least 20 seconds."""
    ids = [int(sentence["id"]) for sentence in ordered]
    try:
        start = ids.index(int(covered[0]["id"]))
        end = ids.index(int(covered[-1]["id"]))
    except ValueError:
        return None
    if end < start:
        return None
    while _packed_duration(ordered[start : end + 1]) < MIN_DURATION - 0.05:
        forward = (
            end + 1 < len(ordered)
            and _packed_duration(ordered[start : end + 2]) <= MAX_DURATION + 0.05
        )
        backward = start > 0 and _packed_duration(ordered[start - 1 : end + 1]) <= MAX_DURATION + 0.05
        if not forward and not backward:
            return None
        if forward and (
            not backward
            or _packed_duration(ordered[start : end + 2])
            <= _packed_duration(ordered[start - 1 : end + 1])
        ):
            end += 1
        else:
            start -= 1
    window = ordered[start : end + 1]
    if _packed_duration(window) > MAX_DURATION + 0.05:
        return None
    return window


def _combine_from(ordered: list[dict], index: int) -> list[dict] | None:
    end = index
    while end < len(ordered):
        window = ordered[index : end + 1]
        span = _packed_duration(window)
        if span > MAX_DURATION + 0.05:
            return None
        if span >= MIN_DURATION - 0.05:
            return window
        end += 1
    return None


def _spread(windows: list[list[dict]], limit: int) -> list[list[dict]]:
    count = len(windows)
    picked: list[int] = []
    for slot in range(limit):
        index = round(slot * (count - 1) / max(limit - 1, 1))
        if not picked or picked[-1] != index:
            picked.append(index)
    cursor = 0
    while len(picked) < limit and cursor < count:
        if cursor not in picked:
            picked.append(cursor)
        cursor += 1
    picked.sort()
    return [windows[index] for index in picked[:limit]]


def _shrink(sentences: list[dict], model_text: str) -> list[dict] | None:
    best: list[dict] | None = None
    best_key: tuple[float, float] | None = None
    for start_index in range(len(sentences)):
        for end_index in range(start_index, len(sentences)):
            window = sentences[start_index : end_index + 1]
            span = _packed_duration(window)
            if span > MAX_DURATION + 0.05:
                break
            if span < MIN_DURATION - 0.05:
                continue
            key = (_quote_overlap(model_text, _join(window)), span)
            if best_key is None or key > best_key:
                best_key = key
                best = window
    return best


def _record(window: list[dict], raw: dict) -> dict:
    transcript = _join(window)
    breakdown = _breakdown(raw.get("score_breakdown"))
    first = str(window[0].get("text") or "").strip()
    segments = [
        {"start": round(item["start"], 3), "end": round(item["end"], 3)}
        for item in _speech_segments(window)
    ]
    reason = _clip_text(str(raw.get("reason") or ""), 500) or "These sentences form a complete thought."
    if len(segments) > 1:
        reason = _clip_text(
            reason + " Other speech already in this transcript was joined, and pauses longer than 2 seconds were left out.",
            500,
        )
    return {
        "start": segments[0]["start"],
        "end": segments[-1]["end"],
        "duration": round(sum(item["end"] - item["start"] for item in segments), 3),
        "segments": segments,
        "transcript": transcript,
        "opening_hook": _hook(str(raw.get("opening_hook") or ""), transcript, first),
        "category": _category(str(raw.get("category") or "")),
        "score": sum(breakdown.values()),
        "score_breakdown": breakdown,
        "reason": reason,
        "suggested_title": _title(str(raw.get("suggested_title") or ""), transcript),
    }


def _breakdown(raw: object) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    values: dict[str, int] = {}
    for key, maximum in WEIGHTS.items():
        number = _number(source.get(key))
        if number is None:
            number = 0
        values[key] = max(0, min(maximum, int(round(number))))
    return values


def _hook(hook: str, transcript: str, first: str) -> str:
    cleaned = " ".join(hook.split())
    if cleaned and cleaned.lower() in transcript.lower():
        return cleaned[:180]
    return first[:180] or transcript[:180]


def _title(title: str, transcript: str) -> str:
    cleaned = " ".join(title.split())
    cleaned = re.sub(r"\b(viral|guaranteed|must watch)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = transcript
    return cleaned[:120]


def _category(value: str) -> str:
    cleaned = " ".join(value.split()).lower()
    if cleaned in CATEGORIES:
        return cleaned
    return "memorable statement"


def _ordered(sentences: list[dict]) -> list[dict]:
    return sorted(sentences, key=lambda sentence: (float(sentence["start"]), int(sentence["id"])))


def _span(sentences: list[dict]) -> float:
    return float(sentences[-1]["end"]) - float(sentences[0]["start"])


def _speech_segments(sentences: list[dict]) -> list[dict]:
    """Keep pauses of 2 seconds or less. A longer pause starts another spoken part."""
    segments: list[dict] = []
    for sentence in sentences:
        start = float(sentence["start"])
        end = float(sentence["end"])
        if end <= start:
            continue
        if segments and start - float(segments[-1]["end"]) <= SPEECH_GAP:
            segments[-1]["end"] = max(float(segments[-1]["end"]), end)
        else:
            segments.append({"start": start, "end": end})
    return segments


def _packed_duration(sentences: list[dict]) -> float:
    return sum(item["end"] - item["start"] for item in _speech_segments(sentences))


def _join(sentences: list[dict]) -> str:
    return " ".join(" ".join(str(sentence.get("text") or "").split()) for sentence in sentences).strip()


def _overlap_amount(sentence: dict, start: float, end: float) -> float:
    return min(float(sentence["end"]), end) - max(float(sentence["start"]), start)


def _overlaps(left: dict, right: dict) -> bool:
    for left_part in _ranges(left):
        for right_part in _ranges(right):
            if left_part["start"] < right_part["end"] and left_part["end"] > right_part["start"]:
                return True
    return False


def _ranges(item: dict) -> list[dict]:
    raw = item.get("segments")
    if isinstance(raw, list) and raw:
        return [{"start": float(part["start"]), "end": float(part["end"])} for part in raw]
    return [{"start": float(item["start"]), "end": float(item["end"])}]


def _same_quote(left: dict, right: dict) -> bool:
    return " ".join(left["transcript"].lower().split()) == " ".join(right["transcript"].lower().split())


def _quote_overlap(model_text: str, exact: str) -> float:
    model_words = re.findall(r"[a-z0-9']+", model_text.lower())
    exact_words = re.findall(r"[a-z0-9']+", exact.lower())
    if not model_words or not exact_words:
        return 0.0
    exact_set = set(exact_words)
    shared = sum(1 for word in model_words if word in exact_set)
    return shared / len(model_words)


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clip_text(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]
