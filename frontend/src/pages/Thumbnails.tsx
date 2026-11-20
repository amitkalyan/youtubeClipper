import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listHighlights, listMetadata, listProjects, saveMetadata, startMetadata } from "../api";
import { StatusPill } from "../components/StatusPill";
import { isActiveStatus } from "../format";
import type { Clip, ClipMetadata, Project } from "../types";

export function Thumbnails() {
  const [params, setParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [packages, setPackages] = useState<ClipMetadata[]>([]);
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
      setClips([]);
      setPackages([]);
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
        setPackages(await listMetadata(selected));
        if (!isActiveStatus(next.status)) return;
        timer = window.setTimeout(() => void tick(), 1000);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load thumbnails.");
      }
    };
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selected, project?.status]);

  async function draft() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setProject(await startMetadata(selected));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not draft thumbnails.");
    } finally {
      setBusy(false);
    }
  }

  async function redraw(clip: Clip, pack: ClipMetadata, headline: string) {
    setError(null);
    try {
      const saved = await saveMetadata(selected, clip.id, { ...pack, headline });
      setPackages((current) => current.map((item) => (item.clip_id === saved.clip_id ? saved : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not redraw the thumbnail.");
    }
  }

  const choices = (projects ?? []).filter((item) => item.clip_count > 0);
  const active = project ? isActiveStatus(project.status) : false;
  const byClip = new Map(packages.map((item) => [item.clip_id, item]));

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Thumbnail studio</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
        Each thumbnail is one frame from the middle of the short. Pillow draws a headline made of words that were
        actually spoken. A local image model stays off.
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
          disabled={!selected || busy || active || clips.length === 0}
          onClick={() => void draft()}
          className="rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-40"
        >
          {active ? "Drafting…" : "Draft thumbnails"}
        </button>
        {project ? (
          <Link to={`/metadata?project=${project.id}`} className="text-sm text-amber-200 underline">
            Edit titles
          </Link>
        ) : null}
      </div>
      {project ? (
        <div className="mt-6 flex items-center gap-3">
          <StatusPill status={project.status} />
          <p className="text-sm text-zinc-400">{project.progress_message}</p>
        </div>
      ) : null}
      {project && clips.length === 0 && !active ? (
        <p className="mt-8 text-sm text-zinc-400">Find a short before drafting a thumbnail.</p>
      ) : null}
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {clips.map((clip) => {
          const pack = byClip.get(clip.id);
          return (
            <ThumbnailCard
              key={clip.id}
              projectId={selected}
              clip={clip}
              pack={pack}
              stamp={project?.updated_at ?? ""}
              disabled={active}
              onRedraw={(headline) => pack && void redraw(clip, pack, headline)}
            />
          );
        })}
      </div>
    </div>
  );
}

function ThumbnailCard({
  projectId,
  clip,
  pack,
  stamp,
  disabled,
  onRedraw,
}: {
  projectId: string;
  clip: Clip;
  pack: ClipMetadata | undefined;
  stamp: string;
  disabled: boolean;
  onRedraw: (headline: string) => void;
}) {
  const [headline, setHeadline] = useState(pack?.headline ?? "");
  useEffect(() => {
    setHeadline(pack?.headline ?? "");
  }, [pack?.headline]);
  return (
    <article className="rounded-lg border border-white/10 bg-[#16181d] p-4">
      <h2 className="text-sm font-medium">{clip.suggested_title}</h2>
      {pack?.has_thumbnail ? (
        <img
          src={`/api/projects/${projectId}/clips/${clip.id}/thumbnail?t=${encodeURIComponent(`${stamp}-${pack.headline}`)}`}
          alt={pack.headline}
          className="mt-3 aspect-[9/16] w-full max-w-[220px] rounded-md bg-black object-cover"
        />
      ) : (
        <p className="mt-3 text-sm text-zinc-500">No thumbnail yet.</p>
      )}
      {pack ? (
        <form
          className="mt-3"
          onSubmit={(event) => {
            event.preventDefault();
            onRedraw(headline);
          }}
        >
          <label className="text-xs text-zinc-400" htmlFor={`headline-${clip.id}`}>
            Headline
            <input
              id={`headline-${clip.id}`}
              value={headline}
              onChange={(event) => setHeadline(event.target.value)}
              className="mt-2 w-full rounded-md border border-white/10 bg-[#0c0d10] px-3 py-2 text-sm"
            />
          </label>
          <button
            type="submit"
            disabled={disabled || headline.trim() === pack.headline}
            className="mt-3 rounded-md border border-white/15 px-3 py-2 text-sm disabled:opacity-40"
          >
            Redraw
          </button>
        </form>
      ) : null}
    </article>
  );
}
