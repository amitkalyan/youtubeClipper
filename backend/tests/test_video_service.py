import pytest

from app.errors import AudioTrackMissingError, InvalidMediaError
from app.services.video_service import extract_audio, probe
from tests.media_factory import make_silent_video, make_tone_video


def test_probe_reads_metadata_without_loading_frames(tmp_path):
    video = tmp_path / "tone.mp4"
    make_tone_video(video, seconds=1)
    info = probe(video)
    assert info.has_video is True
    assert info.has_audio is True
    assert info.width == 320
    assert info.height == 180
    assert info.video_codec == "h264"
    assert info.file_size_bytes == video.stat().st_size
    assert 0.5 < info.duration_seconds < 2.5
    assert info.fps is not None and 5 < info.fps < 20


def test_extract_audio_is_16k_mono_pcm(tmp_path):
    video = tmp_path / "tone.mp4"
    wav = tmp_path / "audio.wav"
    make_tone_video(video, seconds=1)
    extract_audio(video, wav, should_cancel=lambda: False)
    info = probe(wav)
    assert info.has_audio is True
    assert info.has_video is False
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert wav.stat().st_size > 1000


def test_silent_video_has_no_audio_track(tmp_path):
    video = tmp_path / "silent.mp4"
    make_silent_video(video)
    info = probe(video)
    assert info.has_video is True
    assert info.has_audio is False
    try:
        extract_audio(video, tmp_path / "audio.wav", should_cancel=lambda: False)
    except AudioTrackMissingError as exc:
        assert "no audio" in str(exc).lower()
    else:
        raise AssertionError("Expected a missing-audio error")


def test_text_file_is_rejected(tmp_path):
    fake = tmp_path / "notes.mp4"
    fake.write_text("this is not a video", encoding="utf-8")
    with pytest.raises(InvalidMediaError):
        probe(fake)
