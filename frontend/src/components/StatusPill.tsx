import { statusLabel } from "../format";

const TONE: Record<string, string> = {
  ready: "bg-emerald-400/15 text-emerald-300",
  completed: "bg-emerald-400/15 text-emerald-300",
  failed: "bg-rose-400/15 text-rose-300",
  cancelled: "bg-zinc-500/20 text-zinc-300",
  uploaded: "bg-zinc-500/20 text-zinc-300",
  queued: "bg-sky-400/15 text-sky-200",
  downloading: "bg-amber-400/15 text-amber-200",
  running: "bg-amber-400/15 text-amber-200",
  extracting_audio: "bg-amber-400/15 text-amber-200",
  transcribing: "bg-amber-400/15 text-amber-200",
  analyzing: "bg-amber-400/15 text-amber-200",
  rendering: "bg-amber-400/15 text-amber-200",
  packaging: "bg-amber-400/15 text-amber-200",
};

export function StatusPill({ status }: { status: string }) {
  const tone = TONE[status] ?? "bg-zinc-500/20 text-zinc-300";
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>
      {statusLabel(status)}
    </span>
  );
}
