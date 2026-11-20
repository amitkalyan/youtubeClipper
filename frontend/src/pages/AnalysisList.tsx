import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listProjects } from "../api";
import { StatusPill } from "../components/StatusPill";
import { formatClock, formatWhen } from "../format";
import type { Project } from "../types";

export function AnalysisList() {
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

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Video analysis</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
        Open a project to see metadata, processing progress, and the transcript with word times.
      </p>
      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
      {projects && projects.length === 0 ? (
        <p className="mt-6 text-sm text-zinc-400">
          Nothing to analyze yet. <Link to="/new" className="text-amber-200 underline">Upload a video</Link>.
        </p>
      ) : null}
      <ul className="mt-6 divide-y divide-white/10 overflow-hidden rounded-lg border border-white/10">
        {(projects ?? []).map((project) => (
          <li key={project.id}>
            <Link to={`/projects/${project.id}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-white/5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{project.title}</p>
                <p className="mt-1 text-xs text-zinc-500">
                  {formatWhen(project.updated_at)}
                  {project.duration_seconds != null ? ` · ${formatClock(project.duration_seconds)}` : ""}
                </p>
              </div>
              <StatusPill status={project.status} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
