import { useState } from "react";
import { Icon, Slider, useToast } from "../components/ui.jsx";
import { Section } from "./panels.jsx";
import { buildPcd, buildPly, buildReport, download, slug } from "../lib/exporters.js";
import { formatBytes } from "../lib/scene.js";
import { useStore } from "../state/store.js";

function Row({ title, detail, onClick, href, disabled, reason }) {
  const inner = (
    <>
      <div className="min-w-0">
        <div className="text-[13.5px] font-medium">{title}</div>
        <div className="truncate text-[12px] text-muted">{disabled ? reason : detail}</div>
      </div>
      <Icon name="download" size={16} className="shrink-0 text-muted" />
    </>
  );
  const cls = `flex w-full items-center justify-between gap-3 rounded-[2px] border border-line px-3.5 py-2.5 text-left transition-colors ${disabled ? "opacity-50" : "hover:border-line-strong hover:bg-surface"}`;
  if (href && !disabled) return <a className={cls} href={href} download>{inner}</a>;
  return <button className={cls} onClick={onClick} disabled={disabled}>{inner}</button>;
}

export default function ExportPanel({ manifest, src, points, sparse, loadSparse, ops, viewer }) {
  const view = useStore((s) => s.view);
  const [conf, setConf] = useState(view.confidence);
  const [busy, setBusy] = useState(null);
  const toast = useToast();
  const name = slug(manifest.title);
  const isProject = src.kind === "project";
  const run = async (key, fn) => {
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      toast(e.message || "Export failed", "error");
    } finally {
      setBusy(null);
    }
  };

  const pointsExport = (fmt) =>
    run(fmt, async () => {
      if (isProject) return download(src.exportUrl(fmt === "ply" ? "points-ply" : "points-pcd", { confidence: conf }), `sceneform-${name}-points.${fmt}`);
      const { blob, count } = (fmt === "ply" ? buildPly : buildPcd)(points, ops, conf);
      download(blob, `sceneform-${name}-points.${fmt}`);
      toast(`Exported ${count.toLocaleString()} points (${formatBytes(blob.size)})`, "success");
    });

  return (
    <>
      <Section title="Point cloud">
        <Slider label="Include confidence ≥" value={conf} min={0} max={1} step={0.05} onChange={setConf} format={(v) => v.toFixed(2)} />
        <Row title="Point cloud · PLY" detail="Positions, colors, confidence · MeshLab, Blender, CloudCompare" onClick={() => pointsExport("ply")} disabled={busy === "ply"} />
        <Row title="Point cloud · PCD" detail="Point Cloud Library binary format" onClick={() => pointsExport("pcd")} disabled={busy === "pcd"} />
        <Row
          title="Sparse SfM points · PLY"
          detail="Triangulated feature points"
          onClick={() =>
            run("sparse", async () => {
              if (isProject) return download(src.exportUrl("sparse-ply"), `sceneform-${name}-sparse.ply`);
              const sp = sparse || (await loadSparse());
              const { blob } = buildPly(sp, ops, 0);
              download(blob, `sceneform-${name}-sparse.ply`);
            })
          }
        />
        {ops.length > 0 && <p className="text-[12px] text-muted">Your {ops.length} edit(s) are applied to point exports.</p>}
      </Section>
      <Section title="Cameras">
        <Row title="Cameras · JSON" detail="Intrinsics, OpenCV extrinsics, three.js poses" href={src.url("cameras.json")} />
        <Row title="COLMAP model · cameras.txt" detail="PINHOLE intrinsics" href={src.url("colmap/cameras.txt")} />
        <Row title="COLMAP model · images.txt" detail="World-to-camera quaternions and translations" href={src.url("colmap/images.txt")} />
        <Row title="COLMAP model · points3D.txt" detail="Sparse points" href={src.url("colmap/points3D.txt")} />
      </Section>
      <Section title="Surfaces & splats">
        <Row title="Mesh · GLB" detail={manifest.mesh ? `${manifest.mesh.diagnostics.faces.toLocaleString()} faces, vertex colors` : ""} href={manifest.mesh ? (isProject ? src.exportUrl("mesh-glb") : src.url(manifest.mesh.file)) : null} disabled={!manifest.mesh} reason="No mesh was built for this scene" />
        {isProject && manifest.mesh && <Row title="Mesh · OBJ" detail="Wavefront OBJ" href={src.exportUrl("mesh-obj")} />}
        <Row title="Gaussian splat · PLY" detail={manifest.splat ? `${manifest.splat.stats.count.toLocaleString()} splats · ${formatBytes(manifest.splat.pruning.bytes)} · 3DGS format` : ""} href={manifest.splat ? src.url(manifest.splat.file) : null} disabled={!manifest.splat} reason="Requires high-quality mode" />
      </Section>
      <Section title="Frames, depth & report">
        {isProject ? (
          <>
            <Row title="Selected frames · ZIP" detail="The undistorted views used for reconstruction" href={src.exportUrl("frames-zip")} />
            <Row title="Depth maps · ZIP" detail="16-bit PNGs + decoding metadata" href={src.exportUrl("depth-zip")} />
          </>
        ) : (
          <p className="text-[12.5px] text-muted">Frames and depth maps can be viewed in the Cameras and Depth tabs. ZIP downloads are available for your own projects.</p>
        )}
        <Row title="Report · Markdown" detail="Quality metrics, settings and limitations" onClick={() => (isProject ? download(src.exportUrl("report-md"), `sceneform-${name}-report.md`) : download(buildReport(manifest, ops), `sceneform-${name}-report.md`))} />
        <Row title="Screenshot · PNG" detail="Current view at 2× resolution" onClick={() => run("shot", async () => download(viewer.current.screenshot(2), `sceneform-${name}.png`))} />
      </Section>
    </>
  );
}
