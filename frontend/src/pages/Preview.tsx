import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { approveClip, listHighlights, listProjects, setClipCrop, startPreviews } from "../api";
import { StatusPill } from "../components/StatusPill";
import { formatClock, formatTimestamp, isActiveStatus } from "../format";
import type { Clip, Project } from "../types";

export function Preview() {
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
        if (next.clip_count > 0) setClips(await listHighlights(selected));
        else setClips([]);
        if (!isActiveStatus(next.status)) return;
        timer = window.setTimeout(() => void tick(), 1000);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load the preview.");
      }
    };
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selected, project?.status]);

  async function build(clipId?: string) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setProject(await startPreviews(selected, clipId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the preview.");
    } finally {
      setBusy(false);
    }
  }

  async function saveCrop(clip: Clip, offset: number, useDetector: boolean) {
    if (!selected) return;
    setError(null);
    try {
      const next = await setClipCrop(selected, clip.id, offset, useDetector);
      setClips((current) => (current ?? []).map((item) => (item.id === next.id ? next : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the crop.");
    }
  }

  async function approve(clip: Clip) {
    if (!selected) return;
    setError(null);
    try {
      const next = await approveClip(selected, clip.id);
      setClips((current) => (current ?? []).map((item) => (item.id === next.id ? next : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve this preview.");
    }
  }

  const choices = (projects ?? []).filter((item) => item.has_transcript);
  const active = project ? isActiveStatus(project.status) : false;

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Video preview</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
        Each highlight is framed from a 360 px, one-frame-per-second proxy. A face, when one is found, sets the
        vertical window. You can override that with a manual crop. The preview is 360×640. The 1080×1920 file is
        created only after you approve it. Zoom stays off.
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
        <button
          type="button"
          disabled={!selected || busy || active || !clips?.length}
          onClick={() => void build()}
          className="rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {active ? "Rendering…" : "Build previews"}
        </button>
        {project && clips?.some((clip) => clip.render.status === "approved" || clip.render.has_export) ? (
          <Link to={`/shorts?project=${project.id}`} className="text-sm text-amber-200 underline">
            Generated shorts
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
      {clips && clips.length === 0 && project && !active ? (
        <p className="mt-8 text-sm text-zinc-400">Find highlights first. A preview is built from those moments.</p>
      ) : null}

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {(clips ?? []).map((clip) => (
          <article key={clip.id} className="rounded-lg border border-white/10 bg-[#16181d] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-medium">{clip.suggested_title}</h2>
                <p className="mt-1 font-mono text-xs text-zinc-400">
                  {formatTimestamp(clip.start)} – {formatTimestamp(clip.end)} · {formatClock(clip.duration)}
                </p>
              </div>
              <p className="text-sm text-zinc-400">{labelFor(clip.render.status)}</p>
            </div>
            {clip.render.has_preview && project ? (
              <video
                key={`${clip.id}-${project.updated_at}`}
                src={`/api/projects/${project.id}/clips/${clip.id}/preview`}
                controls
                playsInline
                className="mt-4 aspect-[9/16] w-full max-w-[220px] rounded-md bg-black"
              />
            ) : (
              <p className="mt-4 text-sm text-zinc-500">No preview yet.</p>
            )}
            <p className="mt-3 text-sm text-zinc-400">
              {clip.render.crop_mode === "pad"
                ? "This frame is already vertical, so it is scaled and padded."
                : clip.render.crop_mode === "face"
                  ? "The crop follows a detected face."
                  : clip.render.crop_mode === "manual"
                    ? "A manual crop is saved and replaces face detection."
                    : clip.render.crop_mode === "center"
                      ? "No face was found, so the crop stays centered."
                      : "The first preview uses the center until a face is found."}
              {clip.render.error ? ` ${clip.render.error}` : ""}
            </p>
            {clip.render.crop_mode !== "pad" ? (
              <Framing
                clip={clip}
                disabled={active}
                onSave={(offset, useDetector) => void saveCrop(clip, offset, useDetector)}
              />
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy || active}
                onClick={() => void build(clip.id)}
                className="rounded-md border border-white/15 px-3 py-2 text-sm disabled:opacity-40"
              >
                Build this preview
              </button>
              <button
                type="button"
                disabled={busy || active || clip.render.status !== "preview_ready"}
                onClick={() => void approve(clip)}
                className="rounded-md bg-amber-400 px-3 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-40"
              >
                {clip.render.status === "approved" || clip.render.has_export ? "Approved" : "Approve"}
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function Framing({
  clip,
  disabled,
  onSave,
}: {
  clip: Clip;
  disabled: boolean;
  onSave: (offset: number, useDetector: boolean) => void;
}) {
  const [offset, setOffset] = useState(clip.render.manual_offset);
  useEffect(() => {
    setOffset(clip.render.manual_offset);
  }, [clip.render.manual_offset, clip.render.use_manual]);

  return (
    <div className="mt-4">
      <label className="text-xs text-zinc-400" htmlFor={`crop-${clip.id}`}>
        Manual crop · {offset.toFixed(2)} · left is -1, right is 1
        <input
          id={`crop-${clip.id}`}
          type="range"
          min={-1}
          max={1}
          step={0.05}
          value={offset}
          disabled={disabled}
          onChange={(event) => setOffset(Number(event.target.value))}
          className="mt-2 block w-full"
        />
      </label>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSave(offset, false)}
          className="rounded-md border border-white/15 px-3 py-2 text-sm disabled:opacity-40"
        >
          Save framing
        </button>
        <button
          type="button"
          disabled={disabled || !clip.render.use_manual}
          onClick={() => onSave(0, true)}
          className="rounded-md border border-white/15 px-3 py-2 text-sm disabled:opacity-40"
        >
          Use face detection
        </button>
      </div>
      {clip.render.status === "none" && (clip.render.use_manual || clip.render.manual_offset !== 0) ? (
        <p className="mt-2 text-xs text-amber-100">Framing changed. Build the preview again before approving.</p>
      ) : null}
    </div>
  );
}

function labelFor(status: string): string {
  if (status === "preview_ready") return "Preview ready";
  if (status === "approved") return "Approved";
  if (status === "exported") return "Exported";
  if (status === "failed") return "Failed";
  return "Not built";
}
