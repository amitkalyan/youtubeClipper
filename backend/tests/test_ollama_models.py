"""Highlight detection can use any model Ollama already has installed."""

from __future__ import annotations

import pytest

from app.errors import OllamaError
from app.services.ollama_service import choose_model, match_model


def test_match_accepts_a_bare_name_or_the_full_tag():
    installed = ["llama3.2:3b", "phi3:mini", "qwen2.5:3b"]
    assert match_model("phi3:mini", installed) == "phi3:mini"
    assert match_model("llama3.2", installed) == "llama3.2:3b"
    assert match_model("missing", installed) is None
    assert match_model("llama3.2:70b", installed) is None


def test_choose_model_falls_back_when_the_preferred_name_is_absent():
    installed = ["llama3.2:3b", "mistral:7b"]
    assert choose_model(installed, None, "qwen2.5:3b") == "llama3.2:3b"
    assert choose_model(installed, "mistral", "qwen2.5:3b") == "mistral:7b"
    assert choose_model(["qwen2.5:3b", "llama3.2:3b"], None, "qwen2.5:3b") == "qwen2.5:3b"
    with pytest.raises(OllamaError):
        choose_model([], None, "qwen2.5:3b")


def test_settings_can_switch_to_another_installed_model(client, monkeypatch):
    http, _data = client
    installed = ["llama3.2:3b", "phi3:mini"]
    monkeypatch.setattr("app.services.ollama_service.installed_models", lambda: installed)

    health = http.get("/api/health")
    assert health.status_code == 200
    body = health.json()["ollama"]
    assert body["models"] == installed
    assert body["model"] == "llama3.2:3b"

    saved = http.put("/api/settings/ollama-model", json={"model": "phi3"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["model"] == "phi3:mini"

    again = http.get("/api/health").json()["ollama"]
    assert again["model"] == "phi3:mini"

    missing = http.put("/api/settings/ollama-model", json={"model": "not-installed"})
    assert missing.status_code == 400
