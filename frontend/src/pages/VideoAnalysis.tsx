import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { cancelProject, getProject, getTranscript, processProject, startHighlights } from "../api";
import { StatusPill } from "../components/StatusPill";
import { formatBytes, formatClock, formatTimestamp, isActiveStatus } from "../format";
import type { Project, Transcript } from "../types";

export function VideoAnalysis() {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    setTranscript(null);

    const tick = async () => {
      try {
        const next = await getProject(projectId);
        if (cancelled) return;
        setProject(next);
        setError(null);
        if (next.has_transcript) {
          const body = await getTranscript(projectId);
          if (!cancelled) setTranscript(body);
        }
        if (!isActiveStatus(next.status)) return;
        timer = window.setTimeout(() => void tick(), 1000);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load the project.");
      }
    };

    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [projectId, watch]);

  async function run(action: "start" | "cancel" | "highlights") {
    setBusy(true);
    setActionError(null);
    try {
      if (action === "start") await processProject(projectId);
      else if (action === "highlights") await startHighlights(projectId);
      else await cancelProject(projectId);
      setWatch((value) => value + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The request failed.");
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div>
        <p className="text-sm text-rose-300">{error}</p>
        <Link to="/analysis" className="mt-4 inline-block text-sm text-amber-200 underline">
          Back to analysis
        </Link>
      </div>
    );
  }
  if (!project) return <p className="text-sm text-zinc-400">Loading project…</p>;

  const active = isActiveStatus(project.status);
  const waitingForDownload = Boolean(project.source_url) && !project.stored_path;
  const canStart =
    ["uploaded", "failed", "cancelled", "ready"].includes(project.status) &&
    (project.has_audio || waitingForDownload);
  const startLabel = waitingForDownload
    ? project.status === "uploaded"
      ? "Start download"
      : "Download again"
    : project.status === "uploaded"
      ? "Start transcription"
      : "Transcribe again";
  const wordCount = transcript?.sentences.reduce((total, sentence) => total + sentence.words.length, 0) ?? 0;

  return (
    <div>
      <Link to="/analysis" className="text-xs text-zinc-500 hover:text-zinc-300">
        Video analysis
      </Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{project.title}</h1>
          <p className="mt-2 text-sm text-zinc-500">{project.original_filename || project.source_url}</p>
        </div>
        <StatusPill status={project.status} />
      </div>

      {project.error ? (
        <p className="mt-4 rounded-md border border-rose-400/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">
          {project.error}
        </p>
      ) : null}
      {actionError ? <p className="mt-4 text-sm text-rose-300">{actionError}</p> : null}

      <div className="mt-6 grid gap-6 lg:grid-cols-[280px_1fr]">
        <section className="rounded-lg border border-white/10 bg-[#16181d] p-4">
          {project.has_video ? (
            <video
              key={project.id}
              controls
              preload="metadata"
              className="aspect-video w-full rounded-md bg-black"
              src={`/api/projects/${project.id}/media`}
            />
          ) : (
            <p className="text-sm text-zinc-500">No playable video for this project.</p>
          )}
          <dl className="mt-4 space-y-2 text-sm">
            <Fact label="Duration" value={project.duration_seconds != null ? formatClock(project.duration_seconds) : "–"} />
            <Fact
              label="Picture"
              value={project.width && project.height ? `${project.width}×${project.height}` : "–"}
            />
            <Fact label="Video" value={project.video_codec ?? "–"} />
            <Fact label="Audio" value={project.audio_codec ?? "–"} />
            <Fact
              label="Sample rate"
              value={project.audio_sample_rate ? `${project.audio_sample_rate} Hz` : "–"}
            />
            <Fact label="Size" value={project.file_size_bytes != null ? formatBytes(project.file_size_bytes) : "–"} />
          </dl>
        </section>

        <section>
          <div className="rounded-lg border border-white/10 bg-[#16181d] p-4" aria-live="polite">
            <div className="flex items-center justify-between gap-3 text-sm">
              <p>{project.progress_message || "Waiting"}</p>
              <p className="tabular-nums text-zinc-400">{Math.round(project.progress)}%</p>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
              <div className="h-full bg-amber-400" style={{ width: `${Math.max(0, Math.min(100, project.progress))}%` }} />
            </div>
            <div className="mt-4 flex gap-2">
              {canStart ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run("start")}
                  className="rounded-md bg-amber-400 px-3 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-40"
                >
                  {startLabel}
                </button>
              ) : null}
              {project.has_transcript && !active ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run("highlights")}
                  className="rounded-md border border-white/15 px-3 py-2 text-sm disabled:opacity-40"
                >
                  Find highlights
                </button>
              ) : null}
              {project.clip_count > 0 ? (
                <Link
                  to={`/highlights?project=${project.id}`}
                  className="rounded-md border border-white/15 px-3 py-2 text-sm"
                >
                  {project.clip_count} clip{project.clip_count === 1 ? "" : "s"}
                </Link>
              ) : null}
              {project.clip_count > 0 ? (
                <Link
                  to={`/preview?project=${project.id}`}
                  className="rounded-md border border-white/15 px-3 py-2 text-sm"
                >
                  Preview
                </Link>
              ) : null}
              {active ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run("cancel")}
                  className="rounded-md border border-white/15 px-3 py-2 text-sm disabled:opacity-40"
                >
                  Cancel
                </button>
              ) : null}
            </div>
          </div>

          {transcript ? (
            <div className="mt-6">
              <h2 className="text-lg font-medium">Transcript</h2>
              <p className="mt-1 text-xs text-zinc-500">
                {transcript.language ?? "unknown language"} · {transcript.model} · {transcript.sentences.length} sentences
                {wordCount ? ` · ${wordCount} words` : ""}
              </p>
              {transcript.warnings.length ? (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-amber-100">
                  {transcript.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              ) : null}
              {transcript.sentences.length === 0 ? (
                <p className="mt-4 text-sm text-zinc-400">No speech was detected in this video.</p>
              ) : (
                <ol className="mt-4 space-y-4">
                  {transcript.sentences.map((sentence) => (
                    <li key={sentence.id} className="rounded-lg border border-white/10 px-4 py-3">
                      <p className="font-mono text-xs text-amber-200">
                        {formatTimestamp(sentence.start)} – {formatTimestamp(sentence.end)}
                      </p>
                      <p className="mt-2 text-sm leading-6">{sentence.text}</p>
                      {sentence.words.length ? (
                        <details className="mt-2">
                          <summary className="cursor-pointer text-xs text-zinc-500">Words</summary>
                          <p className="mt-2 text-xs leading-5 text-zinc-400">
                            {sentence.words.map((word, index) => (
                              <span key={`${sentence.id}-${index}`} title={`${word.start.toFixed(2)}–${word.end.toFixed(2)}`}>
                                {word.word}
                              </span>
                            ))}
                          </p>
                        </details>
                      ) : null}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-zinc-500">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  );
}
