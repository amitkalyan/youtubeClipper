"""Titles, description, hashtags, and a thumbnail headline from the clip transcript.

The model only sees that clip's spoken words. A local image model is not used.
"""

from __future__ import annotations

import json
import re

from app.errors import ClipperError, OllamaError
from app.services.clip_validation_service import CATEGORIES

_BANNED = re.compile(r"\b(viral|guaranteed|must watch|blow up)\b", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Za-z0-9']+")
_QUOTE = re.compile(r"[\"“”']([^\"“”']{2,})[\"“”']")
_SYSTEM = (
    "You write a YouTube Short package from one transcript. "
    "Return one JSON object. Use only facts and phrases from that transcript. "
    "Do not promise views or say the video will perform well."
)


def draft_metadata(raw_text: str, clip: dict) -> dict:
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama returned invalid JSON.") from exc
    if not isinstance(raw, dict):
        raw = {}
    return _normalize(raw, clip, strict_headline=False)


def edit_metadata(incoming: dict, clip: dict, previous: dict | None) -> dict:
    draft = _normalize(incoming, clip, strict_headline=True)
    if previous:
        draft["thumbnail_path"] = previous.get("thumbnail_path")
        draft["frame_path"] = previous.get("frame_path")
        draft["metadata_path"] = previous.get("metadata_path")
    return draft


def prompt_for(clip: dict) -> str:
    transcript = " ".join(str(clip.get("transcript") or "").split())
    return f"""Write the package for this spoken clip.

Transcript:
{transcript}

Return JSON with:
- titles: exactly 3 short titles based on the transcript
- description: one paragraph that only restates what was spoken
- hashtags: 3 to 5 tags whose words appear in the transcript
- headline: a short phrase copied from the transcript, at most 8 words
- cta: one short call to action with no promise of views
- category: {clip.get("category") or "memorable statement"}
- keywords: 3 to 6 words that appear in the transcript

Do not use the words viral, guaranteed, or must watch.
"""


def system_prompt() -> str:
    return _SYSTEM


def _normalize(raw: dict, clip: dict, *, strict_headline: bool) -> dict:
    transcript = " ".join(str(clip.get("transcript") or "").split())
    spoken = _tokens(transcript)
    fallback_title = _clean(str(clip.get("suggested_title") or transcript), 100) or "Short"
    titles = _titles(raw.get("titles"), fallback_title)
    selected = _clean(str(raw.get("selected_title") or ""), 100)
    if selected not in titles:
        selected = titles[0]
    headline = _clean(str(raw.get("headline") or ""), 80)
    if not _uses_spoken_words(headline, spoken):
        if strict_headline:
            raise ClipperError("The headline has to use words from the spoken transcript.")
        headline = _clean(str(clip.get("opening_hook") or transcript), 80) or fallback_title
        if not _uses_spoken_words(headline, spoken):
            headline = _clean(transcript, 80) or fallback_title
    description = _drop_invented_quotes(_clean(str(raw.get("description") or ""), 700), transcript)
    if not description:
        description = transcript[:700]
    hashtags = _hashtags(raw.get("hashtags"), spoken)
    keywords = _keywords(raw.get("keywords"), spoken)
    cta = _clean(str(raw.get("cta") or ""), 120)
    if len(cta) < 3:
        cta = "Watch the rest of this video."
    category = " ".join(str(raw.get("category") or clip.get("category") or "").split()).lower()
    if category not in CATEGORIES:
        category = str(clip.get("category") or "memorable statement")
        if category not in CATEGORIES:
            category = "memorable statement"
    return {
        "titles": titles,
        "selected_title": selected,
        "description": description,
        "hashtags": hashtags,
        "headline": headline,
        "cta": cta,
        "category": category,
        "keywords": keywords,
    }


def _titles(raw: object, fallback: str) -> list[str]:
    values = raw if isinstance(raw, list) else []
    cleaned = []
    for value in values:
        text = _clean(str(value), 100)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) == 3:
            break
    while len(cleaned) < 3:
        filler = fallback if fallback not in cleaned else f"{fallback} {len(cleaned) + 1}"
        cleaned.append(filler[:100])
    return cleaned


def _hashtags(raw: object, spoken: set[str]) -> list[str]:
    found: list[str] = []
    values = raw if isinstance(raw, list) else []
    for value in values:
        tag = _tag(str(value))
        word = tag[1:]
        if word in spoken and tag not in found:
            found.append(tag)
        if len(found) == 5:
            break
    for word in sorted(spoken, key=len, reverse=True):
        if len(found) >= 3:
            break
        tag = f"#{word[:30]}"
        if len(word) > 2 and tag not in found:
            found.append(tag)
    return found[:5]


def _keywords(raw: object, spoken: set[str]) -> list[str]:
    found: list[str] = []
    values = raw if isinstance(raw, list) else []
    for value in values:
        word = "".join(_TOKEN.findall(str(value))).lower()
        if word in spoken and word not in found:
            found.append(word)
        if len(found) == 6:
            break
    if len(found) < 3:
        for word in sorted(spoken):
            if len(word) > 2 and word not in found:
                found.append(word)
            if len(found) == 3:
                break
    return found[:6]


def _tag(value: str) -> str:
    token = "".join(ch for ch in value.lower() if ch.isalnum())
    return f"#{token[:30]}" if token else ""


def _uses_spoken_words(text: str, spoken: set[str]) -> bool:
    words = [word for word in _tokens(text) if len(word) > 2]
    return bool(words) and all(word in spoken for word in words)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN.findall(text)}


def _clean(text: str, limit: int) -> str:
    cleaned = _BANNED.sub("", text)
    return " ".join(cleaned.split())[:limit].strip()


def _drop_invented_quotes(text: str, transcript: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner and inner.lower() in transcript.lower():
            return match.group(0)
        return ""

    return " ".join(_QUOTE.sub(replace, text).split())
