import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listHighlights, listProjects, startExport } from "../api";
import { StatusPill } from "../components/StatusPill";
import { formatClock, formatTimestamp, isActiveStatus } from "../format";
import type { Clip, Project } from "../types";

export function Shorts() {
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
        setClips(next.clip_count > 0 ? await listHighlights(selected) : []);
        if (!isActiveStatus(next.status)) return;
        timer = window.setTimeout(() => void tick(), 1000);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load shorts.");
      }
    };
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selected, project?.status]);

  async function exportClip(clip: Clip) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setProject(await startExport(selected, clip.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export this short.");
    } finally {
      setBusy(false);
    }
  }

  const choices = (projects ?? []).filter((item) => item.has_transcript);
  const active = project ? isActiveStatus(project.status) : false;
  const ready = (clips ?? []).filter(
    (clip) => clip.render.status === "approved" || clip.render.status === "exported" || clip.render.has_export,
  );

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Generated shorts</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
        An approved preview is exported as 1080×1920 H.264 with AAC audio and burned-in word captions. The spoken
        words are the caption text. Loudness is left as it was in the source. Thumbnails and titles are still later.
      </p>
      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}

      <div className="mt-6 flex flex-wrap items-end gap-3">
        <label className="text-sm" htmlFor="project">
          Project
          <select
            id="project"
            value={selected}
            onChange={(event) => setParams(event.target.value ? { project: event.target.value } : {})}
            className="mt-2 block min-w-64 rounded-md border border-white/10 bg-[#16181d] px-3 py-2 text-sm"
          >
            <option value="">Choose a project</option>
            {choices.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        {project ? (
          <Link to={`/preview?project=${project.id}`} className="text-sm text-amber-200 underline">
            Review previews
          </Link>
        ) : null}
      </div>

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
      {project && clips && ready.length === 0 && !active ? (
        <p className="mt-8 text-sm text-zinc-400">Approve a low-resolution preview before exporting a short.</p>
      ) : null}

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {ready.map((clip) => (
          <article key={clip.id} className="rounded-lg border border-white/10 bg-[#16181d] p-4">
            <h2 className="text-lg font-medium">{clip.suggested_title}</h2>
            <p className="mt-1 font-mono text-xs text-zinc-400">
              {formatTimestamp(clip.start)} – {formatTimestamp(clip.end)} · {formatClock(clip.duration)}
            </p>
            <p className="mt-3 text-sm leading-6">{clip.transcript}</p>
            {clip.render.has_export && project ? (
              <video
                key={`${clip.id}-${project.updated_at}`}
                src={`/api/projects/${project.id}/clips/${clip.id}/export`}
                controls
                playsInline
                className="mt-4 aspect-[9/16] w-full max-w-[220px] rounded-md bg-black"
              />
            ) : (
              <p className="mt-4 text-sm text-zinc-500">Approved. The full-size file has not been encoded yet.</p>
            )}
            <button
              type="button"
              disabled={busy || active || (clip.render.status !== "approved" && clip.render.status !== "exported")}
              onClick={() => void exportClip(clip)}
              className="mt-4 rounded-md bg-amber-400 px-3 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-40"
            >
              {active ? "Rendering…" : clip.render.has_export ? "Export again" : "Export 1080×1920"}
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
