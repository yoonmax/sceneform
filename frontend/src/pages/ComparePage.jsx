import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import SceneViewer from "../viewer/SceneViewer.jsx";
import { Icon, ProgressBar, Seg } from "../components/ui.jsx";
import { exampleSource, formatBytes, formatCount, formatDuration, loadCameras, loadManifest, loadPoints, projectSource } from "../lib/scene.js";
import { listExamples } from "../api/examples.js";
import { api } from "../api/client.js";
import { DEFAULT_VIEW } from "../state/store.js";

async function resolve(spec) {
  const [kind, a, b] = (spec || "").split(":");
  if (kind === "example") return exampleSource(a);
  if (kind === "project") {
    const p = await api.getProject(a);
    return projectSource(a, b, p.sig);
  }
  throw new Error("Unknown scene");
}

function useScene(spec) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let live = true;
    setState({ loading: true });
    (async () => {
      try {
        const src = await resolve(spec);
        const manifest = await loadManifest(src);
        const [cameras, points] = await Promise.all([loadCameras(src, manifest), loadPoints(src, manifest.pointCloud)]);
        if (live) setState({ src, manifest, cameras, points });
      } catch (e) {
        if (live) setState({ error: e.message });
      }
    })();
    return () => {
      live = false;
    };
  }, [spec]);
  return state;
}

