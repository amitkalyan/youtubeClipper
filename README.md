# Clipper

Local tool that turns one YouTube video into reviewed Shorts. Paste a link, and Clipper downloads that video, transcribes it, and cuts moments from 20 seconds to 1 minute. You approve a low-resolution preview before the full vertical export. It does not call a cloud AI API. A link downloads that one video only, and only after you confirm you have the right to download and edit it.

This workstation is Windows 11 with 8 GB of RAM and no discrete GPU. The app keeps one heavy job at a time, streams uploads to disk, and unloads Whisper before anything else would load.

## Phase 1

What works now:

1. Paste one YouTube link, or upload a local video (mp4, mov, mkv, webm, avi, m4v). A link downloads that single video at up to 1080p. Playlists are not downloaded.
2. Read duration, resolution, and codecs with ffprobe.
3. Extract 16 kHz mono audio with FFmpeg, without loading the picture into Python.
4. Transcribe with Faster-Whisper `base` on CPU, INT8.
5. Save sentence-level and word-level timestamps.
6. Watch progress, cancel, and read the transcript in the dashboard.

## Phase 2

Highlight detection reads a finished transcript with Ollama. It does not load Whisper at the same time.

1. Open Highlight Detection, or use Find highlights on a finished transcript.
2. The Ollama model selected in Settings returns candidate moments as JSON. Any model already installed locally can be used. `qwen2.5:3b` is only the default preference.
3. Candidates are kept only when they sit on real sentences and last from 20 seconds to 1 minute.
4. The stored quote is the spoken text. Overlaps, duplicates, and invented lines are removed.
5. Audio and picture score stays at 3 until a preview measures a frame. It can then rise to 5.

Ollama has to be running locally:

```powershell
ollama serve
ollama pull qwen2.5:3b
```

`ollama pull` can be any model you want. After it is installed, choose it under Settings. The line above is a small model that fits this 8 GB machine.

If Ollama is stopped, the transcript stays, and the project shows the error. Speech under 20 seconds is joined with other speech already in that transcript, and a pause longer than 2 seconds is left out. A transcript with under 20 seconds of speech in total produces no shorts and does not load the model.

## Phase 3

A highlight can become a vertical short after you look at a low-resolution preview.

1. Open Video Preview and build a 360×640 preview. Framing comes from a 360 px, 1 fps proxy. One picture is read at a time, then deleted.
2. A detected face sets the 9:16 window on a landscape video. A portrait video is scaled and padded. A saved manual crop replaces the detector. Zoom stays off.
3. Captions are the spoken words. A word from the opening hook is emphasized. If the face is low in the frame, the captions move up.
4. Approve the preview, then export 1080×1920 H.264/AAC from Generated Shorts. The full-size encode does not start before that approval.
5. The export is `output/<project>/clip_001/short.mp4` plus `subtitles.srt`.

## Phase 4

Titles and the thumbnail come from the words spoken in that short.

1. Open Metadata editor or Thumbnail studio and draft from the transcript.
2. Ollama returns three titles, a description, 3–5 hashtags when the transcript has enough words, a headline, a call to action, and keywords.
3. The headline has to use words from the transcript. Hype such as “viral” or “guaranteed” is removed.
4. The thumbnail is one frame from the middle of the clip. Pillow draws the headline on it. No image-generation model is used.
5. Edit the text and redraw the headline. The full-size short still waits for your approval.

What is still later: dashboard totals and a full export history.

## Requirements

- Windows 11
- Python 3.11 or newer (this machine has 3.13)
- Node.js 20 or newer
- FFmpeg (the fetch script puts a portable build in `tools/ffmpeg`)
- About 150 MB of free disk for the Whisper base model on first transcription
- Ollama with any locally installed model for highlight detection. Transcription still works without it. A 3B model is the comfortable size for 8 GB of RAM.

Close other heavy applications before a long transcription. The speech model is the largest thing Phase 1 loads.

## Install

From the project folder in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\fetch-ffmpeg.ps1
py -3 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm install
cd ..
```

`requirements.txt` keeps PyAV below 17. Faster-Whisper 1.2 passes `metadata_errors` to `av.open`, and PyAV 17+ removed that argument.

Optional overrides live in `.env.example`. Copy it to `.env` only if you need to change a default.

## Start

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

- App: http://127.0.0.1:5173
- API: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

Or start the two processes yourself:

```powershell
# Terminal 1
cd backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1

# Terminal 2
cd frontend
npm run dev
```

Do not add `--reload` while a transcription is running. A reload kills the worker and the in-memory speech model.

## Stop

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

If you started the terminals yourself, press Ctrl+C in each one.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

The suite covers metadata, 16 kHz extraction, missing audio, sentence grouping, timestamp checks, model unload, the CPU profile guard, upload through a saved transcript, the single-job queue, cancel, and one real Whisper pass on a short spoken sample generated on this PC. The first real pass downloads the base model into `data/models`.

## Files

| Path | Role |
| --- | --- |
| `data/` | SQLite, uploads, audio, transcripts, model cache |
| `output/` | Approved exports, used from Phase 3 |
| `tools/ffmpeg/` | Portable ffmpeg and ffprobe |
| `architecture.md` | Decisions for this machine and the later phases |

## First transcription

The first job downloads Whisper base (about 150 MB) and may also download a small voice-activity model. Progress stays on "Loading the speech model" until that finishes. Later jobs reuse `data/models`.

A one-hour file produces roughly 115 MB of 16 kHz mono WAV next to the source. The Python process does not hold the video in memory.
