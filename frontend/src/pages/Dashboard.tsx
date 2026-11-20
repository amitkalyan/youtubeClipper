import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listProjects } from "../api";
import { StatusPill } from "../components/StatusPill";
import { formatClock, formatWhen, isActiveStatus } from "../format";
import type { Project } from "../types";
import { useHealth } from "../useHealth";

export function Dashboard() {
  const { health, error: healthError } = useHealth();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  }, []);

  const rows = projects ?? [];
  const ready = rows.filter((project) => project.status === "ready").length;
  const active = rows.filter((project) => isActiveStatus(project.status)).length;
  const failed = rows.filter((project) => project.status === "failed").length;
  const clips = rows.reduce((total, project) => total + (project.clip_count || 0), 0);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Paste a YouTube link for a video you have the right to edit. Clipper downloads it and cuts shorts from
            20 seconds to 1 minute. You approve a low-resolution preview before the full 1080×1920 export.
          </p>
        </div>
        <Link
          to="/new"
          className="rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-950 hover:bg-amber-300"
        >
          New project
        </Link>
      </div>

      {healthError ? <Banner tone="bad">{healthError}</Banner> : null}
      {health && !health.ffmpeg.available ? (
        <Banner tone="bad">FFmpeg is missing. Run scripts\fetch-ffmpeg.ps1 and restart the backend.</Banner>
      ) : null}
      {health?.whisper.profile_message ? <Banner tone="warn">{health.whisper.profile_message}</Banner> : null}
      {error ? <Banner tone="bad">{error}</Banner> : null}

      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Videos" value={projects ? String(rows.length) : "–"} />
        <Stat label="Transcripts ready" value={projects ? String(ready) : "–"} />
        <Stat label="In progress" value={projects ? String(active) : "–"} />
        <Stat label="Failed" value={projects ? String(failed) : "–"} />
        <Stat label="Clip candidates" value={projects ? String(clips) : "–"} />
      </div>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-zinc-300">Recent projects</h2>
        {projects && rows.length === 0 ? (
          <p className="mt-4 rounded-lg border border-dashed border-white/15 px-4 py-8 text-sm text-zinc-400">
            No videos yet. Add a YouTube link or a file to generate the first transcript.
          </p>
        ) : null}
        <ul className="mt-3 divide-y divide-white/10 overflow-hidden rounded-lg border border-white/10">
          {rows.map((project) => (
            <li key={project.id}>
              <Link to={`/projects/${project.id}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-white/5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{project.title}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {formatWhen(project.created_at)}
                    {project.duration_seconds != null ? ` · ${formatClock(project.duration_seconds)}` : ""}
                  </p>
                </div>
                <StatusPill status={project.status} />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-[#16181d] px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function Banner({ children, tone }: { children: string; tone: "bad" | "warn" }) {
  const color = tone === "bad" ? "border-rose-400/40 bg-rose-400/10 text-rose-100" : "border-amber-400/40 bg-amber-400/10 text-amber-100";
  return <p className={`mt-4 rounded-md border px-3 py-2 text-sm ${color}`}>{children}</p>;
}