function Side({ scene, label, view, setView, sync, syncId }) {
  const [sparse, setSparse] = useState(null);
  useEffect(() => {
    if (view.pointSet === "sparse" && scene.manifest && !sparse) loadPoints(scene.src, scene.manifest.sparse).then(setSparse);
  }, [view.pointSet, scene, sparse]);
  if (scene.error) return <div className="flex h-full items-center justify-center p-6 text-center text-bad">{scene.error}</div>;
  if (!scene.manifest || !scene.points) return <div className="canvas-bg flex h-full items-center justify-center"><div className="w-48"><ProgressBar value={null} label="Loading" /></div></div>;
  const m = scene.manifest;
  return (
    <div className="relative h-full">
      <SceneViewer
        manifest={m}
        cameras={scene.cameras}
        points={scene.points}
        sparse={sparse}
        view={view}
        tool="orbit"
        splatUrl={m.splat ? scene.src.url(m.splat.file) : null}
        meshUrl={m.mesh ? scene.src.url(m.mesh.file) : null}
        measurePoints={[]}
        sync={sync}
        syncId={syncId}
        unitsLabel="units"
      />
      <div className="absolute left-3 top-3 flex flex-wrap items-center gap-2">
        <span className="chip bg-bg/90">{label}</span>
        <div className="seg bg-bg/85" role="group" aria-label={`${label} representation`}>
          {[["points:dense", "Dense"], ["points:sparse", "Sparse"], ["splat:dense", "Splat"], ["mesh:dense", "Mesh"]].map(([k, l]) => {
            const [layer, pointSet] = k.split(":");
            const ok = layer === "points" || (layer === "splat" ? !!m.splat : !!m.mesh);
            return (
              <button key={k} disabled={!ok} className="disabled:opacity-35" aria-pressed={view.layer === layer && (layer !== "points" || view.pointSet === pointSet)}
                onClick={() => setView({ ...view, layer, pointSet })}>
                {l}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function statRows(m) {
  if (!m) return null;
  const x = m.metrics;
  return {
    "Input": `${x.inputFrames} ${m.source.type === "video" ? "frames (video)" : "photos"}`,
    "Cameras registered": `${x.registeredViews} / ${x.inputFrames}`,
    "Reprojection (mean)": `${x.sparseReprojectionErrorPx.mean?.toFixed(3)} px`,
    "Sparse points": formatCount(x.sparsePoints),
    "Dense points": formatCount(m.pointCloud.stats.count),
    "Confidence ≥ 0.5": `${Math.round((m.pointCloud.stats.confidenceHistogram.slice(10).reduce((a, b) => a + b, 0) / Math.max(1, m.pointCloud.stats.count)) * 100)}%`,
    "Point cloud size": formatBytes(m.pointCloud.layout.bytes),
    "Splat": m.splat ? `${formatCount(m.splat.stats.count)} · ${formatBytes(m.splat.pruning.bytes)}` : "—",
    "Held-out PSNR": x.splatHeldout?.psnr != null ? `${x.splatHeldout.psnr.toFixed(2)} dB` : "—",
    "Mesh faces": m.mesh ? formatCount(m.mesh.diagnostics.faces) : "—",
    "Processing time": formatDuration(m.processing.totalSeconds),
  };
}

export default function ComparePage() {
  const [params, setParams] = useSearchParams();
  const [examples, setExamples] = useState([]);
  const a = params.get("a") || "example:plaster-skull";
  const b = params.get("b") || a;
  const A = useScene(a);
  const B = useScene(b);
  const sync = useRef({});
  const [viewA, setViewA] = useState({ ...DEFAULT_VIEW, showGrid: false, layer: "points", pointSet: "sparse" });
  const [viewB, setViewB] = useState({ ...DEFAULT_VIEW, showGrid: false, layer: "points", pointSet: "dense" });
  const [orient, setOrient] = useState("row");

  useEffect(() => {
    listExamples().then(setExamples).catch(() => {});
  }, []);

  const ra = statRows(A.manifest),
    rb = statRows(B.manifest);

  const picker = (value, key) => (
    <select className="field h-8 w-auto text-[12.5px]" value={value} onChange={(e) => setParams({ a, b, [key]: e.target.value })} aria-label={`Scene ${key.toUpperCase()}`}>
      {examples.map((e) => <option key={e.id} value={`example:${e.id}`}>{e.title}</option>)}
      {!value.startsWith("example:") && <option value={value}>Your scene ({value.split(":")[2]})</option>}
    </select>
  );

  return (
    <div className="flex h-[calc(100dvh-56px-64px)] flex-col md:h-[calc(100dvh-56px)]">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2">
        <Link to="/explore" className="btn btn-ghost btn-icon" aria-label="Back"><Icon name="arrowLeft" size={16} /></Link>
        <h1 className="text-[14px] font-medium">Compare</h1>
        <div className="flex items-center gap-2 text-[12.5px] text-muted">A {picker(a, "a")} B {picker(b, "b")}</div>
        <span className="text-[12px] text-faint">Cameras are synchronized — move either view.</span>
        <div className="ml-auto hidden sm:block">
          <Seg label="Layout" value={orient} onChange={setOrient} options={[{ value: "row", label: "Side by side" }, { value: "col", label: "Stacked" }]} />
        </div>
      </div>
      <div className={`grid min-h-0 flex-1 ${orient === "row" ? "grid-cols-1 grid-rows-2 sm:grid-cols-2 sm:grid-rows-1" : "grid-rows-2"} gap-px bg-line`}>
        <div className="relative min-h-0 bg-bg"><Side scene={A} label="A" view={viewA} setView={setViewA} sync={sync} syncId="a" /></div>
        <div className="relative min-h-0 bg-bg"><Side scene={B} label="B" view={viewB} setView={setViewB} sync={sync} syncId="b" /></div>
      </div>
      {ra && rb && (
        <details className="border-t border-line bg-raised" open>
          <summary className="cursor-pointer px-4 py-2 text-[12.5px] text-muted">Quality indicators</summary>
          <div className="max-h-48 overflow-auto px-4 pb-3 scroll-thin">
            <table className="w-full text-[12.5px]">
              <thead><tr className="text-left text-muted"><th className="py-1 font-normal">Metric</th><th className="font-normal">A</th><th className="font-normal">B</th></tr></thead>
              <tbody className="font-mono tabular">
                {Object.keys(ra).map((k) => (
                  <tr key={k} className="border-t border-line"><td className="py-1 font-sans text-ink-2">{k}</td><td>{ra[k]}</td><td>{rb[k]}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11.5px] text-faint">Confidence is multi-view agreement, not accuracy. PSNR is measured on held-out photos over the full frame.</p>
          </div>
        </details>
      )}
    </div>
  );
}
