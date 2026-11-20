import os

import pytest

from app.config import get_settings
from app.errors import ClipperError


def test_default_profile_is_cpu_int8(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "base")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("WHISPER_THREADS", "4")
    settings = get_settings()
    settings.assert_hardware_profile()
    assert settings.effective_threads() == min(4, os.cpu_count() or 1)
    assert settings.whisper_compute_type == "int8"


def test_rejects_gpu(monkeypatch):
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    with pytest.raises(ClipperError):
        get_settings().assert_hardware_profile()


def test_rejects_large_model(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "large-v3")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.delenv("CLIPPER_ALLOW_LARGE_MODELS", raising=False)
    with pytest.raises(ClipperError):
        get_settings().assert_hardware_profile()


def test_rejects_parallel_jobs(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "base")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    with pytest.raises(ClipperError):
        get_settings().assert_hardware_profile()


def test_rejects_float16(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "base")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "float16")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    with pytest.raises(ClipperError):
        get_settings().assert_hardware_profile()
