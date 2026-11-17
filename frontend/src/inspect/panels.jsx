import { useMemo, useState } from "react";
import { Icon, InfoTip, Seg, Slider, Stat, Toggle } from "../components/ui.jsx";
import QualityReport from "../components/QualityReport.jsx";
import { useStore } from "../state/store.js";
import { formatBytes, formatCount, formatDuration } from "../lib/scene.js";

export function Section({ title, children, hint, action }) {
  return (
    <section className="space-y-3 border-b border-line px-5 py-4 last:border-0">
      {title && (
        <div className="flex items-center justify-between">
          <h3 className="label flex items-center gap-1.5">
            {title} {hint && <InfoTip text={hint} />}
          </h3>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function OverviewPanel({ manifest, units }) {
  const m = manifest.metrics;
  const lic = manifest.license;
  return (
    <>
      <Section>
        <p className="text-[13.5px] leading-relaxed text-ink-2">
          {manifest.summary || `Reconstructed from ${manifest.source.type === "video" ? "a video" : `${m.inputFrames} photos`}.`}
        </p>
        <table className="table-paper">
          <thead>
            <tr>
              <th>Quantity</th>
              <th className="num">Value</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>Views registered</td><td className="num">{m.registeredViews} / {m.inputFrames}</td></tr>
            <tr><td>Reprojection error (mean)</td><td className="num">{m.sparseReprojectionErrorPx.mean?.toFixed(3)} px</td></tr>
            <tr><td>Sparse points</td><td className="num">{formatCount(m.sparsePoints)}</td></tr>
            <tr><td>Dense points (filtered)</td><td className="num">{formatCount(manifest.pointCloud.stats.count)}</td></tr>
            {manifest.splat && <tr><td>Gaussian splats</td><td className="num">{formatCount(manifest.splat.stats.count)}</td></tr>}
            {manifest.mesh && <tr><td>Mesh faces</td><td className="num">{formatCount(manifest.mesh.diagnostics.faces)}</td></tr>}
            <tr><td>Azimuthal coverage</td><td className="num">{m.coverageDeg.toFixed(0)}°</td></tr>
            <tr><td>Processing time</td><td className="num">{formatDuration(manifest.processing.totalSeconds)}</td></tr>
          </tbody>
        </table>
        <p className="caption">Mode: {manifest.mode === "high" ? "high quality (with splat)" : "fast preview"}. Error is measured in pixels of the undistorted working images.</p>
      </Section>
      <Section title="Units" hint="SfM recovers shape up to an unknown scale. Distances are relative unless you set a reference length in Measure.">
        <p className="text-[13px] text-ink-2">
          {units.kind === "relative"
            ? "Relative units — the scene’s true size is unknown. Set a known distance in Measure to estimate real-world scale."
            : `Scale-estimated (${units.unit}) from your reference measurement. Accuracy depends on how precisely you picked the points.`}
        </p>
      </Section>
      <Section title="What you’re looking at">
        <ul className="space-y-1.5 text-[13px] text-ink-2">
          <li><b className="font-medium">Points</b> — depth estimated per photo, kept only where several cameras agree.</li>
          {manifest.splat && <li><b className="font-medium">Splat</b> — a trained Gaussian-splat model for realistic viewing.</li>}
          {manifest.mesh && <li><b className="font-medium">Mesh</b> — an approximate surface. Unseen sides stay open.</li>}
          <li><b className="font-medium">Cameras</b> — where each photo was taken, as estimated from the images alone.</li>
        </ul>
      </Section>
      <Section title="Input quality">
        <QualityReport report={manifest.quality} compact />
      </Section>
      {lic && (
        <Section title="Source & license">
          <p className="text-[12.5px] leading-relaxed text-muted">
            {lic.attribution}.{" "}
            <a href={lic.url} target="_blank" rel="noopener noreferrer" className="underline">{lic.name}</a>
            {" · "}
            <a href={lic.source} target="_blank" rel="noopener noreferrer" className="underline">source</a>
          </p>
          {lic.note && <p className="text-[12.5px] text-muted">{lic.note}</p>}
        </Section>
      )}
    </>
  );
}

export function ViewPanel({ manifest, layerStatus }) {
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const renderQuality = useStore((s) => s.renderQuality);
  const setPref = useStore((s) => s.setPref);
  const advanced = useStore((s) => s.expertise === "advanced");
  const showsPoints = view.layer === "points";
  return (
    <>
      <Section title="Representation">
        <Seg
          label="Representation"
          value={view.layer}
          onChange={(v) => setView({ layer: v, projection: v === "splat" ? "perspective" : view.projection })}
          options={[
            { value: "points", label: "Points" },
            { value: "splat", label: "Splat", disabled: !manifest.splat, disabledReason: "No trained splat for this scene (fast preview)" },
            { value: "mesh", label: "Mesh", disabled: !manifest.mesh, disabledReason: "No mesh was built for this scene" },
          ]}
        />
        {view.layer === "splat" && layerStatus.splat && !layerStatus.splat.ready && !layerStatus.splat.error && (
          <p className="text-[12.5px] text-muted">Loading splat… {layerStatus.splat.progress ? `${Math.round(layerStatus.splat.progress * 100)}%` : ""}</p>
        )}
        {layerStatus.splat?.error && view.layer === "splat" && (
          <p className="text-[12.5px] text-bad">The splat couldn’t be displayed on this device ({layerStatus.splat.error}). Showing points is a lighter alternative.</p>
        )}
        {view.layer === "splat" && <p className="text-[12px] text-muted">Gaussian splats are a rendering representation — great for looking, not a measured surface.</p>}
      </Section>
      {showsPoints && (
        <Section title="Points">
          <Seg label="Point set" value={view.pointSet} onChange={(v) => setView({ pointSet: v })}
            options={[{ value: "dense", label: "Dense" }, { value: "sparse", label: "Sparse (SfM)" }]} />
          <div className="space-y-1.5">
            <div className="text-[12.5px] text-ink-2">Color</div>
            <div className="flex flex-wrap gap-1.5">
              {[["rgb", "Photo color"], ["white", "Plain"], ["confidence", "Confidence"], ["depth", "Depth"], ["density", "Density"]].map(([k, l]) => (
                <button key={k} className={`chip ${view.colorMode === k ? "border-ink text-ink" : ""}`} aria-pressed={view.colorMode === k} onClick={() => setView({ colorMode: k })}>
                  {l}
                </button>
              ))}
            </div>
            {view.colorMode !== "rgb" && view.colorMode !== "white" && (
              <div className="flex items-center gap-2 text-[11px] text-muted">
                <span>{view.colorMode === "depth" ? "near" : "low"}</span>
                <span className="h-1.5 flex-1 rounded" style={{ background: "linear-gradient(90deg,#30123b,#4686fb,#1ae4b6,#a2fc3c,#f9ba38,#e4460a,#7a0403)" }} />
                <span>{view.colorMode === "depth" ? "far" : "high"}</span>
              </div>
            )}
          </div>
          <Slider label="Point size" value={view.pointSize} min={0.3} max={6} step={0.1} onChange={(v) => setView({ pointSize: v })} format={(v) => v.toFixed(1)} />
          {view.pointSet === "dense" && (
            <Slider label="Minimum confidence" value={view.confidence} min={0} max={1} step={0.05} onChange={(v) => setView({ confidence: v })} format={(v) => v.toFixed(2)}
              hint="Confidence = fraction of neighbouring cameras whose depth agrees with the point. It measures consistency, not real-world accuracy." />
          )}
          <Slider label="Brightness" value={view.exposure} min={0.4} max={2} step={0.05} onChange={(v) => setView({ exposure: v })} format={(v) => `${v.toFixed(2)}×`} />
        </Section>
      )}
      <Section title="Scene">
        <Toggle label="Camera positions" checked={view.showCameras} onChange={(v) => setView({ showCameras: v })} />
        <Toggle label="Capture path" checked={view.showPath} onChange={(v) => setView({ showPath: v })} />
        <Toggle label="Ground grid" checked={view.showGrid} onChange={(v) => setView({ showGrid: v })} />
        <Toggle label="Axis gizmo" checked={view.showAxes} onChange={(v) => setView({ showAxes: v })} />
        <Toggle label="Bounding box" checked={view.showBounds} onChange={(v) => setView({ showBounds: v })} />
        <div className="flex items-center justify-between pt-1">
          <span className="text-[13px] text-ink-2">Background</span>
          <Seg label="Background" value={view.background} onChange={(v) => setView({ background: v })}
            options={[{ value: "studio", label: "Studio" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[13px] text-ink-2">Projection {view.layer === "splat" && <InfoTip text="Orthographic view isn't supported for splats." />}</span>
          <Seg label="Projection" value={view.projection} onChange={(v) => setView({ projection: v })}
            options={[{ value: "perspective", label: "Perspective" }, { value: "orthographic", label: "Ortho", disabled: view.layer === "splat" }]} />
        </div>
      </Section>
      {advanced && (
        <Section title="Rendering" hint="Lower settings reduce resolution to stay smooth on slower devices.">
          <Seg label="Render quality" value={renderQuality} onChange={(v) => setPref("renderQuality", v)}
            options={[{ value: "performance", label: "Performance" }, { value: "balanced", label: "Balanced" }, { value: "quality", label: "Quality" }]} />
        </Section>
      )}
    </>
  );
}

export function CamerasPanel({ cameras, src, viewer, onCompare }) {
  const selected = useStore((s) => s.selectedCamera);
  const select = useStore((s) => s.selectCamera);
  const replaying = useStore((s) => s.replaying);
  const advanced = useStore((s) => s.expertise === "advanced");
  const cam = selected != null ? cameras.cameras[selected] : null;
  const ordered = useMemo(() => [...cameras.cameras].sort((a, b) => (a.captureIndex ?? a.index) - (b.captureIndex ?? b.index)), [cameras]);
  return (
    <>
      <Section>
        <div className="flex gap-2">
          {replaying ? (
            <button className="btn btn-secondary flex-1" onClick={() => viewer.current?.stopReplay()}>
              <Icon name="stop" size={15} /> Stop replay
            </button>
          ) : (
            <button className="btn btn-secondary flex-1" onClick={() => viewer.current?.replay()}>
              <Icon name="play" size={15} /> Replay capture path
            </button>
          )}
        </div>
      </Section>
      {cam && (
        <Section title={`Camera ${selected + 1}`} action={<button className="btn btn-ghost h-7 px-2 text-[12px]" onClick={() => select(null)}>Clear</button>}>
          <img src={src.url(cam.frame)} alt={`Source photo for camera ${selected + 1}`} className="w-full rounded-[2px] border border-line" />
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary" onClick={() => viewer.current?.goToCamera(selected)}>
              <Icon name="camera" size={15} /> View from here
            </button>
            <button className="btn btn-secondary" onClick={() => onCompare(selected)}>
              <Icon name="split" size={15} /> Compare with photo
            </button>
          </div>
          <dl className="grid grid-cols-2 gap-y-1 text-[12.5px]">
            <dt className="text-muted">Capture order</dt>
            <dd className="text-right font-mono tabular">{(cam.captureIndex ?? cam.index) + 1}</dd>
            {cam.timestamp != null && (
              <>
                <dt className="text-muted">Video time</dt>
                <dd className="text-right font-mono tabular">{cam.timestamp.toFixed(2)} s</dd>
              </>
            )}
            <dt className="text-muted">Field of view</dt>
            <dd className="text-right font-mono tabular">{cam.intrinsics.fovYDeg.toFixed(1)}° vertical</dd>
            <dt className="text-muted">Reprojection</dt>
            <dd className="text-right font-mono tabular">{cam.reprojectionErrorPx ? `${cam.reprojectionErrorPx.mean.toFixed(2)} px (${cam.reprojectionErrorPx.observations} pts)` : "—"}</dd>
          </dl>
          {advanced && (
            <details className="text-[12px]">
              <summary className="cursor-pointer text-muted hover:text-ink">Intrinsics & extrinsics</summary>
              <pre className="mt-2 overflow-x-auto rounded-[2px] bg-surface p-3 font-mono text-[11px] leading-relaxed">
{`K (pinhole, ${cam.width}×${cam.height})
fx ${cam.intrinsics.fx.toFixed(2)}  fy ${cam.intrinsics.fy.toFixed(2)}
cx ${cam.intrinsics.cx.toFixed(2)}  cy ${cam.intrinsics.cy.toFixed(2)}

R (world→camera, OpenCV: x right, y down, z forward)
${cam.extrinsics.R.map((r) => r.map((v) => v.toFixed(5).padStart(9)).join(" ")).join("\n")}
t ${cam.extrinsics.t.map((v) => v.toFixed(4)).join("  ")}
center ${cam.center.map((v) => v.toFixed(4)).join("  ")}`}
              </pre>
            </details>
          )}
        </Section>
      )}
      <Section title={`${ordered.length} cameras`} hint="Click a thumbnail or a camera in the scene.">
        <ul className="grid grid-cols-4 gap-1.5">
          {ordered.map((c) => (
            <li key={c.index}>
              <button
                onClick={() => select(c.index)}
                className={`block w-full overflow-hidden rounded-[2px] border ${selected === c.index ? "border-accent ring-1 ring-accent" : "border-line"}`}
                aria-label={`Select camera ${c.index + 1}`}
                aria-pressed={selected === c.index}
              >
                <img src={src.url(c.thumb)} alt="" loading="lazy" className="aspect-[4/3] w-full object-cover" />
              </button>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

export function MeasurePanel({ units, onScaleReference }) {
  const tool = useStore((s) => s.tool);
  const setTool = useStore((s) => s.setTool);
  const pts = useStore((s) => s.measurePoints);
  const clear = useStore((s) => s.clearMeasure);
  const hover = useStore((s) => s.hoverPoint);
  const [actual, setActual] = useState("");
  const [unit, setUnit] = useState("m");
  const dist = pts.length === 2 ? Math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1], pts[0][2] - pts[1][2]) : null;
  const label = units.kind === "relative" ? "units (relative)" : `${units.unit} (scale-estimated)`;
  return (
    <>
      <Section>
        <button className={`btn w-full ${tool === "measure" ? "btn-primary" : "btn-secondary"}`} onClick={() => setTool(tool === "measure" ? "orbit" : "measure")} aria-pressed={tool === "measure"}>
          <Icon name="ruler" size={15} /> {tool === "measure" ? "Measuring — click two points" : "Start measuring"}
        </button>
        <p className="text-[12.5px] text-muted">Works on the point cloud. Click a point, then a second one.</p>
      </Section>
      <Section title="Selection">
        {pts.map((p, i) => (
          <div key={i} className="flex justify-between font-mono text-[12px] tabular">
            <span className="text-muted">{i === 0 ? "A" : "B"}</span>
            <span>{p.map((v) => v.toFixed(3)).join(", ")}</span>
          </div>
        ))}
        {hover && tool === "measure" && (
          <div className="flex justify-between font-mono text-[12px] tabular text-faint">
            <span>cursor</span>
            <span>{hover.point.map((v) => v.toFixed(3)).join(", ")}</span>
          </div>
        )}
        {dist != null && (
          <div className="rounded-[2px] bg-surface p-3">
            <div className="label">Distance</div>
            <div className="mt-1 font-mono text-xl tabular">{dist.toFixed(4)} <span className="text-[12px] text-muted">{label}</span></div>
            {units.kind === "relative" && <p className="mt-1 text-[12px] text-muted">The true scale is unknown, so this isn’t in meters yet.</p>}
          </div>
        )}
        {pts.length > 0 && <button className="btn btn-ghost -ml-2" onClick={clear}>Clear points</button>}
      </Section>
      {dist != null && (
        <Section title="Set real-world scale" hint="If you know the true length between A and B, sceneform rescales the scene so measurements are approximately in real units.">
          <div className="flex gap-2">
            <input className="field font-mono" inputMode="decimal" placeholder="Known length" value={actual} onChange={(e) => setActual(e.target.value)} aria-label="Known length between A and B" />
            <select className="field w-24" value={unit} onChange={(e) => setUnit(e.target.value)} aria-label="Unit">
              {["m", "cm", "mm", "in", "ft"].map((u) => <option key={u}>{u}</option>)}
            </select>
          </div>
          <button className="btn btn-secondary w-full" disabled={!(Number(actual) > 0)} onClick={() => { onScaleReference(dist, Number(actual), unit); setActual(""); clear(); }}>
            Apply scale
          </button>
          <p className="text-[12px] text-muted">Results are labelled “scale-estimated”: accuracy depends on point picking and reconstruction quality. No uncertainty is claimed.</p>
        </Section>
      )}
    </>
  );
}

export function DiagnosticsPanel({ manifest, cameras }) {
  const m = manifest.metrics;
  const conf = manifest.pointCloud.stats.confidenceHistogram;
  const maxC = Math.max(...conf, 1);
  const errs = cameras.cameras.map((c) => c.reprojectionErrorPx?.mean ?? 0);
  const maxE = Math.max(...errs, 0.01);
  const h = m.splatHeldout;
  return (
    <>
      <Section title="Camera registration">
        <div className="grid grid-cols-2 gap-4">
          <Stat label="Registered" value={`${(m.registrationRatio * 100).toFixed(0)}%`} sub={`${m.registeredViews} of ${m.inputFrames}`} />
          <Stat label="Track length" value={m.meanTrackLength?.toFixed(2)} sub="views per sparse point" />
          <Stat label="Median reproj." value={`${m.sparseReprojectionErrorPx.median?.toFixed(2)} px`} sub={`p90 ${m.sparseReprojectionErrorPx.p90?.toFixed(2)} px`} />
          <Stat label="Coverage" value={`${m.coverageDeg.toFixed(0)}°`} sub="azimuth around subject" />
        </div>
        <div>
          <div className="mb-1 text-[12px] text-muted">Mean reprojection error per camera (px)</div>
          <div className="flex h-16 items-end gap-px" role="img" aria-label={`Per-camera reprojection error, max ${maxE.toFixed(2)} px`}>
            {errs.map((e, i) => <div key={i} className="flex-1 bg-ink-2" style={{ height: `${(e / maxE) * 100}%` }} title={`camera ${i + 1}: ${e.toFixed(2)} px`} />)}
          </div>
        </div>
        {m.cameraValidation?.warnings?.length > 0 && <p className="text-[12px] text-warn">{m.cameraValidation.warnings.join(" · ")}</p>}
      </Section>
      <Section title="Depth fusion" hint="Per-view monocular depth is aligned to SfM points; agreement across cameras becomes confidence.">
        <div className="grid grid-cols-2 gap-4">
          <Stat label="Views fused" value={`${m.depthFusion.views_fused}`} sub={`${m.depthFusion.views_skipped} skipped`} />
          <Stat label="Alignment error" value={`${((m.depthFusion.median_alignment_rel_error || 0) * 100).toFixed(2)}%`} sub="median, vs SfM depth" />
        </div>
        <div>
          <div className="mb-1 text-[12px] text-muted">Confidence distribution (shipped points)</div>
          <div className="flex h-14 items-end gap-px" role="img" aria-label="Confidence histogram">
            {conf.map((c, i) => <div key={i} className="flex-1 bg-ink-2" style={{ height: `${(c / maxC) * 100}%` }} title={`${(i / conf.length).toFixed(2)}–${((i + 1) / conf.length).toFixed(2)}: ${c}`} />)}
          </div>
          <div className="mt-0.5 flex justify-between font-mono text-[10px] text-faint"><span>0</span><span>1</span></div>
        </div>
        <ul className="space-y-0.5 font-mono text-[11.5px] text-muted">
          {manifest.pointCloud.stats.filtering.map((f, i) => (
            <li key={i} className="flex justify-between gap-2"><span className="truncate">{f.step}</span><span className="tabular">{f.after?.toLocaleString()}</span></li>
          ))}
        </ul>
      </Section>
      {manifest.mesh && (
        <Section title="Mesh">
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Faces" value={formatCount(manifest.mesh.diagnostics.faces)} />
            <Stat label="Components" value={manifest.mesh.diagnostics.components} />
            <Stat label="Watertight" value={manifest.mesh.diagnostics.watertight ? "yes" : "no"} sub={`${manifest.mesh.diagnostics.boundary_edges.toLocaleString()} open edges`} />
            <Stat label="Voxel" value={manifest.mesh.diagnostics.voxel_size.toFixed(4)} sub="units" />
          </div>
        </Section>
      )}
      {manifest.splat && (
        <Section title="Gaussian splat" hint="Held-out views are photos the trainer never saw. Scores cover the full frame, including blurry backgrounds, so they can be low even when the subject looks good.">
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Trainer" value={manifest.splat.training.trainer} sub={`${manifest.splat.training.device}, ${manifest.splat.training.iterations.toLocaleString()} steps`} />
            <Stat label="Splats" value={formatCount(manifest.splat.stats.count)} sub={formatBytes(manifest.splat.pruning.bytes)} />
            {h?.psnr != null && <Stat label="Held-out PSNR" value={`${h.psnr.toFixed(2)} dB`} sub={`${h.num_test} views`} />}
            {h?.ssim != null && <Stat label="Held-out SSIM" value={h.ssim.toFixed(3)} />}
          </div>
        </Section>
      )}
      <Section title="Pipeline">
        <ul className="space-y-1 text-[12px] text-muted">
          <li>SfM: {manifest.processing.sfm}</li>
          <li>Depth: {manifest.processing.depth}</li>
          {manifest.processing.splat && <li>Splat: {manifest.processing.splat}</li>}
          <li className="font-mono text-[11px]">{Object.entries(manifest.processing.versions || {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</li>
        </ul>
        <ul className="space-y-0.5 font-mono text-[11.5px] text-muted">
          {Object.entries(manifest.processing.stageSeconds || {}).map(([k, v]) => (
            <li key={k} className="flex justify-between"><span>{k.replaceAll("_", " ")}</span><span className="tabular">{v.toFixed(1)} s</span></li>
          ))}
        </ul>
      </Section>
    </>
  );
}
