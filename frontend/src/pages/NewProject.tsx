import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createYoutubeProject, uploadProject } from "../api";
import { formatBytes } from "../format";
import { useHealth } from "../useHealth";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v,video/mp4,video/webm,video/quicktime";

export function NewProject() {
  const navigate = useNavigate();
  const { health } = useHealth();
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [rights, setRights] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const limit = health?.max_upload_bytes ?? 4 * 1024 * 1024 * 1024;
  const link = url.trim();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (link && file) {
      setError("Use a YouTube link or a file, not both.");
      return;
    }
    if (!link && !file) return;
    if (link && !rights) {
      setError("Confirm that you have the right to download and edit this video.");
      return;
    }
    if (file && file.size > limit) {
      setError(`That file is larger than the ${formatBytes(limit)} upload limit.`);
      return;
    }
    setError(null);
    setBusy(true);
    setProgress(0);
    try {
      const project = link
        ? await createYoutubeProject(link, title)
        : await uploadProject(file as File, title, setProgress);
      navigate(`/preview?project=${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the project.");
      setBusy(false);
    }
  }

  const canSubmit = !busy && (file !== null || (link.length > 0 && rights));

  return (
    <form onSubmit={onSubmit} className="max-w-2xl">
      <h1 className="text-3xl font-semibold tracking-tight">New project</h1>
      <p className="mt-2 text-sm leading-6 text-zinc-400">
        Paste one YouTube link. Clipper downloads that video, finds moments from 20 seconds to 1 minute, and builds a
        vertical preview of each short. Approve a preview before the full 1080×1920 export. A file on this computer
        follows the same path. Playlists and channel pages are skipped.
      </p>

      <label className="mt-8 block text-sm font-medium" htmlFor="title">
        Title
      </label>
      <input
        id="title"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Optional. Defaults to the video title or file name."
        maxLength={120}
        className="mt-2 w-full rounded-md border border-white/10 bg-[#16181d] px-3 py-2 text-sm outline-none"
      />

      <label className="mt-6 block text-sm font-medium" htmlFor="youtube">
        YouTube link
      </label>
      <input
        id="youtube"
        type="url"
        inputMode="url"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="https://www.youtube.com/watch?v=…"
        autoComplete="off"
        className="mt-2 w-full rounded-md border border-white/10 bg-[#16181d] px-3 py-2 text-sm outline-none"
      />
      {link ? (
        <label className="mt-3 flex items-start gap-2 text-sm text-zinc-300" htmlFor="rights">
          <input
            id="rights"
            type="checkbox"
            checked={rights}
            onChange={(event) => setRights(event.target.checked)}
            className="mt-1"
          />
          <span>I have the right to download and edit this video.</span>
        </label>
      ) : null}

      <p className="mt-6 text-xs uppercase tracking-wide text-zinc-500">or a file on this computer</p>
      <label
        htmlFor="video"
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          const next = event.dataTransfer.files[0];
          if (next) setFile(next);
        }}
        className={`mt-3 flex cursor-pointer flex-col items-center rounded-lg border border-dashed px-4 py-10 text-center ${
          dragOver ? "border-amber-300 bg-amber-400/10" : "border-white/15 bg-[#16181d]"
        }`}
      >
        <span className="text-sm font-medium">Drop a video here, or browse</span>
        <span className="mt-2 text-xs text-zinc-500">mp4, mov, mkv, webm, avi, m4v · up to {formatBytes(limit)}</span>
        {file ? (
          <span className="mt-4 text-sm text-amber-100">
            {file.name} · {formatBytes(file.size)}
          </span>
        ) : null}
        <input
          id="video"
          type="file"
          accept={ACCEPT}
          className="sr-only"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>

      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}

      <button
        type="submit"
        disabled={!canSubmit}
        className="mt-6 rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy && file ? `Uploading ${Math.round(progress * 100)}%` : busy ? "Starting…" : link ? "Create shorts" : "Upload and create shorts"}
      </button>
    </form>
  );
}
