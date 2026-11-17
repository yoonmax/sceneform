// Thin client for the sceneform reconstruction API.
//
// The public website is a static deployment: it has no backend unless one is
// configured with VITE_API_URL (or in Settings → Advanced). Every caller must
// handle `backend.available === false` and say so plainly.

import { useStore } from "../state/store.js";

const ENV_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export function apiBase() {
  const o = useStore.getState().apiOverride;
  return (o || ENV_BASE || "").replace(/\/$/, "");
}

function randomHex(n) {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

let memoryToken = null;
export function ownerToken() {
  try {
    let t = localStorage.getItem("sceneform.owner");
    if (!t) {
      t = randomHex(24);
      localStorage.setItem("sceneform.owner", t);
    }
    return t;
  } catch {
    memoryToken = memoryToken || randomHex(24);
    return memoryToken;
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const FRIENDLY = {
  0: "We couldn't reach the reconstruction service. Check that it's running.",
  413: "That upload is too large.",
  429: "Too many requests at once. Please wait a moment and try again.",
  500: "The server ran into a problem. Please try again.",
};

export async function request(path, { method = "GET", body, json, signal, timeout = 30000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  signal?.addEventListener("abort", () => ctrl.abort());
  const headers = { "X-Sceneform-Owner": ownerToken() };
  if (json !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(apiBase() + path, {
      method,
      headers,
      body: json !== undefined ? JSON.stringify(json) : body,
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new ApiError(signal?.aborted ? "Cancelled" : FRIENDLY[0], 0);
  } finally {
    clearTimeout(timer);
  }
  const type = res.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    let msg = data?.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new ApiError(msg || FRIENDLY[res.status] || `Request failed (${res.status})`, res.status);
  }
  return data;
}

/** Resolve a server-relative URL (e.g. "/api/projects/…") against the API base. */
export function apiUrl(path) {
  if (!path) return path;
  if (/^https?:/.test(path)) return path;
  return apiBase() + path;
}

let healthCache = null;
export async function detectBackend(force = false) {
  if (healthCache && !force) return healthCache;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    const res = await fetch(apiBase() + "/api/health", { signal: ctrl.signal });
    clearTimeout(t);
    const type = res.headers.get("content-type") || "";
    // A static host answers with index.html — that is *not* a backend.
    if (!res.ok || !type.includes("application/json")) throw new Error("no backend");
    const h = await res.json();
    if (h.service !== "sceneform") throw new Error("not sceneform");
    const caps = await (await fetch(apiBase() + "/api/capabilities")).json();
    healthCache = { available: true, version: h.version, capabilities: caps };
  } catch {
    healthCache = { available: false };
  }
  return healthCache;
}

export const api = {
  listProjects: () => request("/api/projects"),
  createProject: (name) => request("/api/projects", { method: "POST", json: { name } }),
  getProject: (id) => request(`/api/projects/${id}`),
  renameProject: (id, name) => request(`/api/projects/${id}`, { method: "PATCH", json: { name } }),
  reorderAssets: (id, order) => request(`/api/projects/${id}`, { method: "PATCH", json: { asset_order: order } }),
  deleteProject: (id) => request(`/api/projects/${id}`, { method: "DELETE" }),
  duplicateProject: (id) => request(`/api/projects/${id}/duplicate`, { method: "POST" }),
  listAssets: (id) => request(`/api/projects/${id}/assets`),
  deleteAsset: (id, aid) => request(`/api/projects/${id}/assets/${aid}`, { method: "DELETE" }),
  analyze: (id, params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined));
    return request(`/api/projects/${id}/analyze?${q}`, { method: "POST", timeout: 180000 });
  },
  startJob: (id, mode, settings) => request(`/api/projects/${id}/jobs`, { method: "POST", json: { mode, settings } }),
  getJob: (jid) => request(`/api/jobs/${jid}`),
  cancelJob: (jid) => request(`/api/jobs/${jid}/cancel`, { method: "POST" }),
  retryJob: (jid) => request(`/api/jobs/${jid}/retry`, { method: "POST" }),
  jobLogs: (jid) => request(`/api/jobs/${jid}/logs`),
  getEdits: (pid, rid) => request(`/api/projects/${pid}/runs/${rid}/edits`),
  putEdits: (pid, rid, edits) => request(`/api/projects/${pid}/runs/${rid}/edits`, { method: "PUT", json: edits }),
};

/** Upload files with real byte-level progress (fetch can't report upload progress). */
export function uploadFiles(projectId, files, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${apiBase()}/api/projects/${projectId}/uploads`);
    xhr.setRequestHeader("X-Sceneform-Owner", ownerToken());
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      let data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(data?.detail || FRIENDLY[xhr.status] || "Upload failed", xhr.status));
    };
    xhr.onerror = () => reject(new ApiError(FRIENDLY[0], 0));
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    xhr.send(fd);
  });
}
