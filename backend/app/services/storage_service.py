"""Project paths. Ids are UUIDs so a request cannot escape the data directory."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.config import ALLOWED_EXTENSIONS, get_settings
from app.errors import InvalidMediaError, NotFoundError


def assert_project_id(project_id: str) -> str:
    try:
        return str(uuid.UUID(project_id))
    except ValueError as exc:
        raise NotFoundError("Project not found.") from exc


def project_dir(project_id: str) -> Path:
    return get_settings().data_dir / "projects" / assert_project_id(project_id)


def source_path(project_id: str, suffix: str) -> Path:
    if suffix not in ALLOWED_EXTENSIONS:
        raise InvalidMediaError("Unsupported video type.")
    return project_dir(project_id) / f"source{suffix}"


def audio_path(project_id: str) -> Path:
    return project_dir(project_id) / "work" / "audio.wav"


def transcript_path(project_id: str) -> Path:
    return project_dir(project_id) / "work" / "transcript.json"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
