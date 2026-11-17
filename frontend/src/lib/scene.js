// Scene sources: the same manifest format serves precomputed examples (static
// files) and user projects (signed API URLs).

import { apiUrl } from "../api/client.js";

export function exampleSource(id) {
  const base = `${import.meta.env.BASE_URL}examples/${id}/`;
  return { kind: "example", id, key: `example:${id}`, url: (p) => base + p, base };
}

export function projectSource(projectId, runId, sig) {
  const base = apiUrl(`/api/projects/${projectId}/files/runs/${runId}/outputs/`);
  return {
    kind: "project",
    id: `${projectId}/${runId}`,
    projectId,
    runId,
    sig,
    key: `project:${projectId}:${runId}`,
    url: (p) => `${base}${p}?sig=${encodeURIComponent(sig)}`,
    exportUrl: (kind, params = {}) =>
      apiUrl(`/api/projects/${projectId}/runs/${runId}/export/${kind}?` + new URLSearchParams({ sig, ...params })),
  };
}

async function fetchChecked(url, as = "json", onProgress) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Couldn't load ${url.split("?")[0].split("/").pop()} (${res.status})`);
  if (as === "json") return res.json();
  if (!onProgress || !res.body) return res.arrayBuffer();
  const total = Number(res.headers.get("content-length")) || 0;
  const reader = res.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    if (total) onProgress(got / total);
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  return out.buffer;
}

export async function loadManifest(src) {
  return fetchChecked(src.url("manifest.json"));
}

export async function loadCameras(src, manifest) {
  return fetchChecked(src.url(manifest.cameras.file));
}

/** Decode the compact points.bin layout into typed arrays (zero-copy views). */
export function decodePoints(buffer, layout) {
  const n = layout.count;
  const out = {
    count: n,
    positions: new Float32Array(buffer, layout.position.offset, n * 3),
    colors: new Uint8Array(buffer, layout.color.offset, n * 3),
  };
  if (layout.confidence) out.confidence = new Uint8Array(buffer, layout.confidence.offset, n);
  if (layout.source) out.source = new Uint16Array(buffer, layout.source.offset, n);
  return out;
}

export async function loadPoints(src, entry, onProgress) {
  const buf = await fetchChecked(src.url(entry.file), "buffer", onProgress);
  return decodePoints(buf, entry.layout);
}

export async function loadDepth(src, depthMeta) {
  const buf = await fetchChecked(src.url(depthMeta.file), "buffer");
  const depth = new Uint16Array(buf);
  let conf = null;
  if (depthMeta.confidence) {
    try {
      conf = new Uint8Array(await fetchChecked(src.url(depthMeta.confidence), "buffer"));
    } catch {
      conf = null;
    }
  }
  return { depth, conf, ...depthMeta };
}

/** Decode a quantised depth value; returns null for invalid pixels. */
export function decodeDepth(meta, v) {
  if (v === meta.invalid) return null;
  return meta.near + (v / meta.scale) * (meta.far - meta.near);
}

export function unitsLabel(units) {
  if (!units || units.kind === "relative") return "units";
  return units.unit || "units";
}

export function formatBytes(b) {
  if (!b && b !== 0) return "—";
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(0)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

export function formatCount(n) {
  if (n == null) return "—";
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e4) return `${(n / 1e3).toFixed(0)}k`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
}

export function formatDuration(s) {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(0)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
}
