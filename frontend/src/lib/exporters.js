// Client-side exports for static examples (no server needed). Formats match
// the backend writers byte-for-byte in layout.

import { applyEdits, unitsFor } from "../editing/applyEdits.js";

export function filteredPoints(points, ops, minConfidence) {
  const { positions, keep } = applyEdits(points.positions, ops);
  const thr = Math.round(minConfidence * 255);
  const idx = [];
  for (let i = 0; i < points.count; i++) {
    if (!keep[i]) continue;
    if (points.confidence && points.confidence[i] < thr) continue;
    idx.push(i);
  }
  return { positions, idx };
}

export function buildPly(points, ops, minConfidence) {
  const { positions, idx } = filteredPoints(points, ops, minConfidence);
  const units = unitsFor(ops);
  const hasConf = !!points.confidence;
  const header =
    [
      "ply",
      "format binary_little_endian 1.0",
      "comment sceneform point cloud export",
      `comment units: ${units.kind}${units.unit ? ` (${units.unit})` : ""}`,
      `comment confidence >= ${minConfidence.toFixed(2)}`,
      `element vertex ${idx.length}`,
      "property float x",
      "property float y",
      "property float z",
      "property uchar red",
      "property uchar green",
      "property uchar blue",
      ...(hasConf ? ["property float confidence"] : []),
      "end_header",
    ].join("\n") + "\n";
  const stride = 15 + (hasConf ? 4 : 0);
  const head = new TextEncoder().encode(header);
  const buf = new ArrayBuffer(head.length + stride * idx.length);
  new Uint8Array(buf).set(head);
  const dv = new DataView(buf);
  let o = head.length;
  for (const i of idx) {
    dv.setFloat32(o, positions[i * 3], true);
    dv.setFloat32(o + 4, positions[i * 3 + 1], true);
    dv.setFloat32(o + 8, positions[i * 3 + 2], true);
    dv.setUint8(o + 12, points.colors[i * 3]);
    dv.setUint8(o + 13, points.colors[i * 3 + 1]);
    dv.setUint8(o + 14, points.colors[i * 3 + 2]);
    if (hasConf) dv.setFloat32(o + 15, points.confidence[i] / 255, true);
    o += stride;
  }
  return { blob: new Blob([buf], { type: "application/octet-stream" }), count: idx.length };
}

export function buildPcd(points, ops, minConfidence) {
  const { positions, idx } = filteredPoints(points, ops, minConfidence);
  const n = idx.length;
  const header =
    "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z rgb\nSIZE 4 4 4 4\nTYPE F F F U\nCOUNT 1 1 1 1\n" +
    `WIDTH ${n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS ${n}\nDATA binary\n`;
  const head = new TextEncoder().encode(header);
  const buf = new ArrayBuffer(head.length + 16 * n);
  new Uint8Array(buf).set(head);
  const dv = new DataView(buf);
  let o = head.length;
  for (const i of idx) {
    dv.setFloat32(o, positions[i * 3], true);
    dv.setFloat32(o + 4, positions[i * 3 + 1], true);
    dv.setFloat32(o + 8, positions[i * 3 + 2], true);
    const c = (points.colors[i * 3] << 16) | (points.colors[i * 3 + 1] << 8) | points.colors[i * 3 + 2];
    dv.setUint32(o + 12, c >>> 0, true);
    o += 16;
  }
  return { blob: new Blob([buf], { type: "application/octet-stream" }), count: n };
}

export function buildReport(manifest, ops) {
  const m = manifest.metrics;
  const rep = m.sparseReprojectionErrorPx;
  const s = manifest.splat;
  const lines = [
    `# sceneform report — ${manifest.title}`,
    "",
    `Created ${manifest.createdAt} · mode: ${manifest.mode}`,
    "",
    "## Input",
    `- Source: ${manifest.source.type}`,
    `- Input quality: ${manifest.quality.score}/100 (${manifest.quality.grade}; heuristic score)`,
    ...manifest.quality.findings.map((f) => `  - ${f.message}`),
    "",
    "## Cameras",
    `- Registered views: ${m.registeredViews} of ${m.inputFrames}`,
    `- Sparse points: ${m.sparsePoints}`,
    `- Reprojection error: mean ${rep.mean?.toFixed(2)} px, median ${rep.median?.toFixed(2)} px, p90 ${rep.p90?.toFixed(2)} px`,
    `- Azimuthal camera coverage: ${m.coverageDeg.toFixed(0)}°`,
    "",
    "## Dense point cloud",
    `- Points: ${manifest.pointCloud.stats.count.toLocaleString()}`,
    `- Depth views fused: ${m.depthFusion.views_fused} (skipped ${m.depthFusion.views_skipped})`,
    `- Median SfM↔depth alignment error: ${((m.depthFusion.median_alignment_rel_error || 0) * 100).toFixed(2)}%`,
  ];
  if (manifest.mesh) {
    const d = manifest.mesh.diagnostics;
    lines.push("", "## Mesh", `- ${d.faces.toLocaleString()} faces, ${d.components} components, watertight: ${d.watertight}`);
  }
  if (s) {
    const h = s.training.heldout_metrics || {};
    lines.push(
      "",
      "## Gaussian splat",
      `- Trainer: ${s.training.trainer} (${s.training.device}), ${s.training.iterations.toLocaleString()} steps, ${s.stats.count.toLocaleString()} splats shipped`,
    );
    if (h.psnr != null)
      lines.push(`- Held-out views: PSNR ${h.psnr.toFixed(2)} dB, SSIM ${h.ssim?.toFixed(3)} over ${h.num_test} views (full frame)`);
  }
  lines.push(
    "",
    "## Edits",
    ops.length ? ops.map((o) => `- ${o.type} ${JSON.stringify(o.params)}`).join("\n") : "- none",
    "",
    "## Notes",
    "Confidence values are geometric-consistency scores, not real-world accuracy.",
    "Distances are in relative units unless a reference length was set.",
    manifest.license ? `\nSource media: ${manifest.license.attribution} — ${manifest.license.name}` : "",
    "",
  );
  return new Blob([lines.join("\n")], { type: "text/markdown" });
}

export function download(blobOrUrl, filename) {
  const url = typeof blobOrUrl === "string" ? blobOrUrl : URL.createObjectURL(blobOrUrl);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  if (typeof blobOrUrl !== "string") setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function slug(s) {
  return (
    String(s || "scene")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40) || "scene"
  );
}
