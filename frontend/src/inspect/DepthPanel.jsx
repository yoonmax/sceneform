import { useEffect, useRef, useState } from "react";
import { decodeDepth, loadDepth } from "../lib/scene.js";
import { TURBO_LUT } from "../lib/colormap.js";
import { Seg, Slider } from "../components/ui.jsx";
import { Section } from "./panels.jsx";
import { useStore } from "../state/store.js";

/** Depth & confidence inspection for one view, with robust near/far controls. */
export default function DepthPanel({ manifest, cameras, src, units }) {
  const selected = useStore((s) => s.selectedCamera);
  const select = useStore((s) => s.selectCamera);
  const frames = manifest.frames.filter((f) => f.depth);
  const [idx, setIdx] = useState(selected ?? frames[0]?.index ?? 0);
  const [data, setData] = useState(null);
  const [show, setShow] = useState("depth");
  const [range, setRange] = useState([0, 1]);
  const [hover, setHover] = useState(null);
  const [error, setError] = useState(null);
  const canvas = useRef();
  const frame = manifest.frames[idx];

  useEffect(() => {
    if (selected != null && manifest.frames[selected]?.depth) setIdx(selected);
  }, [selected, manifest]);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    if (!frame?.depth) return;
    loadDepth(src, frame.depth)
      .then((d) => {
        if (!live) return;
        // Robust default range: 2nd–98th percentile of valid depth.
        const vals = [];
        for (let i = 0; i < d.depth.length; i += 7) if (d.depth[i] !== d.invalid) vals.push(d.depth[i]);
        vals.sort((a, b) => a - b);
        const lo = vals.length ? decodeDepth(d, vals[Math.floor(vals.length * 0.02)]) : d.near;
        const hi = vals.length ? decodeDepth(d, vals[Math.floor(vals.length * 0.98)]) : d.far;
        setRange([lo, hi]);
        setData(d);
      })
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [frame, src]);

  useEffect(() => {
    const c = canvas.current;
    if (!c || !data) return;
    const { width: w, height: h } = data;
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d");
    const img = ctx.createImageData(w, h);
    const [lo, hi] = range;
    for (let i = 0; i < w * h; i++) {
      let t = null;
      if (show === "depth") {
        const z = decodeDepth(data, data.depth[i]);
        if (z != null) t = 1 - (z - lo) / Math.max(hi - lo, 1e-9);
      } else if (data.conf) {
        t = data.depth[i] === data.invalid ? null : data.conf[i] / 255;
      }
      if (t == null) {
        img.data[i * 4 + 3] = 0;
        continue;
      }
      const k = Math.max(0, Math.min(255, Math.round(t * 255))) * 4;
      img.data[i * 4] = TURBO_LUT[k];
      img.data[i * 4 + 1] = TURBO_LUT[k + 1];
      img.data[i * 4 + 2] = TURBO_LUT[k + 2];
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }, [data, range, show]);

  if (!frames.length) return <Section><p className="text-[13px] text-muted">No depth maps are available for this scene.</p></Section>;
  const hist = frame?.depth?.histogram || [];
  const maxH = Math.max(...hist, 1);
  const u = units.kind === "relative" ? "units" : units.unit;

  return (
    <>
      <Section title="View">
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary btn-icon" onClick={() => { const i = frames.findIndex((f) => f.index === idx); const n = frames[(i - 1 + frames.length) % frames.length].index; setIdx(n); select(n); }} aria-label="Previous view">‹</button>
          <div className="flex-1 text-center font-mono text-[12.5px] tabular">view {idx + 1} of {manifest.frames.length}</div>
          <button className="btn btn-secondary btn-icon" onClick={() => { const i = frames.findIndex((f) => f.index === idx); const n = frames[(i + 1) % frames.length].index; setIdx(n); select(n); }} aria-label="Next view">›</button>
        </div>
        <Seg label="Map" value={show} onChange={setShow} options={[{ value: "depth", label: "Depth" }, { value: "confidence", label: "Confidence", disabled: !data?.conf }]} />
        <div className="grid grid-cols-2 gap-1.5">
          <img src={src.url(frame.frame)} alt={`Source photo ${idx + 1}`} className="w-full rounded-[2px] border border-line" />
          <div className="relative">
            {!data && !error && <div className="aspect-[4/3] skeleton rounded-[2px]" />}
            {error && <p className="text-[12px] text-bad">{error}</p>}
            <canvas
              ref={canvas}
              className={`w-full rounded-[2px] border border-line bg-surface [image-rendering:pixelated] ${data ? "" : "hidden"}`}
              aria-label={`${show} map for view ${idx + 1}`}
              onMouseMove={(e) => {
                if (!data) return;
                const r = e.currentTarget.getBoundingClientRect();
                const x = Math.floor(((e.clientX - r.left) / r.width) * data.width);
                const y = Math.floor(((e.clientY - r.top) / r.height) * data.height);
                const i = y * data.width + x;
                setHover({ z: decodeDepth(data, data.depth[i]), c: data.conf ? data.conf[i] / 255 : null });
              }}
              onMouseLeave={() => setHover(null)}
            />
          </div>
        </div>
        <p className="min-h-[1.1rem] font-mono text-[12px] tabular text-muted">
          {hover ? (hover.z == null ? "no depth here (filtered or unsupported)" : `depth ≈ ${hover.z.toFixed(3)} ${u}${hover.c != null ? ` · confidence ${hover.c.toFixed(2)}` : ""}`) : "Hover the map to read depth."}
        </p>
      </Section>
      {show === "depth" && data && (
        <Section title="Near / far" hint="Colors are stretched between these depths. Defaults ignore the nearest and farthest 2% of pixels.">
          <div className="flex h-12 items-end gap-px" role="img" aria-label="Depth histogram">
            {hist.map((v, i) => <div key={i} className="flex-1 bg-ink-2/70" style={{ height: `${(v / maxH) * 100}%` }} />)}
          </div>
          <Slider label="Near" value={range[0]} min={data.near} max={range[1]} step={(data.far - data.near) / 200} onChange={(v) => setRange([v, range[1]])} format={(v) => v.toFixed(3)} />
          <Slider label="Far" value={range[1]} min={range[0]} max={data.far} step={(data.far - data.near) / 200} onChange={(v) => setRange([range[0], v])} format={(v) => v.toFixed(3)} />
        </Section>
      )}
      {frame.depth.alignment && (
        <Section title="How this depth was made" hint="Monocular depth has no scale; it is fitted to the SfM points seen in this view, then locally corrected.">
          <dl className="grid grid-cols-2 gap-y-1 text-[12.5px]">
            <dt className="text-muted">SfM points used</dt><dd className="text-right font-mono tabular">{frame.depth.alignment.inliers} / {frame.depth.alignment.sparsePoints}</dd>
            <dt className="text-muted">Error, global fit</dt><dd className="text-right font-mono tabular">{(frame.depth.alignment.medianRelErrorGlobal * 100).toFixed(2)}%</dd>
            <dt className="text-muted">Error, after local fix</dt><dd className="text-right font-mono tabular">{(frame.depth.alignment.medianRelErrorLocal * 100).toFixed(2)}%</dd>
          </dl>
          <p className="text-[12px] text-muted">Depth is in {units.kind === "relative" ? "relative scene units, not meters" : `${units.unit}, scale-estimated`}.</p>
        </Section>
      )}
    </>
  );
}
