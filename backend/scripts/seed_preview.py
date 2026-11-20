"""Insert one tiny ready project so the preview page can be tried without Whisper."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app import db
from app.services.storage_service import project_dir, transcript_path, write_json
from app.services.video_service import probe
from tests.media_factory import make_tone_video


def main() -> None:
    db.init_db()
    project_id = db.create_project("Phase 3 sample", status="ready", message="Ready for a low-resolution preview.")
    db.update_project(project_id, progress=100, progress_message="Ready for a low-resolution preview.")
    folder = project_dir(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "source.mp4"
    with tempfile.TemporaryDirectory() as temporary:
        made = Path(temporary) / "tone.mp4"
        make_tone_video(made, seconds=1)
        source.write_bytes(made.read_bytes())
    info = probe(source)
    db.save_source(
        project_id,
        original_filename="phase3-sample.mp4",
        stored_path=str(source.resolve()),
        info=info,
        file_size=source.stat().st_size,
    )
    document = {
        "language": "en",
        "language_probability": 0.99,
        "model": "base",
        "duration": 1.0,
        "text": "Hello world.",
        "segments": [],
        "sentences": [
            {
                "id": 0,
                "start": 0.0,
                "end": 1.0,
                "text": "Hello world.",
                "words": [
                    {"word": " Hello", "start": 0.0, "end": 0.4, "probability": 0.9},
                    {"word": " world.", "start": 0.4, "end": 1.0, "probability": 0.9},
                ],
            }
        ],
        "warnings": [],
    }
    path = transcript_path(project_id)
    write_json(path, document)
    db.upsert_transcript(
        project_id,
        language="en",
        model="base",
        duration_seconds=1.0,
        segment_count=1,
        sentence_count=1,
        json_path=str(path),
        text_preview="Hello world.",
    )
    db.replace_clips(
        project_id,
        [
            {
                "ordinal": 0,
                "start": 0.0,
                "end": 1.0,
                "duration": 1.0,
                "transcript": "Hello world.",
                "opening_hook": "Hello",
                "category": "memorable statement",
                "score": 3,
                "score_breakdown": {
                    "opening_hook": 0,
                    "interesting_content": 0,
                    "emotional_impact": 0,
                    "context": 0,
                    "complete_thought": 0,
                    "shareability": 0,
                    "av_quality": 3,
                },
                "reason": "A one-second sample for the vertical preview.",
                "suggested_title": "Hello",
            }
        ],
    )
    print(project_id)


if __name__ == "__main__":
    main()
