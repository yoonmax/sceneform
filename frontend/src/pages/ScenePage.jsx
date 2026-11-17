import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import SceneViewer from "../viewer/SceneViewer.jsx";
import { CamerasPanel, DiagnosticsPanel, MeasurePanel, OverviewPanel, ViewPanel } from "../inspect/panels.jsx";
import DepthPanel from "../inspect/DepthPanel.jsx";
import EditPanel from "../inspect/EditPanel.jsx";
import ExportPanel from "../inspect/ExportPanel.jsx";
import PhotoCompare from "../inspect/PhotoCompare.jsx";
import { Icon, ProgressBar, Tip, useToast } from "../components/ui.jsx";
import { EditHistory, applyEdits, totalTransform, unitsFor } from "../editing/applyEdits.js";
import { exampleSource, loadCameras, loadManifest, loadPoints, projectSource, formatCount } from "../lib/scene.js";
import { api } from "../api/client.js";
import { localdb, rememberRecent } from "../storage/localdb.js";
import { useStore } from "../state/store.js";

const TABS = [
  ["overview", "Overview", "info"],
  ["view", "View", "eye"],
  ["cameras", "Cameras", "camera"],
  ["depth", "Depth", "layers"],
  ["measure", "Measure", "ruler"],
  ["edit", "Edit", "edit"],
  ["export", "Export", "download"],
  ["diagnostics", "Diagnostics", "chart", true],
];

function ToolButton({ label, icon, onClick, active, shortcut }) {
  return (
    <Tip text={shortcut ? `${label} (${shortcut})` : label}>
      <button
        className={`flex h-9 w-9 items-center justify-center rounded-[2px] transition-colors ${active ? "bg-ink text-bg" : "text-ink-2 hover:bg-surface hover:text-ink"}`}
        onClick={onClick}
        aria-label={label}
        aria-pressed={active}
      >
        <Icon name={icon} size={18} />
      </button>
    </Tip>
  );
}

