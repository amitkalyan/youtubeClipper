"""One Ollama chat at a time. Any model already installed in Ollama can be used."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

import httpx

from app import db
from app.config import get_settings
from app.errors import CancelledError, OllamaError

logger = logging.getLogger("clipper.ollama")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def installed_models() -> list[str] | None:
    """Model names from Ollama. None means the server did not answer."""
    try:
        response = httpx.get(f"{_host()}/api/tags", timeout=0.8)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None
    names: list[str] = []
    for item in payload.get("models") or []:
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def match_model(wanted: str | None, installed: list[str]) -> str | None:
    if not wanted or not wanted.strip():
        return None
    wanted = wanted.strip()
    if wanted in installed:
        return wanted
    if ":" in wanted:
        return None
    for name in installed:
        if name.split(":", 1)[0] == wanted:
            return name
    return None


def choose_model(installed: list[str], preferred: str | None, configured: str) -> str:
    if not installed:
        raise OllamaError(
            "Ollama has no models installed. Pull any model, then choose it in Settings."
        )
    for candidate in (preferred, configured):
        match = match_model(candidate, installed)
        if match:
            return match
    return installed[0]


def status() -> dict:
    host = _host()
    installed = installed_models()
    saved = _saved_model()
    configured = get_settings().ollama_model.strip()
    if installed is None:
        return {
            "host": host,
            "model": saved or configured,
            "models": [],
            "used_in_phase": 2,
            "note": (
                f"Not running at {host}. Start Ollama. "
                "Any model you have pulled can be chosen in Settings."
            ),
        }
    if not installed:
        return {
            "host": host,
            "model": saved or configured,
            "models": [],
            "used_in_phase": 2,
            "note": "Ollama is running, but no models are installed. Pull any model, then choose it in Settings.",
        }
    model = choose_model(installed, saved, configured)
    if saved and match_model(saved, installed) is None:
        note = f"Using {model}. The saved choice is no longer installed."
    elif not saved and match_model(configured, installed) is None:
        note = f"Using {model}. {configured} is not installed, so another local model is used."
    else:
        note = f"Ready · {model}. Any installed Ollama model can be chosen in Settings."
    return {
        "host": host,
        "model": model,
        "models": installed,
        "used_in_phase": 2,
        "note": note,
    }


def select_model(name: str) -> str:
    installed = installed_models()
    if installed is None:
        raise OllamaError(f"Cannot reach Ollama at {_host()}. Start it, then choose a model.")
    match = match_model(name, installed)
    if match is None:
        raise OllamaError(f"{name.strip() or 'That model'} is not installed in Ollama.")
    db.set_setting("ollama_model", match)
    return match


def active_model() -> str:
    installed = installed_models()
    saved = _saved_model()
    configured = get_settings().ollama_model.strip()
    if installed is None:
        return saved or configured
    return choose_model(installed, saved, configured)


def chat(
    prompt: str,
    *,
    should_cancel: Callable[[], bool],
    keep_alive: int | str,
    system: str | None = None,
) -> str:
    settings = get_settings()
    if should_cancel():
        raise CancelledError("Cancelled.")
    model = active_model()
    payload = {
        "model": model,
        "stream": True,
        "format": "json",
        "keep_alive": keep_alive,
        "messages": [
            {
                "role": "system",
                "content": system
                or (
                    "You select short video moments from a transcript. "
                    "Return one JSON object with a clips array. Do not add facts that were not spoken."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "options": {
            "temperature": 0.1,
            "num_ctx": _num_ctx(),
            "num_predict": 1200,
            "num_gpu": 0,
            "num_thread": settings.effective_threads(),
        },
    }
    parts: list[str] = []
    timeout = httpx.Timeout(10.0, read=float(settings.ollama_timeout_seconds))
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", f"{_host()}/api/chat", json=payload) as response:
                if response.status_code != 200:
                    body = response.read().decode("utf-8", errors="replace")
                    raise OllamaError(_http_error(response.status_code, body, model))
                for line in response.iter_lines():
                    if should_cancel():
                        raise CancelledError("Cancelled.")
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OllamaError("Ollama returned invalid JSON.") from exc
                    if data.get("error"):
                        raise OllamaError(_memory_or_text(str(data["error"]), model))
                    content = (data.get("message") or {}).get("content") or ""
                    parts.append(content)
                    if data.get("done"):
                        break
    except CancelledError:
        raise
    except OllamaError:
        raise
    except httpx.TimeoutException as exc:
        raise OllamaError("Ollama took too long. The transcript was kept. Try again when the machine is idle.") from exc
    except httpx.HTTPError as exc:
        raise OllamaError(
            f"Cannot reach Ollama at {_host()}. Start it, then choose any model you have pulled."
        ) from exc
    text = "".join(parts).strip()
    if not text:
        raise OllamaError("Ollama returned an empty response.")
    return text


def unload() -> None:
    try:
        model = active_model()
    except OllamaError:
        return
    try:
        httpx.post(
            f"{_host()}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=8.0,
        )
    except httpx.HTTPError:
        logger.info("Ollama unload was skipped because the server did not answer.")


def parse_clip_response(text: str) -> list[dict]:
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama returned invalid JSON.") from exc
    if isinstance(data, dict):
        clips = data.get("clips", [])
    elif isinstance(data, list):
        clips = data
    else:
        raise OllamaError("Ollama returned invalid JSON.")
    if not isinstance(clips, list):
        raise OllamaError("Ollama returned invalid JSON.")
    return [item for item in clips if isinstance(item, dict)]


def _host() -> str:
    return get_settings().ollama_host.rstrip("/")


def _num_ctx() -> int:
    value = int(get_settings().ollama_num_ctx)
    return max(2048, min(8192, value))


def _saved_model() -> str | None:
    value = db.get_setting("ollama_model")
    if value is None or not value.strip():
        return None
    return value.strip()


def _http_error(status: int, body: str, model: str) -> str:
    if status == 404:
        return f"Ollama does not have {model}. Choose another installed model in Settings."
    return _memory_or_text(body, model)


def _memory_or_text(body: str, model: str) -> str:
    lowered = body.lower()
    if "memory" in lowered:
        return (
            f"Ollama ran out of memory while using {model}. "
            "Close other applications or choose a smaller installed model in Settings."
        )
    if "not found" in lowered:
        return f"Ollama does not have {model}. Choose another installed model in Settings."
    return "Ollama could not score this transcript. The transcript was kept."
