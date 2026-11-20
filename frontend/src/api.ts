import type { Clip, ClipMetadata, Health, Job, Project, Transcript } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Cannot reach the backend. Start it with scripts\\start.ps1.");
  }
  if (!response.ok) {
    let detail = response.statusText || "Request failed.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) detail = body.detail;
    } catch {
      // The body was not JSON.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function setOllamaModel(model: string): Promise<Health["ollama"]> {
  return request<Health["ollama"]>("/api/settings/ollama-model", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
}

export function listProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export function getProject(id: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}`);
}

export function getTranscript(id: string): Promise<Transcript> {
  return request<Transcript>(`/api/projects/${id}/transcript`);
}

export function processProject(id: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}/process`, { method: "POST" });
}

export function startHighlights(id: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}/highlights`, { method: "POST" });
}

export function listHighlights(id: string): Promise<Clip[]> {
  return request<Clip[]>(`/api/projects/${id}/highlights`);
}

export function startPreviews(id: string, clipId?: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}/previews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_id: clipId ?? null }),
  });
}

export function startExport(id: string, clipId: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}/exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_id: clipId }),
  });
}

export function setClipCrop(id: string, clipId: string, offset: number, useDetector: boolean): Promise<Clip> {
  return request<Clip>(`/api/projects/${id}/clips/${clipId}/crop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ offset, use_detector: useDetector }),
  });
}

export function approveClip(id: string, clipId: string): Promise<Clip> {
  return request<Clip>(`/api/projects/${id}/clips/${clipId}/approve`, { method: "POST" });
}

export function startMetadata(id: string, clipId?: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}/metadata`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_id: clipId ?? null }),
  });
}

export function listMetadata(id: string): Promise<ClipMetadata[]> {
  return request<ClipMetadata[]>(`/api/projects/${id}/metadata`);
}

export function saveMetadata(id: string, clipId: string, body: Omit<ClipMetadata, "clip_id" | "project_id" | "category" | "has_thumbnail">): Promise<ClipMetadata> {
  return request<ClipMetadata>(`/api/projects/${id}/clips/${clipId}/metadata`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function cancelProject(id: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}/cancel`, { method: "POST" });
}

export function listJobs(): Promise<Job[]> {
  return request<Job[]>("/api/jobs");
}

export function createYoutubeProject(url: string, title: string): Promise<Project> {
  return request<Project>("/api/projects/youtube", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, title, confirmed_rights: true }),
  });
}

export function uploadProject(
  file: File,
  title: string,
  onProgress: (ratio: number) => void,
): Promise<Project> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/projects/upload");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => {
      reject(new ApiError(0, "Cannot reach the backend. Start it with scripts\\start.ps1."));
    };
    xhr.onload = () => {
      let body: { detail?: unknown } | null = null;
      try {
        body = JSON.parse(xhr.responseText) as { detail?: unknown };
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300 && body) {
        resolve(body as Project);
        return;
      }
      const detail = body && typeof body.detail === "string" ? body.detail : "Upload failed.";
      reject(new ApiError(xhr.status, detail));
    };
    const form = new FormData();
    form.append("file", file);
    if (title.trim()) form.append("title", title.trim());
    xhr.send(form);
  });
}