export default function ScenePage() {
  const { exampleId, projectId, runId } = useParams();
  const toast = useToast();
  const viewer = useRef();
  const scaleBar = useRef();
  const scaleText = useRef();
  const [src, setSrc] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [cameras, setCameras] = useState(null);
  const [points, setPoints] = useState(null);
  const [sparse, setSparse] = useState(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [history] = useState(() => new EditHistory());
  const [ops, setOps] = useState([]);
  const [saving, setSaving] = useState(false);
  const [layerStatus, setLayerStatus] = useState({});
  const [compareIdx, setCompareIdx] = useState(null);
  const [runs, setRuns] = useState([]);

  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const tool = useStore((s) => s.tool);
  const setTool = useStore((s) => s.setTool);
  const selected = useStore((s) => s.selectedCamera);
  const selectCamera = useStore((s) => s.selectCamera);
  const measurePoints = useStore((s) => s.measurePoints);
  const addMeasurePoint = useStore((s) => s.addMeasurePoint);
  const setHover = useStore((s) => s.setHover);
  const hover = useStore((s) => s.hoverPoint);
  const inspector = useStore((s) => s.inspector);
  const setInspector = useStore((s) => s.setInspector);
  const sheetOpen = useStore((s) => s.sheetOpen);
  const setSheetOpen = useStore((s) => s.setSheetOpen);
  const advanced = useStore((s) => s.expertise === "advanced");
  const resetView = useStore((s) => s.resetView);

  // ------------------------------------------------------------ loading
  useEffect(() => {
    resetView();
    let live = true;
    setManifest(null);
    setPoints(null);
    setSparse(null);
    setError(null);
    setProgress(0);
    (async () => {
      try {
        let s;
        if (exampleId) s = exampleSource(exampleId);
        else {
          const p = await api.getProject(projectId);
          s = projectSource(projectId, runId, p.sig);
          setRuns(p.runs || []);
        }
        const m = await loadManifest(s);
        if (!live) return;
        setSrc(s);
        setManifest(m);
        document.title = `${m.title} · sceneform`;
        const [c, pts] = await Promise.all([loadCameras(s, m), loadPoints(s, m.pointCloud, (f) => live && setProgress(f))]);
        if (!live) return;
        setCameras(c);
        setPoints(pts);
        setView({ confidence: m.pointCloud.defaultConfidence ?? 0.5 });
        // Default to the splat on capable desktop GPUs; points elsewhere.
        const mobile = matchMedia("(max-width: 768px)").matches;
        if (m.splat && !mobile) setView({ layer: "splat" });
        const saved = exampleId ? await localdb.get("edits", s.key) : await api.getEdits(projectId, runId).catch(() => null);
        if (saved?.ops?.length) {
          history.present = saved.ops;
          setOps(saved.ops);
        }
        rememberRecent(s.key, { title: m.title, kind: s.kind, path: location.pathname, cover: s.url(m.cover) });
      } catch (e) {
        if (live) setError(e.message || "This scene couldn't be loaded.");
      }
    })();
    return () => {
      live = false;
      document.title = "sceneform";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exampleId, projectId, runId]);

  const loadSparse = useCallback(async () => {
    if (sparse) return sparse;
    const sp = await loadPoints(src, manifest.sparse);
    setSparse(sp);
    return sp;
  }, [sparse, src, manifest]);

  useEffect(() => {
    if (view.pointSet === "sparse" && manifest && !sparse) loadSparse().catch((e) => toast(e.message, "error"));
  }, [view.pointSet, manifest, sparse, loadSparse, toast]);

  // -------------------------------------------------------------- edits
  const edited = useMemo(() => (points ? applyEdits(points.positions, ops) : null), [points, ops]);
  const transform = useMemo(() => totalTransform(ops), [ops]);
  const units = useMemo(() => unitsFor(ops), [ops]);

  const persist = useCallback(
    async (next) => {
      if (!src) return;
      setSaving(true);
      try {
        if (src.kind === "example") await localdb.set("edits", src.key, { version: 1, ops: next });
        else await api.putEdits(src.projectId, src.runId, { version: 1, ops: next });
      } catch (e) {
        toast(`Edits couldn't be saved: ${e.message}`, "error");
      } finally {
        setSaving(false);
      }
    },
    [src, toast],
  );
  const commit = (next) => {
    setOps(next);
    persist(next);
  };
  const pushOp = (op) => commit(history.push(op));
  const undo = () => commit(history.undo());
  const redo = () => commit(history.redo());

  // ------------------------------------------------------------ keyboard
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest("input,textarea,select,[contenteditable]")) return;
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === "z") {
        e.preventDefault();
        return e.shiftKey ? redo() : undo();
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (tool === "fly" && "wasdqe".includes(k)) return;
      if (k === "1") setView({ layer: "points" });
      else if (k === "2" && manifest?.splat) setView({ layer: "splat", projection: "perspective" });
      else if (k === "3" && manifest?.mesh) setView({ layer: "mesh" });
      else if (k === "f") viewer.current?.fit();
      else if (k === "h") viewer.current?.home();
      else if (k === "c") setView({ showCameras: !useStore.getState().view.showCameras });
      else if (k === "m") setTool(tool === "measure" ? "orbit" : "measure");
      else if (k === "g") setTool(tool === "fly" ? "orbit" : "fly");
      else if (k === "escape") {
        setTool("orbit");
        setCompareIdx(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) {
    return (
      <div className="mx-auto max-w-lg px-6 py-24 text-center">
        <h1 className="serif text-[26px]">Couldn’t open this scene</h1>
        <p className="mt-3 text-muted">{error}</p>
        <div className="mt-6 flex justify-center gap-2">
          <Link to="/explore" className="btn btn-primary">Browse examples</Link>
          <Link to="/projects" className="btn btn-secondary">Your projects</Link>
        </div>
      </div>
    );
  }

  const ready = manifest && cameras && points;
  const tabs = TABS.filter((t) => !t[3] || advanced);
  const frameUrl = selected != null && cameras && src ? src.url(cameras.cameras[selected].frame) : null;

  const panel = ready && (
    <div className="min-h-0 flex-1 overflow-y-auto scroll-thin">
      {inspector === "overview" && <OverviewPanel manifest={manifest} units={units} />}
      {inspector === "view" && <ViewPanel manifest={manifest} layerStatus={layerStatus} />}
      {inspector === "cameras" && <CamerasPanel cameras={cameras} src={src} viewer={viewer} onCompare={setCompareIdx} />}
      {inspector === "depth" && <DepthPanel manifest={manifest} cameras={cameras} src={src} units={units} />}
      {inspector === "measure" && (
        <MeasurePanel units={units} onScaleReference={(measured, actual, unit) => pushOp({ type: "scaleReference", params: { measured, actual, unit } })} />
      )}
      {inspector === "edit" && (
        <EditPanel manifest={manifest} points={points} ops={ops} history={history} onPush={pushOp} onUndo={undo} onRedo={redo}
          onReset={() => commit(history.reset())} editedPositions={edited?.positions} keepMask={edited?.keep} saving={saving} />
      )}
      {inspector === "export" && <ExportPanel manifest={manifest} src={src} points={points} sparse={sparse} loadSparse={loadSparse} ops={ops} viewer={viewer} />}
      {inspector === "diagnostics" && <DiagnosticsPanel manifest={manifest} cameras={cameras} />}
    </div>
  );

  return (
    <div className="relative flex h-[calc(100dvh-56px-64px)] md:h-[calc(100dvh-56px)]">
      <div className="relative min-w-0 flex-1">
        {ready ? (
          <SceneViewer
            ref={viewer}
            manifest={manifest}
            cameras={cameras}
            points={points}
            sparse={sparse}
            keepMask={edited?.keep}
            transform={transform}
            view={view}
            tool={tool}
            splatUrl={manifest.splat ? src.url(manifest.splat.file) : null}
            meshUrl={manifest.mesh ? src.url(manifest.mesh.file) : null}
            frameUrl={frameUrl}
            selectedCamera={selected}
            onSelectCamera={(i) => {
              selectCamera(i);
              setInspector("cameras");
            }}
            measurePoints={measurePoints}
            onPick={({ point }) => addMeasurePoint(point)}
            onHover={setHover}
            onLayerStatus={(s) => setLayerStatus((cur) => ({ ...cur, [s.layer]: { ...cur[s.layer], ...s } }))}
            unitsLabel={units.kind === "relative" ? "units" : units.unit}
            scaleBar={scaleBar}
            scaleText={scaleText}
          />
        ) : (
          <div className="canvas-bg absolute inset-0 flex items-center justify-center">
            <div className="w-64 space-y-3 text-center" role="status">
              <div className="text-[13.5px] text-ink-2">{manifest ? `Loading ${formatCount(manifest.pointCloud.stats.count)} points…` : "Opening scene…"}</div>
              <ProgressBar value={manifest ? progress : null} label="Loading scene" />
            </div>
          </div>
        )}

        {/* title */}
        <div className="pointer-events-none absolute left-3 top-3 right-3 flex items-start justify-between gap-3 sm:left-4 sm:top-4">
          <div className="pointer-events-auto flex items-stretch border border-line bg-raised">
            <Link to={exampleId ? "/explore" : "/projects"} className="flex w-8 items-center justify-center border-r border-line text-muted hover:bg-surface hover:text-ink" aria-label="Back">
              <Icon name="arrowLeft" size={15} />
            </Link>
            <div className="min-w-0 px-3 py-1.5">
              <h1 className="serif truncate text-[15px]">{manifest?.title || "…"}</h1>
              {manifest && (
                <p className="font-mono text-[10.5px] text-muted">
                  {manifest.example ? "reference" : "project"} · {manifest.metrics.registeredViews}/{manifest.metrics.inputFrames} views ·{" "}
                  {manifest.metrics.sparseReprojectionErrorPx.mean?.toFixed(2)} px · {units.kind === "relative" ? "relative units" : `${units.unit} (scale-est.)`}
                </p>
              )}
            </div>
          </div>
          {ready && (
            <div className="pointer-events-auto seg" role="group" aria-label="Representation">
              {[["points", "Points", true], ["splat", "Splat", !!manifest.splat], ["mesh", "Mesh", !!manifest.mesh]].map(([k, l, ok]) => (
                <button key={k} aria-pressed={view.layer === k} disabled={!ok} title={ok ? `${l} (${k === "points" ? 1 : k === "splat" ? 2 : 3})` : `No ${l.toLowerCase()} for this scene`} className="disabled:opacity-35"
                  onClick={() => setView({ layer: k, projection: k === "splat" ? "perspective" : view.projection })}>
                  {l}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* tool rail */}
        {ready && (
          <div className="absolute left-3 top-1/2 flex -translate-y-1/2 flex-col border border-line bg-raised sm:left-4" role="toolbar" aria-label="Viewer tools" aria-orientation="vertical">
            <ToolButton label="Orbit" icon="orbit" active={tool === "orbit"} onClick={() => setTool("orbit")} />
            <ToolButton label="Fly — WASD to move, QE up/down, drag to look" icon="fly" active={tool === "fly"} onClick={() => setTool(tool === "fly" ? "orbit" : "fly")} shortcut="G" />
            <ToolButton label="Measure" icon="ruler" active={tool === "measure"} onClick={() => { setTool(tool === "measure" ? "orbit" : "measure"); setInspector("measure"); }} shortcut="M" />
            <div className="h-px bg-line" />
            <ToolButton label="Reset view" icon="home" onClick={() => viewer.current?.home()} shortcut="H" />
            <ToolButton label="Fit to scene" icon="fit" onClick={() => viewer.current?.fit()} shortcut="F" />
            <ToolButton label="Top view" icon="plane" onClick={() => viewer.current?.preset("top")} />
            <ToolButton label="Front view" icon="image" onClick={() => viewer.current?.preset("front")} />
            <ToolButton label="Side view" icon="split" onClick={() => viewer.current?.preset("side")} />
          </div>
        )}

        {tool === "fly" && (
          <div className="pointer-events-none absolute bottom-10 left-1/2 -translate-x-1/2 border border-line bg-raised px-3 py-1 font-mono text-[11px] text-ink-2">
            Fly: W A S D to move · Q E down/up · Shift faster · drag to look · Esc to exit
          </div>
        )}
        {tool === "measure" && (
          <div className="pointer-events-none absolute bottom-10 left-1/2 -translate-x-1/2 border border-line bg-raised px-3 py-1 font-mono text-[11px] text-ink-2">
            Click two points on the point cloud{view.layer !== "points" ? " (switch to Points)" : ""}
          </div>
        )}

        {ready && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-4 border-t border-line bg-raised px-3 py-1 font-mono text-[10.5px] text-muted">
            <span className="flex items-center gap-2" aria-label="Scale bar">
              <span ref={scaleBar} className="inline-block h-[5px] border-x border-b border-ink-2" style={{ width: 80 }} />
              <span ref={scaleText} className="tabular text-ink-2">—</span>
            </span>
            <span className="hidden sm:inline">
              {view.layer === "points" ? `${formatCount(view.pointSet === "sparse" ? manifest.sparse.count : manifest.pointCloud.stats.count)} pts · conf ≥ ${view.confidence.toFixed(2)}` : view.layer === "splat" ? `${formatCount(manifest.splat?.stats.count)} splats` : `${formatCount(manifest.mesh?.diagnostics.faces)} faces`}
            </span>
            <span className="hidden md:inline">{view.projection}</span>
            {selected != null && <span>cam {selected + 1}</span>}
            {hover && tool === "measure" && <span className="tabular">x {hover.point.map((v) => v.toFixed(3)).join(" ")}</span>}
            <span className="ml-auto">{units.kind === "relative" ? "units: relative (scale unknown)" : `units: ${units.unit}, scale-estimated`}</span>
          </div>
        )}

        {compareIdx != null && ready && (
          <PhotoCompare viewer={viewer} index={compareIdx} cameras={cameras} src={src} onClose={() => setCompareIdx(null)} />
        )}

        {/* mobile sheet toggle */}
        {ready && (
          <button className="btn btn-primary absolute bottom-9 right-3 md:hidden" onClick={() => setSheetOpen(!sheetOpen)} aria-expanded={sheetOpen}>
            <Icon name="layers" size={16} /> {sheetOpen ? "Close" : "Inspect"}
          </button>
        )}
      </div>

      {/* inspector: right panel on desktop, bottom sheet on mobile */}
      {ready && (
        <aside
          aria-label="Inspector"
          className={`flex flex-col border-line bg-raised md:static md:w-[360px] md:border-l
            fixed inset-x-0 bottom-0 z-40 max-h-[72dvh] border-t shadow-lg transition-transform md:max-h-none md:translate-y-0 md:rounded-none md:shadow-none
            ${sheetOpen ? "translate-y-0" : "translate-y-full"}`}
        >
          <div className="mx-auto mt-2 h-1 w-10 bg-line-strong md:hidden" aria-hidden="true" />
          <div className="flex items-stretch gap-4 overflow-x-auto border-b border-line px-4 scroll-thin" role="tablist" aria-label="Inspector sections">
            {tabs.map(([k, l]) => (
              <button key={k} role="tab" aria-selected={inspector === k} onClick={() => setInspector(k)}
                className={`-mb-px shrink-0 border-b-2 py-2.5 text-[12.5px] ${inspector === k ? "border-ink font-medium text-ink" : "border-transparent text-muted hover:text-ink"}`}>
                {l}
              </button>
            ))}
          </div>
          {panel}
          {src?.kind === "project" && runs.length > 1 && (
            <div className="border-t border-line px-5 py-3">
              <Link className="btn btn-secondary w-full" to={`/compare?a=${projectId}:${runs[1].id}&b=${projectId}:${runId}`}>
                <Icon name="split" size={15} /> Compare with previous version
              </Link>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
