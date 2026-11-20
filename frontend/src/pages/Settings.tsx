import { useEffect, useState } from "react";
import { setOllamaModel } from "../api";
import { formatBytes } from "../format";
import { useHealth } from "../useHealth";

export function Settings() {
  const { health, error, reload } = useHealth();
  const [model, setModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (health?.ollama.model) setModel(health.ollama.model);
  }, [health?.ollama.model]);

  async function saveModel() {
    if (!model || saving) return;
    setSaving(true);
    setSaveError(null);
    setMessage(null);
    try {
      const next = await setOllamaModel(model);
      setMessage(`Highlight detection will use ${next.model}.`);
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save the model.");
    } finally {
      setSaving(false);
    }
  }

  const models = health?.ollama.models ?? [];

  return (
    <div className="max-w-3xl">
      <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-2 text-sm leading-6 text-zinc-400">
        Speech and FFmpeg values come from <code className="text-zinc-200">.env</code>. The highlight model is any
        model already installed in local Ollama.
      </p>
      {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
      {!health && !error ? <p className="mt-6 text-sm text-zinc-400">Loading…</p> : null}
      {health ? (
        <dl className="mt-8 grid gap-4 sm:grid-cols-2">
          <Item label="Profile" value={health.status === "ok" ? "Ready" : "Needs attention"} />
          <Item label="Speech model" value={`${health.whisper.model} · ${health.whisper.device} · ${health.whisper.compute_type}`} />
          <Item label="Threads" value={`${health.whisper.threads} effective (${health.whisper.configured_threads} configured)`} />
          <Item label="Voice activity filter" value={health.whisper.vad_filter ? "On" : "Off"} />
          <Item label="Concurrent jobs" value={String(health.jobs.max_concurrent)} />
          <Item label="Queue slots" value={String(health.jobs.max_queued)} />
          <Item label="Upload limit" value={formatBytes(health.max_upload_bytes)} />
          <Item label="FFmpeg" value={health.ffmpeg.version ?? health.ffmpeg.path} />
          <Item label="FFprobe" value={health.ffprobe.version ?? health.ffprobe.path} />
          <Item label="Data directory" value={health.data_dir} />
          <Item label="Export directory" value={health.output_dir} />
        </dl>
      ) : null}

      {health ? (
        <section className="mt-8 rounded-lg border border-white/10 bg-[#16181d] p-4">
          <h2 className="text-sm font-medium">Ollama model</h2>
          <p className="mt-2 text-sm text-zinc-400">{health.ollama.note}</p>
          {models.length ? (
            <div className="mt-4 flex flex-wrap items-end gap-3">
              <label className="text-sm" htmlFor="ollama-model">
                Installed models
                <select
                  id="ollama-model"
                  value={models.includes(model) ? model : health.ollama.model}
                  onChange={(event) => setModel(event.target.value)}
                  className="mt-2 block min-w-64 rounded-md border border-white/10 bg-[#0c0d10] px-3 py-2 text-sm"
                >
                  {models.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={saving || model === health.ollama.model}
                onClick={() => void saveModel()}
                className="rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {saving ? "Saving…" : "Use this model"}
              </button>
            </div>
          ) : null}
          {message ? <p className="mt-3 text-sm text-emerald-300">{message}</p> : null}
          {saveError ? <p className="mt-3 text-sm text-rose-300">{saveError}</p> : null}
          <p className="mt-3 text-xs leading-5 text-zinc-500">
            A model around 3B parameters is the comfortable size for 8 GB of RAM. Larger installed models can still be
            selected. Clipper runs one of them at a time and unloads it when scoring finishes.
          </p>
        </section>
      ) : null}

      {health?.whisper.profile_message ? (
        <p className="mt-4 rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">
          {health.whisper.profile_message}
        </p>
      ) : null}
    </div>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-[#16181d] px-4 py-3">
      <dt className="text-xs uppercase tracking-wide text-zinc-500">{label}</dt>
      <dd className="mt-1 break-words text-sm">{value}</dd>
    </div>
  );
}
