"""Create a short spoken sample for the Phase 1 UI check."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.services.video_service import hidden_window_flag
from tests.media_factory import mux_speech_video

ROOT = Path(r"C:\Users\amkalyan\AppData\Local\Temp\clipper-sample")
TEXT = "Hello. This is the local clipper transcription test."


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    wav = ROOT / "speech.wav"
    video = ROOT / "speech.mp4"
    safe = str(wav).replace("'", "''")
    script = "\n".join(
        [
            "Add-Type -AssemblyName System.Speech",
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            f"$synth.SetOutputToWaveFile('{safe}')",
            "$synth.Speak(@'",
            TEXT,
            "'@)",
            "$synth.Dispose()",
        ]
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=hidden_window_flag(),
    )
    if proc.returncode != 0 or not wav.is_file():
        raise SystemExit(proc.stderr or "speech synthesis failed")
    mux_speech_video(wav, video)
    print(video)


if __name__ == "__main__":
    main()
