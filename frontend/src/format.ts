export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

export function formatTimestamp(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

export function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

const STATUS_LABELS: Record<string, string> = {
  uploaded: "Uploaded",
  queued: "Queued",
  downloading: "Downloading",
  extracting_audio: "Extracting audio",
  transcribing: "Transcribing",
  analyzing: "Finding highlights",
  rendering: "Rendering",
  packaging: "Drafting titles",
  ready: "Ready",
  failed: "Failed",
  cancelled: "Cancelled",
  running: "Running",
  completed: "Completed",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function isActiveStatus(status: string): boolean {
  return (
    status === "queued" ||
    status === "downloading" ||
    status === "extracting_audio" ||
    status === "transcribing" ||
    status === "analyzing" ||
    status === "rendering" ||
    status === "packaging" ||
    status === "running"
  );
}
