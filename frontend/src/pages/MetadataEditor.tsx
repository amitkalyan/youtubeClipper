import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listHighlights, listMetadata, listProjects, saveMetadata, startMetadata } from "../api";
import { StatusPill } from "../components/StatusPill";
import { isActiveStatus } from "../format";
import type { Clip, ClipMetadata, Project } from "../types";

export function MetadataEditor() {
  const [params, setParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [packages, setPackages] = useState<ClipMetadata[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
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
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load metadata.");
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
    setNotice(null);
    try {
      setProject(await startMetadata(selected));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not draft metadata.");
    } finally {
      setBusy(false);
    }
  }

  async function save(clipId: string, pack: ClipMetadata) {
    setError(null);
    setNotice(null);
    try {
      const saved = await saveMetadata(selected, clipId, pack);
      setPackages((current) => current.map((item) => (item.clip_id === saved.clip_id ? saved : item)));
      setNotice("Saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this package.");
    }
  }

  const choices = (projects ?? []).filter((item) => item.clip_count > 0);
  const active = project ? isActiveStatus(project.status) : false;
  const byClip = new Map(packages.map((item) => [item.clip_id, item]));

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Metadata editor</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
        Ollama drafts three titles, a description, hashtags, a call to action, and keywords from the words that were
        spoken in that short. You can edit them. Nothing here promises that a title will perform well.
      </p>
      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
      {notice ? <p className="mt-4 text-sm text-emerald-300">{notice}</p> : null}
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
          {active ? "Drafting…" : "Draft from transcript"}
        </button>
        {project ? (
          <Link to={`/thumbnails?project=${project.id}`} className="text-sm text-amber-200 underline">
            Thumbnails
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
        <p className="mt-8 text-sm text-zinc-400">Find a short before drafting titles.</p>
      ) : null}
      <div className="mt-6 space-y-4">
        {clips.map((clip) => (
          <PackageCard
            key={clip.id}
            clip={clip}
            pack={byClip.get(clip.id)}
            disabled={active}
            onSave={(pack) => void save(clip.id, pack)}
          />
        ))}
      </div>
    </div>
  );
}

function PackageCard({
  clip,
  pack,
  disabled,
  onSave,
}: {
  clip: Clip;
  pack: ClipMetadata | undefined;
  disabled: boolean;
  onSave: (pack: ClipMetadata) => void;
}) {
  const [draft, setDraft] = useState<ClipMetadata | null>(pack ?? null);
  useEffect(() => {
    setDraft(pack ?? null);
  }, [pack]);
  if (!draft) {
    return (
      <article className="rounded-lg border border-white/10 bg-[#16181d] p-4">
        <h2 className="text-lg font-medium">{clip.suggested_title}</h2>
        <p className="mt-2 text-sm text-zinc-500">No draft yet.</p>
      </article>
    );
  }
  const field = "mt-2 w-full rounded-md border border-white/10 bg-[#0c0d10] px-3 py-2 text-sm";
  return (
    <article className="rounded-lg border border-white/10 bg-[#16181d] p-4">
      <h2 className="text-lg font-medium">{clip.suggested_title}</h2>
      <p className="mt-2 text-sm leading-6 text-zinc-400">{clip.transcript}</p>
      <form
        className="mt-4 grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(draft);
        }}
      >
        <fieldset className="grid gap-2">
          <legend className="text-xs uppercase tracking-wide text-zinc-500">Titles</legend>
          {draft.titles.map((title, index) => (
            <label key={index} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name={`title-${clip.id}`}
                checked={draft.selected_title === title}
                onChange={() => setDraft({ ...draft, selected_title: title })}
              />
              <input
                value={title}
                onChange={(event) => {
                  const titles = [...draft.titles];
                  const previous = titles[index];
                  titles[index] = event.target.value;
                  setDraft({
                    ...draft,
                    titles,
                    selected_title: draft.selected_title === previous ? event.target.value : draft.selected_title,
                  });
                }}
                className={field}
              />
            </label>
          ))}
        </fieldset>
        <label className="text-sm">
          Description
          <textarea
            value={draft.description}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            rows={4}
            className={field}
          />
        </label>
        <label className="text-sm">
          Hashtags
          <input
            value={draft.hashtags.join(" ")}
            onChange={(event) =>
              setDraft({
                ...draft,
                hashtags: event.target.value.split(/\s+/).filter(Boolean),
              })
            }
            className={field}
          />
        </label>
        <label className="text-sm">
          Call to action
          <input
            value={draft.cta}
            onChange={(event) => setDraft({ ...draft, cta: event.target.value })}
            className={field}
          />
        </label>
        <label className="text-sm">
          Keywords
          <input
            value={draft.keywords.join(", ")}
            onChange={(event) =>
              setDraft({
                ...draft,
                keywords: event.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
              })
            }
            className={field}
          />
        </label>
        <p className="text-xs text-zinc-500">Category: {draft.category}</p>
        <button
          type="submit"
          disabled={disabled}
          className="w-fit rounded-md bg-amber-400 px-3 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-40"
        >
          Save
        </button>
      </form>
    </article>
  );
}
