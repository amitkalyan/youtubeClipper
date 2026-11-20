"""SQLite storage for projects, media, transcripts, and jobs.

One connection, guarded by app.lock. The transcript body lives in a JSON file.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import get_settings
from app.lock import lock
from app.services.video_service import MediaInfo

_conn: sqlite3.Connection | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  progress REAL NOT NULL DEFAULT 0,
  progress_message TEXT NOT NULL DEFAULT '',
  current_job_id TEXT,
  source_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_videos (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL UNIQUE REFERENCES projects(id),
  original_filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  file_size_bytes INTEGER NOT NULL,
  duration_seconds REAL,
  width INTEGER,
  height INTEGER,
  fps REAL,
  video_codec TEXT,
  audio_codec TEXT,
  sample_rate INTEGER,
  channels INTEGER,
  has_audio INTEGER NOT NULL DEFAULT 0,
  has_video INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transcripts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL UNIQUE REFERENCES projects(id),
  language TEXT,
  model TEXT NOT NULL,
  duration_seconds REAL,
  segment_count INTEGER NOT NULL,
  sentence_count INTEGER NOT NULL,
  json_path TEXT NOT NULL,
  text_preview TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  status TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT '',
  progress REAL NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '',
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);

CREATE TABLE IF NOT EXISTS candidate_clips (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  ordinal INTEGER NOT NULL,
  start_seconds REAL NOT NULL,
  end_seconds REAL NOT NULL,
  duration_seconds REAL NOT NULL,
  transcript TEXT NOT NULL,
  opening_hook TEXT NOT NULL,
  category TEXT NOT NULL,
  score INTEGER NOT NULL,
  score_breakdown TEXT NOT NULL,
  reason TEXT NOT NULL,
  suggested_title TEXT NOT NULL,
  segments TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clips_project ON candidate_clips(project_id, ordinal);

CREATE TABLE IF NOT EXISTS clip_renders (
  clip_id TEXT PRIMARY KEY REFERENCES candidate_clips(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL,
  status TEXT NOT NULL,
  crop_mode TEXT,
  manual_offset REAL NOT NULL DEFAULT 0,
  use_manual INTEGER NOT NULL DEFAULT 0,
  crop_path TEXT,
  preview_path TEXT,
  export_path TEXT,
  subtitle_path TEXT,
  error TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clip_metadata (
  clip_id TEXT PRIMARY KEY REFERENCES candidate_clips(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL,
  titles TEXT NOT NULL,
  selected_title TEXT NOT NULL,
  description TEXT NOT NULL,
  hashtags TEXT NOT NULL,
  headline TEXT NOT NULL,
  cta TEXT NOT NULL,
  category TEXT NOT NULL,
  keywords TEXT NOT NULL,
  thumbnail_path TEXT,
  frame_path TEXT,
  metadata_path TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

_PROJECT_SQL = """
SELECT
  p.id, p.title, p.status, p.error, p.progress, p.progress_message,
  p.created_at, p.updated_at, p.current_job_id, p.source_url,
  s.original_filename, s.stored_path, s.file_size_bytes, s.duration_seconds,
  s.width, s.height, s.fps, s.video_codec, s.audio_codec,
  s.sample_rate AS audio_sample_rate, s.channels AS audio_channels,
  s.has_audio, s.has_video,
  CASE WHEN t.id IS NULL THEN 0 ELSE 1 END AS has_transcript,
  (SELECT COUNT(*) FROM candidate_clips c WHERE c.project_id = p.id) AS clip_count
FROM projects p
LEFT JOIN source_videos s ON s.project_id = p.id
LEFT JOIN transcripts t ON t.project_id = p.id
"""

_JOB_SQL = """
SELECT
  j.id, j.project_id, j.status, j.stage, j.progress, j.message, j.error,
  j.created_at, j.started_at, j.finished_at, j.kind, j.target_id, p.title AS project_title
