import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listHighlights, listProjects, startHighlights } from "../api";
import { StatusPill } from "../components/StatusPill";
import { formatClock, formatTimestamp, isActiveStatus } from "../format";
import type { Clip, Project } from "../types";
import { useHealth } from "../useHealth";

const BREAKDOWN: { key: keyof Clip["score_breakdown"]; label: string; max: number }[] = [
  { key: "opening_hook", label: "Opening hook", max: 25 },
  { key: "interesting_content", label: "Interesting content", max: 20 },
  { key: "emotional_impact", label: "Emotion and curiosity", max: 15 },
  { key: "context", label: "Context", max: 15 },
  { key: "complete_thought", label: "Complete thought", max: 10 },
  { key: "shareability", label: "Shareability", max: 10 },
  { key: "av_quality", label: "Audio and picture", max: 5 },
];

export function Highlights() {
  const { health } = useHealth();
  const [params, setParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const selected = params.get("project") ?? "";

  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((rows) => {
        if (!cancelled) setProjects(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load projects.");
      });
    return () => {
      cancelled = true;
    };
  }, [project?.updated_at]);

  useEffect(() => {
    if (!selected) {
      setProject(null);
      setClips(null);
      return;
    }
    let cancelled = false;
    let timer = 0;

    const tick = async () => {
      try {
        const rows = await listProjects();
        const next = rows.find((item) => item.id === selected) ?? null;
        if (cancelled) return;
        setProject(next);
        if (!next) {
          setError("That project is not on this computer.");
          return;
        }
        setError(null);
        if (next.has_transcript && !isActiveStatus(next.status)) {
          setClips(await listHighlights(selected));
        }
        if (!isActiveStatus(next.status)) return;
        timer = window.setTimeout(() => void tick(), 1000);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load highlights.");
      }
    };

    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selected, project?.status]);

  async function run() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const next = await startHighlights(selected);
      setProject(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start highlight detection.");
    } finally {
      setBusy(false);
    }
  }

  const ready = (projects ?? []).filter((item) => item.has_transcript);
  const active = project ? isActiveStatus(project.status) : false;

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Highlight detection</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
        When Ollama is running, it proposes moments from 20 seconds to 1 minute of speech. Each quote is copied
        from the sentences that were actually spoken. If Ollama is off, the same transcript is still cut into shorts
        by joining speech. A pause longer than 2 seconds is left out. Picture quality stays at 3 until a preview
        measures a real frame, and can then rise to 5.
      </p>
      {health ? <p className="mt-3 text-sm text-zinc-300">Ollama: {health.ollama.note}</p> : null}
      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}

      <div className="mt-6 flex flex-wrap items-end gap-3">
        <label className="text-sm" htmlFor="project">
          Transcript
          <select
            id="project"
            value={selected}
            onChange={(event) => setParams(event.target.value ? { project: event.target.value } : {})}
            className="mt-2 block min-w-64 rounded-md border border-white/10 bg-[#16181d] px-3 py-2 text-sm"
          >
            <option value="">Choose a transcript</option>
            {ready.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
                {item.clip_count ? ` · ${item.clip_count} clips` : ""}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!selected || busy || active}
          onClick={() => void run()}
          className="rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {active ? "Scoring…" : "Find highlights"}
        </button>
        {project ? (
          <Link to={`/projects/${project.id}`} className="text-sm text-amber-200 underline">
            Open analysis
          </Link>
        ) : null}
        {project && project.clip_count > 0 ? (
          <Link to={`/preview?project=${project.id}`} className="text-sm text-amber-200 underline">
            Preview framing
          </Link>
        ) : null}
      </div>

      {projects && ready.length === 0 ? (
        <p className="mt-8 text-sm text-zinc-400">Transcribe a video first. Highlight detection uses that transcript.</p>
      ) : null}

      {project ? (
        <div className="mt-6 flex items-center gap-3">
          <StatusPill status={project.status} />
          <p className="text-sm text-zinc-400">{project.progress_message}</p>
        </div>
      ) : null}
      {project?.error ? (
        <p className="mt-4 rounded-md border border-rose-400/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">
          {project.error}
        </p>
      ) : null}

      {clips && clips.length === 0 && project && !active ? (
        <p className="mt-8 text-sm text-zinc-400">
          No candidates yet. This transcript needs at least 20 seconds of speech so the short passages can be joined.
        </p>
      ) : null}

      <ol className="mt-6 space-y-4">
        {(clips ?? []).map((clip) => (
          <li key={clip.id} className="rounded-lg border border-white/10 bg-[#16181d] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-amber-200/80">{clip.category}</p>
                <h2 className="mt-1 text-lg font-medium">{clip.suggested_title}</h2>
              </div>
              <p className="text-2xl font-semibold tabular-nums">{clip.score}</p>
            </div>
            <p className="mt-2 font-mono text-xs text-zinc-400">
              {clip.segments && clip.segments.length > 1
                ? `${formatClock(clip.duration)} of speech · ${clip.segments.length} parts`
                : `${formatTimestamp(clip.start)} – ${formatTimestamp(clip.end)} · ${formatClock(clip.duration)}`}
            </p>
            <p className="mt-3 text-sm text-amber-100">{clip.opening_hook}</p>
            <p className="mt-3 text-sm leading-6">{clip.transcript}</p>
            <p className="mt-3 text-sm text-zinc-400">{clip.reason}</p>
            <dl className="mt-4 grid gap-2 sm:grid-cols-2">
              {BREAKDOWN.map((item) => (
                <div key={item.key} className="flex justify-between gap-3 text-xs text-zinc-400">
                  <dt>{item.label}</dt>
                  <dd className="tabular-nums">
                    {clip.score_breakdown[item.key]} / {item.max}
                  </dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ol>
    </div>
  );
}
