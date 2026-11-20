import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listJobs } from "../api";
import { StatusPill } from "../components/StatusPill";
import { formatWhen } from "../format";
import type { Job } from "../types";

export function History() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listJobs()
      .then((rows) => {
        if (!cancelled) setJobs(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load history.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Processing history</h1>
      <p className="mt-2 text-sm text-zinc-400">One transcription runs at a time. Older jobs stay in this list.</p>
      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
      {jobs && jobs.length === 0 ? <p className="mt-6 text-sm text-zinc-400">No processing jobs yet.</p> : null}
      {jobs && jobs.length > 0 ? (
        <div className="mt-6 overflow-x-auto rounded-lg border border-white/10">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-white/5 text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Project</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="px-4 py-3 font-medium">Stage</th>
                <th scope="col" className="px-4 py-3 font-medium">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td className="px-4 py-3">
                    <Link to={`/projects/${job.project_id}`} className="hover:text-amber-200">
                      {job.project_title}
                    </Link>
                    {job.error ? <p className="mt-1 max-w-md text-xs text-rose-300">{job.error}</p> : null}
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={job.status} />
                  </td>
                  <td className="px-4 py-3 text-zinc-400">{job.message}</td>
                  <td className="px-4 py-3 text-zinc-400">{formatWhen(job.started_at ?? job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
