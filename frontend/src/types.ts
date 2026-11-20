export interface Project {
  id: string;
  title: string;
  status: string;
  error: string | null;
  progress: number;
  progress_message: string;
  created_at: string;
  updated_at: string;
  source_url: string | null;
  original_filename: string | null;
  stored_path: string | null;
  file_size_bytes: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  audio_sample_rate: number | null;
  audio_channels: number | null;
  has_audio: boolean;
  has_video: boolean;
  has_transcript: boolean;
  clip_count: number;
  current_job_id: string | null;
}

export interface ScoreBreakdown {
  opening_hook: number;
  interesting_content: number;
  emotional_impact: number;
  context: number;
  complete_thought: number;
  shareability: number;
  av_quality: number;
}

export interface ClipRender {
  status: string;
  crop_mode: string | null;
  manual_offset: number;
  use_manual: boolean;
  has_preview: boolean;
  has_export: boolean;
  error: string | null;
}

export interface Clip {
  id: string;
  project_id: string;
  ordinal: number;
  start: number;
  end: number;
  duration: number;
  transcript: string;
  opening_hook: string;
  category: string;
  score: number;
  score_breakdown: ScoreBreakdown;
  reason: string;
  suggested_title: string;
  segments?: { start: number; end: number }[];
  render: ClipRender;
}

export interface ClipMetadata {
  clip_id: string;
  project_id: string;
  titles: string[];
  selected_title: string;
  description: string;
  hashtags: string[];
  headline: string;
  cta: string;
  category: string;
  keywords: string[];
  has_thumbnail: boolean;
}

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
  probability: number | null;
}

export interface TranscriptSentence {
  id: number;
  start: number;
  end: number;
  text: string;
  words: TranscriptWord[];
}

export interface Transcript {
  language: string | null;
  language_probability: number | null;
  model: string;
  duration: number | null;
  text: string;
  sentences: TranscriptSentence[];
  warnings: string[];
}

export interface Job {
  id: string;
  project_id: string;
  project_title: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Health {
  status: string;
  phase: number;
  ffmpeg: { available: boolean; path: string; version: string | null };
  ffprobe: { available: boolean; path: string; version: string | null };
  whisper: {
    model: string;
    device: string;
    compute_type: string;
    threads: number;
    configured_threads: number;
    vad_filter: boolean;
    profile_ok: boolean;
    profile_message: string | null;
  };
  ollama: { host: string; model: string; models: string[]; used_in_phase: number; note: string };
  jobs: {
    max_concurrent: number;
    max_queued: number;
    running_project_id: string | null;
    queued: number;
  };
  data_dir: string;
  output_dir: string;
  max_upload_bytes: number;
}