FROM jobs j
JOIN projects p ON p.id = j.project_id
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connection() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database is not initialized.")
    return _conn


def init_db() -> None:
    global _conn
    close()
    settings = get_settings()
    settings.ensure_dirs()
    _conn = sqlite3.connect(settings.data_dir / "clipper.db", check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=5000")
    _conn.executescript(SCHEMA_SQL)
    _migrate(_conn)
    row = _conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        _conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    else:
        _conn.execute("UPDATE schema_version SET version=5")
    _conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    if "source_url" not in project_columns:
        conn.execute("ALTER TABLE projects ADD COLUMN source_url TEXT")
    job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "kind" not in job_columns:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'transcribe'"
        )
    if "target_id" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN target_id TEXT")
    clip_columns = {row["name"] for row in conn.execute("PRAGMA table_info(candidate_clips)")}
    if "segments" not in clip_columns:
        conn.execute("ALTER TABLE candidate_clips ADD COLUMN segments TEXT")


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def fail_interrupted_jobs() -> None:
    now = utcnow()
    message = "Interrupted by an application restart."
    with lock:
        conn = _connection()
        conn.execute(
            """
            UPDATE jobs
            SET status='failed', error=?, message=?, finished_at=?
            WHERE status IN ('queued', 'running')
            """,
            (message, message, now),
        )
        conn.execute(
            """
            UPDATE projects
            SET status='failed', error=?, progress_message=?, updated_at=?
            WHERE status IN (
              'queued', 'downloading', 'extracting_audio', 'transcribing', 'analyzing',
              'rendering', 'packaging'
            )
            """,
            (message, message, now),
        )
        conn.commit()


def create_project(
    title: str,
    *,
    source_url: str | None = None,
    status: str = "uploaded",
    message: str = "Video uploaded.",
) -> str:
    project_id = str(uuid.uuid4())
    now = utcnow()
    with lock:
        _connection().execute(
            """
            INSERT INTO projects (
              id, title, status, error, progress, progress_message,
              current_job_id, source_url, created_at, updated_at
            ) VALUES (?, ?, ?, NULL, 0, ?, NULL, ?, ?, ?)
            """,
            (project_id, title, status, message[:300], source_url, now, now),
        )
        _connection().commit()
    return project_id


