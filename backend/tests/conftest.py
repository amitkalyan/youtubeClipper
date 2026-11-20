"""API tests get a fresh data directory and the shared Whisper cache."""

from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("WHISPER_MODEL", "base")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("WHISPER_THREADS", "2")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("MAX_QUEUED_JOBS", "4")
    from app.config import project_root

    monkeypatch.setenv("CLIPPER_MODEL_CACHE", str(project_root() / "data" / "models"))
    from app.errors import FFmpegNotFoundError
    from app.services.video_service import assert_tools_available

    try:
        assert_tools_available()
    except FFmpegNotFoundError as exc:
        pytest.skip(str(exc))

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client, data
