"""Vertical preview, manual crop, and the approved 1080x1920 export."""

from __future__ import annotations

import pytest

from app.services.caption_service import build_ass, caption_alignment, clip_cues, cues_for_segments
from app.services.rendering_service import crop_window
from app.services.video_service import probe
from tests.media_factory import make_tone_video
from tests.test_api_workflow import sample_document, upload, wait_project


def test_landscape_face_crop_and_manual_override():
    face = crop_window(1920, 1080, face_x=200, face_y=400, face=True, use_manual=False, manual_offset=0)
    assert face["mode"] == "face"
    assert face["h"] == 1080
    assert face["w"] == 608
    assert face["x"] == 0

    manual = crop_window(1920, 1080, face_x=200, face_y=400, face=True, use_manual=True, manual_offset=0)
    assert manual["mode"] == "manual"
    assert manual["x"] == 656

    right = crop_window(1920, 1080, face_x=960, face_y=200, face=True, use_manual=True, manual_offset=1)
    assert right["x"] == 1312


def test_portrait_source_is_padded():
    window = crop_window(1080, 1920, face_x=100, face_y=900, face=True, use_manual=True, manual_offset=-1)
    assert window["mode"] == "pad"
    assert window["w"] == 1080
    assert window["h"] == 1920


def test_captions_emphasize_hook_words_and_move_for_a_low_face():
    cues = clip_cues(sample_document()["sentences"], 0, 1, "Hello")
    ass = build_ass(cues, play_x=360, play_y=640, alignment=2)
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue")]
    hello = next(line for line in lines if "Hello" in line)
    world = next(line for line in lines if "world" in line)
    assert r"\b1" in hello
    assert r"\b1" not in world
    assert caption_alignment(900, 1080) == 8
    assert caption_alignment(200, 1080) == 2
    assert caption_alignment(None, 1080) == 2
    joined = cues_for_segments(
        [
            {"id": 0, "start": 0.0, "end": 1.0, "text": "Hello.", "words": [{"word": "Hello", "start": 0.1, "end": 0.4}]},
            {"id": 1, "start": 10.0, "end": 11.0, "text": "Again.", "words": [{"word": "Again", "start": 10.2, "end": 10.6}]},
        ],
        [{"start": 0.0, "end": 1.0}, {"start": 10.0, "end": 11.0}],
        "",
    )
    assert joined[0]["text"] == "Hello"
    assert joined[1]["start"] == pytest.approx(1.2, abs=0.05)


def test_preview_requires_approval_before_the_full_export(client, tmp_path, monkeypatch):
    http, data = client
    tone_video = tmp_path / "tone.mp4"
    make_tone_video(tone_video, seconds=1)

    def fake_transcribe(audio_path, *, media_duration, on_progress, should_cancel, model_loader=None):
        on_progress(1.0, "Transcribed through 1.0s")
        return sample_document()

    monkeypatch.setattr("app.services.transcription_service.transcribe_file", fake_transcribe)
    created = upload(http, tone_video, title="Preview sample")
    ready = wait_project(http, created["id"])
    assert ready["status"] == "ready"

    from app import db

    db.replace_clips(
        created["id"],
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
                "reason": "A short sample.",
                "suggested_title": "Hello",
            }
        ],
    )

    started = http.post(f"/api/projects/{created['id']}/previews", json={})
    assert started.status_code == 202, started.text
    preview_done = wait_project(http, created["id"], timeout=90)
    assert preview_done["error"] in (None, ""), preview_done
    clips = http.get(f"/api/projects/{created['id']}/highlights").json()
    clip = clips[0]
    assert clip["render"]["status"] == "preview_ready"
    assert clip["render"]["has_preview"] is True
    assert clip["score_breakdown"]["av_quality"] == 4
    preview_file = data / "projects" / created["id"] / "work" / "previews" / "clip_001.mp4"
    assert preview_file.is_file()
    info = probe(preview_file)
    assert info.width == 360
    assert info.height == 640
    assert info.video_codec == "h264"
    assert info.has_audio is True
    ass = (data / "projects" / created["id"] / "work" / "previews" / "clip_001.ass").read_text(encoding="utf-8")
    assert "Hello" in ass

    early = http.post(f"/api/projects/{created['id']}/exports", json={"clip_id": clip["id"]})
    assert early.status_code == 400

    framed = http.post(
        f"/api/projects/{created['id']}/clips/{clip['id']}/crop",
        json={"offset": 0.4, "use_detector": False},
    )
    assert framed.status_code == 200, framed.text
    assert framed.json()["render"]["status"] == "none"
    assert framed.json()["render"]["use_manual"] is True

    again = http.post(f"/api/projects/{created['id']}/previews", json={"clip_id": clip["id"]})
    assert again.status_code == 202, again.text
    rebuilt = wait_project(http, created["id"], timeout=90)
    assert rebuilt["error"] in (None, ""), rebuilt

    approved = http.post(f"/api/projects/{created['id']}/clips/{clip['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["render"]["status"] == "approved"

    exported = http.post(f"/api/projects/{created['id']}/exports", json={"clip_id": clip["id"]})
    assert exported.status_code == 202, exported.text
    done = wait_project(http, created["id"], timeout=120)
    assert done["error"] in (None, ""), done
    short = data.parent / "output" / created["id"] / "clip_001" / "short.mp4"
    srt = data.parent / "output" / created["id"] / "clip_001" / "subtitles.srt"
    assert short.is_file()
    final = probe(short)
    assert final.width == 1080
    assert final.height == 1920
    assert final.video_codec == "h264"
    assert final.audio_codec == "aac"
    assert "Hello" in srt.read_text(encoding="utf-8")
    served = http.get(f"/api/projects/{created['id']}/clips/{clip['id']}/export")
    assert served.status_code == 200
    assert served.content[:8] != b""