def update_project(project_id: str, **fields: object) -> None:
    allowed = {"title", "status", "error", "progress", "progress_message", "current_job_id"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown project fields: {sorted(unknown)}")
    if not fields:
        return
    values = dict(fields)
    values["updated_at"] = utcnow()
    assignments = ", ".join(f"{key}=?" for key in values)
    with lock:
        _connection().execute(
            f"UPDATE projects SET {assignments} WHERE id=?",
            (*values.values(), project_id),
        )
        _connection().commit()


def fail_project(project_id: str, error: str) -> None:
    text = error[:1000]
    update_project(project_id, status="failed", error=text, progress_message=text[:300])


def insert_source(
    project_id: str,
    *,
    original_filename: str,
    stored_path: str,
    info: MediaInfo,
    file_size: int,
) -> None:
    with lock:
        _connection().execute(
            """
            INSERT INTO source_videos (
              id, project_id, original_filename, stored_path, file_size_bytes,
              duration_seconds, width, height, fps, video_codec, audio_codec,
              sample_rate, channels, has_audio, has_video
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                project_id,
                original_filename,
                stored_path,
                file_size,
                info.duration_seconds,
                info.width,
                info.height,
                info.fps,
                info.video_codec,
                info.audio_codec,
                info.sample_rate,
                info.channels,
                1 if info.has_audio else 0,
                1 if info.has_video else 0,
            ),
        )
        _connection().commit()


def save_source(
    project_id: str,
    *,
    original_filename: str,
    stored_path: str,
    info: MediaInfo,
    file_size: int,
) -> None:
    with lock:
        existing = _connection().execute(
            "SELECT id FROM source_videos WHERE project_id=?",
            (project_id,),
        ).fetchone()
    if existing is None:
        insert_source(
            project_id,
            original_filename=original_filename,
            stored_path=stored_path,
            info=info,
            file_size=file_size,
        )
        return
    with lock:
        _connection().execute(
            """
            UPDATE source_videos
            SET original_filename=?, stored_path=?, file_size_bytes=?,
                duration_seconds=?, width=?, height=?, fps=?, video_codec=?,
                audio_codec=?, sample_rate=?, channels=?, has_audio=?, has_video=?
            WHERE project_id=?
            """,
            (
                original_filename,
                stored_path,
                file_size,
                info.duration_seconds,
                info.width,
                info.height,
                info.fps,
                info.video_codec,
                info.audio_codec,
                info.sample_rate,
                info.channels,
                1 if info.has_audio else 0,
                1 if info.has_video else 0,
                project_id,
            ),
        )
        _connection().commit()


def update_source_metadata(project_id: str, info: MediaInfo) -> None:
    with lock:
        _connection().execute(
            """
            UPDATE source_videos
            SET duration_seconds=?, width=?, height=?, fps=?, video_codec=?,
                audio_codec=?, sample_rate=?, channels=?, has_audio=?, has_video=?
            WHERE project_id=?
            """,
            (
                info.duration_seconds,
                info.width,
                info.height,
                info.fps,
                info.video_codec,
                info.audio_codec,
                info.sample_rate,
                info.channels,
                1 if info.has_audio else 0,
                1 if info.has_video else 0,
                project_id,
            ),
        )
        _connection().commit()


def upsert_transcript(
    project_id: str,
    *,
    language: str | None,
    model: str,
    duration_seconds: float | None,
    segment_count: int,
    sentence_count: int,
    json_path: str,
    text_preview: str,
) -> None:
    with lock:
        _connection().execute(
            """
            INSERT INTO transcripts (
              id, project_id, language, model, duration_seconds, segment_count,
              sentence_count, json_path, text_preview, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              language=excluded.language,
              model=excluded.model,
              duration_seconds=excluded.duration_seconds,
              segment_count=excluded.segment_count,
              sentence_count=excluded.sentence_count,
              json_path=excluded.json_path,
              text_preview=excluded.text_preview,
              created_at=excluded.created_at
            """,
            (
                str(uuid.uuid4()),
                project_id,
                language,
                model,
                duration_seconds,
                segment_count,
                sentence_count,
                json_path,
                text_preview[:240],
                utcnow(),
            ),
        )
        _connection().commit()


def create_job(project_id: str, *, kind: str = "transcribe", target_id: str | None = None) -> str:
    job_id = str(uuid.uuid4())
    with lock:
        _connection().execute(
            """
            INSERT INTO jobs (
              id, project_id, kind, target_id, status, stage, progress, message, error,
              created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, 'queued', 'queued', 0, 'Waiting for the processor.', NULL, ?, NULL, NULL)
            """,
            (job_id, project_id, kind, target_id, utcnow()),
        )
        _connection().commit()
    return job_id


def update_job(job_id: str, **fields: object) -> None:
    allowed = {"status", "stage", "progress", "message", "error", "started_at", "finished_at"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown job fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{key}=?" for key in fields)
    with lock:
        _connection().execute(
            f"UPDATE jobs SET {assignments} WHERE id=?",
            (*fields.values(), job_id),
        )
        _connection().commit()


def set_progress(
    project_id: str,
    job_id: str,
    *,
    project_status: str,
    job_status: str,
    stage: str,
    progress: float,
    message: str,
) -> None:
    now = utcnow()
    progress = max(0.0, min(100.0, float(progress)))
    text = message[:300]
    with lock:
        conn = _connection()
        conn.execute(
            """
            UPDATE projects
            SET status=?, progress=?, progress_message=?, error=NULL, updated_at=?
            WHERE id=?
            """,
            (project_status, progress, text, now, project_id),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status=?, stage=?, progress=?, message=?, error=NULL,
                started_at=COALESCE(started_at, ?)
            WHERE id=?
            """,
            (job_status, stage, progress, text, now, job_id),
        )
        conn.commit()


def complete_job(project_id: str, job_id: str, message: str) -> None:
    now = utcnow()
    text = message[:300]
    with lock:
        conn = _connection()
        conn.execute(
            """
            UPDATE projects
            SET status='ready', error=NULL, progress=100, progress_message=?, updated_at=?
            WHERE id=?
            """,
            (text, now, project_id),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status='completed', progress=100, message=?, error=NULL, finished_at=?
            WHERE id=?
            """,
            (text, now, job_id),
        )
        conn.commit()


def fail_job(project_id: str, job_id: str, error: str) -> None:
    now = utcnow()
    text = error[:1000]
    with lock:
        conn = _connection()
        conn.execute(
            """
            UPDATE projects
            SET status='failed', error=?, progress_message=?, updated_at=?
            WHERE id=?
            """,
            (text, text[:300], now, project_id),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status='failed', error=?, message=?, finished_at=?
            WHERE id=?
            """,
            (text, text[:300], now, job_id),
        )
        conn.commit()


def cancel_job(project_id: str, job_id: str, message: str) -> None:
    now = utcnow()
    text = message[:300]
    with lock:
        conn = _connection()
        conn.execute(
            """
            UPDATE projects
            SET status='cancelled', error=NULL, progress_message=?, updated_at=?
            WHERE id=?
            """,
            (text, now, project_id),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status='cancelled', message=?, error=NULL, finished_at=?
            WHERE id=?
            """,
            (text, now, job_id),
        )
        conn.commit()


def replace_clips(project_id: str, clips: list[dict]) -> None:
    now = utcnow()
    with lock:
        conn = _connection()
        conn.execute("DELETE FROM candidate_clips WHERE project_id=?", (project_id,))
        for clip in clips:
            conn.execute(
                """
                INSERT INTO candidate_clips (
                  id, project_id, ordinal, start_seconds, end_seconds, duration_seconds,
                  transcript, opening_hook, category, score, score_breakdown, reason,
                  suggested_title, segments, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    int(clip["ordinal"]),
                    float(clip["start"]),
                    float(clip["end"]),
                    float(clip["duration"]),
                    clip["transcript"],
                    clip["opening_hook"],
                    clip["category"],
                    int(clip["score"]),
                    json.dumps(clip["score_breakdown"], ensure_ascii=False),
                    clip["reason"],
                    clip["suggested_title"],
                    json.dumps(clip.get("segments") or [], ensure_ascii=False),
                    now,
                ),
            )
        conn.commit()


def list_clips(project_id: str) -> list[dict]:
    with lock:
        rows = _connection().execute(
            """
            SELECT c.id, c.project_id, c.ordinal, c.start_seconds, c.end_seconds,
                   c.duration_seconds, c.transcript, c.opening_hook, c.category, c.score,
                   c.score_breakdown, c.reason, c.suggested_title, c.segments,
                   r.status AS render_status, r.crop_mode, r.manual_offset, r.use_manual,
                   r.crop_path, r.preview_path, r.export_path, r.subtitle_path,
                   r.error AS render_error
            FROM candidate_clips c
            LEFT JOIN clip_renders r ON r.clip_id = c.id
            WHERE c.project_id=?
            ORDER BY c.ordinal
            """,
            (project_id,),
        ).fetchall()
    clips = []
    for row in rows:
        item = dict(row)
        try:
            item["score_breakdown"] = json.loads(item["score_breakdown"])
        except json.JSONDecodeError:
            item["score_breakdown"] = {}
        clips.append(item)
    return clips


def get_clip(project_id: str, clip_id: str) -> dict | None:
    for clip in list_clips(project_id):
        if clip["id"] == clip_id:
            return clip
    return None


def save_render(clip_id: str, project_id: str, **fields: object) -> None:
    allowed = {
        "status",
        "crop_mode",
        "manual_offset",
        "use_manual",
        "crop_path",
        "preview_path",
        "export_path",
        "subtitle_path",
        "error",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown render fields: {sorted(unknown)}")
    now = utcnow()
    with lock:
        conn = _connection()
        conn.execute(
            """
            INSERT INTO clip_renders (clip_id, project_id, status, updated_at)
            VALUES (?, ?, 'none', ?)
            ON CONFLICT(clip_id) DO NOTHING
            """,
            (clip_id, project_id, now),
        )
        if fields:
            assignments = ", ".join(f"{key}=?" for key in fields)
            conn.execute(
                f"UPDATE clip_renders SET {assignments}, updated_at=? WHERE clip_id=?",
                (*fields.values(), now, clip_id),
            )
        conn.commit()


def set_measured_av(clip_id: str, quality: int) -> None:
    quality = max(0, min(5, int(quality)))
    with lock:
        conn = _connection()
        row = conn.execute(
            "SELECT score_breakdown FROM candidate_clips WHERE id=?",
            (clip_id,),
        ).fetchone()
        if row is None:
            return
        try:
            breakdown = json.loads(row["score_breakdown"])
        except json.JSONDecodeError:
            breakdown = {}
        if not isinstance(breakdown, dict):
            breakdown = {}
        breakdown["av_quality"] = quality
        score = sum(int(value) for value in breakdown.values() if isinstance(value, (int, float)))
        conn.execute(
            "UPDATE candidate_clips SET score_breakdown=?, score=? WHERE id=?",
            (json.dumps(breakdown, ensure_ascii=False), score, clip_id),
        )
        conn.commit()


def set_clip_framing(project_id: str, clip_id: str, *, offset: float, use_manual: bool) -> dict:
    clip = get_clip(project_id, clip_id)
    if clip is None:
        from app.errors import NotFoundError

        raise NotFoundError("Clip not found.")
    previous = {
        "preview_path": clip.get("preview_path"),
        "export_path": clip.get("export_path"),
        "subtitle_path": clip.get("subtitle_path"),
        "crop_path": clip.get("crop_path"),
    }
    save_render(
        clip_id,
        project_id,
        status="none",
        manual_offset=0 if not use_manual else max(-1.0, min(1.0, float(offset))),
        use_manual=1 if use_manual else 0,
        preview_path=None,
        export_path=None,
        subtitle_path=None,
        crop_path=None,
        error=None,
    )
    return previous


def approve_clip(project_id: str, clip_id: str) -> None:
    clip = get_clip(project_id, clip_id)
    if clip is None:
        from app.errors import NotFoundError

        raise NotFoundError("Clip not found.")
    from app.errors import ClipperError

    if clip.get("render_status") != "preview_ready" or not clip.get("preview_path"):
        raise ClipperError("Build a low-resolution preview before approving this short.")
    save_render(clip_id, project_id, status="approved", error=None)


def save_metadata(clip_id: str, project_id: str, payload: dict) -> None:
    now = utcnow()
    with lock:
        _connection().execute(
            """
            INSERT INTO clip_metadata (
              clip_id, project_id, titles, selected_title, description, hashtags,
              headline, cta, category, keywords, thumbnail_path, frame_path,
              metadata_path, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET
              titles=excluded.titles,
              selected_title=excluded.selected_title,
              description=excluded.description,
              hashtags=excluded.hashtags,
              headline=excluded.headline,
              cta=excluded.cta,
              category=excluded.category,
              keywords=excluded.keywords,
              thumbnail_path=excluded.thumbnail_path,
              frame_path=excluded.frame_path,
              metadata_path=excluded.metadata_path,
              updated_at=excluded.updated_at
            """,
            (
                clip_id,
                project_id,
                json.dumps(payload["titles"], ensure_ascii=False),
                payload["selected_title"],
                payload["description"],
                json.dumps(payload["hashtags"], ensure_ascii=False),
                payload["headline"],
                payload["cta"],
                payload["category"],
                json.dumps(payload["keywords"], ensure_ascii=False),
                payload.get("thumbnail_path"),
                payload.get("frame_path"),
                payload.get("metadata_path"),
                now,
            ),
        )
        _connection().commit()


def list_metadata(project_id: str) -> list[dict]:
    with lock:
        rows = _connection().execute(
            """
            SELECT clip_id, project_id, titles, selected_title, description, hashtags,
                   headline, cta, category, keywords, thumbnail_path, frame_path,
                   metadata_path
            FROM clip_metadata
            WHERE project_id=?
            """,
            (project_id,),
        ).fetchall()
    return [_metadata_row(row) for row in rows]


def get_metadata(project_id: str, clip_id: str) -> dict | None:
    for item in list_metadata(project_id):
        if item["clip_id"] == clip_id:
            return item
    return None


def _metadata_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    for key in ("titles", "hashtags", "keywords"):
        try:
            item[key] = json.loads(item[key])
        except json.JSONDecodeError:
            item[key] = []
    return item


def fail_highlight(project_id: str, job_id: str, error: str) -> None:
    _close_highlight(project_id, job_id, error=error, message=error, job_status="failed")


def cancel_highlight(project_id: str, job_id: str, message: str) -> None:
    _close_highlight(project_id, job_id, error=None, message=message, job_status="cancelled")


def fail_render(project_id: str, job_id: str, error: str) -> None:
    _close_highlight(project_id, job_id, error=error, message=error, job_status="failed")


def cancel_render(project_id: str, job_id: str, message: str) -> None:
    _close_highlight(project_id, job_id, error=None, message=message, job_status="cancelled")


def _close_highlight(
    project_id: str,
    job_id: str,
    *,
    error: str | None,
    message: str,
    job_status: str,
) -> None:
    now = utcnow()
    text = (message or "")[:300]
    stored_error = None if error is None else error[:1000]
    with lock:
        has_transcript = _connection().execute(
            "SELECT id FROM transcripts WHERE project_id=?",
            (project_id,),
        ).fetchone()
        project_status = "ready" if has_transcript is not None else "failed"
        conn = _connection()
        conn.execute(
            """
            UPDATE projects
            SET status=?, error=?, progress_message=?, updated_at=?
            WHERE id=?
            """,
            (project_status, stored_error, text, now, project_id),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status=?, error=?, message=?, finished_at=?
            WHERE id=?
            """,
            (job_status, stored_error, text, now, job_id),
        )
        conn.commit()


def get_setting(key: str) -> str | None:
    with lock:
        row = _connection().execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])


def set_setting(key: str, value: str) -> None:
    with lock:
        _connection().execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        _connection().commit()


def get_project(project_id: str) -> dict | None:
    with lock:
        row = _connection().execute(_PROJECT_SQL + " WHERE p.id=?", (project_id,)).fetchone()
    return dict(row) if row is not None else None


def list_projects(limit: int) -> list[dict]:
    with lock:
        rows = _connection().execute(
            _PROJECT_SQL + " ORDER BY p.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_transcript(project_id: str) -> dict | None:
    with lock:
        row = _connection().execute(
            "SELECT * FROM transcripts WHERE project_id=?",
            (project_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def get_job(job_id: str) -> dict | None:
    with lock:
        row = _connection().execute(_JOB_SQL + " WHERE j.id=?", (job_id,)).fetchone()
    return dict(row) if row is not None else None


def list_jobs(limit: int) -> list[dict]:
    with lock:
        rows = _connection().execute(
            _JOB_SQL + " ORDER BY j.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
