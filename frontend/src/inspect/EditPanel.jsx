import { useState } from "react";
import { Icon, Slider } from "../components/ui.jsx";
import { Section } from "./panels.jsx";
import { useStore } from "../state/store.js";

const OP_LABEL = {
  rotate: (p) => `Rotate ${p.degrees}° about ${p.axis[0] ? "X" : p.axis[1] ? "Y" : "Z"}`,
  recenter: () => "Recenter",
  alignGround: () => "Align ground plane",
  scale: (p) => `Scale ×${p.factor}`,
  scaleReference: (p) => `Set scale: ${p.actual} ${p.unit}`,
  crop: () => "Crop to box",
  removePoints: (p) => `Remove ${p.indices.length.toLocaleString()} points`,
};

/** Fit a plane to sampled visible points (RANSAC) for ground alignment. */
function fitPlane(positions, keep, n) {
  const idx = [];
  for (let i = 0; i < n && idx.length < 20000; i += Math.max(1, Math.floor(n / 20000))) if (!keep || keep[i]) idx.push(i);
  let best = null;
  let bestCount = -1;
  const P = (i) => [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]];
  let span = 0;
  for (let k = 0; k < 200; k++) {
    const a = P(idx[(Math.random() * idx.length) | 0]);
    span = Math.max(span, Math.hypot(...a));
  }
  const thr = span * 0.01;
  for (let it = 0; it < 300; it++) {
    const [a, b, c] = [0, 1, 2].map(() => P(idx[(Math.random() * idx.length) | 0]));
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const nrm = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    const l = Math.hypot(...nrm);
    if (l < 1e-12) continue;
    const nn = nrm.map((x) => x / l);
    const d = -(nn[0] * a[0] + nn[1] * a[1] + nn[2] * a[2]);
    let count = 0;
    for (let s = 0; s < idx.length; s += 4) {
      const p = P(idx[s]);
      if (Math.abs(nn[0] * p[0] + nn[1] * p[1] + nn[2] * p[2] + d) < thr) count++;
    }
    if (count > bestCount) {
      bestCount = count;
      best = { normal: nn, point: a, inliers: count / Math.ceil(idx.length / 4) };
    }
  }
  if (best && best.normal[1] < 0) best.normal = best.normal.map((x) => -x);
  return best;
}

export default function EditPanel({ manifest, points, ops, history, onPush, onUndo, onRedo, onReset, editedPositions, keepMask, saving }) {
  const b = manifest.bounds;
  const [box, setBox] = useState({ min: b.min, max: b.max });
  const [msg, setMsg] = useState(null);
  const setView = useStore((s) => s.setView);

  const center = () => {
    if (!editedPositions) return [0, 0, 0];
    const n = points.count;
    const s = [0, 0, 0];
    let c = 0;
    for (let i = 0; i < n; i += 7) {
      if (keepMask && !keepMask[i]) continue;
      s[0] += editedPositions[i * 3];
      s[1] += editedPositions[i * 3 + 1];
      s[2] += editedPositions[i * 3 + 2];
      c++;
    }
    return s.map((v) => v / Math.max(1, c));
  };

  const axisSlider = (k, label) => {
    const lo = b.min[k] - b.radius * 0.5,
      hi = b.max[k] + b.radius * 0.5;
    return (
      <div className="grid grid-cols-2 gap-3" key={k}>
        <Slider label={`${label} min`} value={box.min[k]} min={lo} max={hi} step={(hi - lo) / 200} onChange={(v) => setBox((s) => ({ ...s, min: s.min.map((x, i) => (i === k ? v : x)) }))} format={(v) => v.toFixed(2)} />
        <Slider label={`${label} max`} value={box.max[k]} min={lo} max={hi} step={(hi - lo) / 200} onChange={(v) => setBox((s) => ({ ...s, max: s.max.map((x, i) => (i === k ? v : x)) }))} format={(v) => v.toFixed(2)} />
      </div>
    );
  };

  return (
    <>
      <Section>
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary" onClick={onUndo} disabled={!history.canUndo} aria-label="Undo" title="Undo (⌘Z)">
            <Icon name="undo" size={15} /> Undo
          </button>
          <button className="btn btn-secondary" onClick={onRedo} disabled={!history.canRedo} aria-label="Redo" title="Redo (⇧⌘Z)">
            <Icon name="redo" size={15} /> Redo
          </button>
          <button className="btn btn-ghost ml-auto" onClick={onReset} disabled={!ops.length}>Revert all</button>
        </div>
        <p className="text-[12px] text-muted">
          Edits are stored separately. The original reconstruction is never changed{saving ? " · saving…" : ""}.
        </p>
      </Section>
      <Section title="Orientation">
        <div className="grid grid-cols-3 gap-1.5">
          {[["X", [1, 0, 0]], ["Y", [0, 1, 0]], ["Z", [0, 0, 1]]].map(([l, axis]) => (
            <button key={l} className="btn btn-secondary" onClick={() => onPush({ type: "rotate", params: { axis, degrees: 90 } })}>
              Rotate {l} 90°
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <button className="btn btn-secondary" onClick={() => onPush({ type: "recenter", params: { center: center() } })}>
            <Icon name="fit" size={15} /> Recenter
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => {
              const plane = fitPlane(editedPositions, keepMask, points.count);
              if (!plane || plane.inliers < 0.12) return setMsg("No clear ground plane found. Try cropping to the floor first.");
              onPush({ type: "alignGround", params: { normal: plane.normal, point: plane.point } });
              setMsg(`Aligned to a plane covering ${(plane.inliers * 100).toFixed(0)}% of sampled points.`);
            }}
          >
            <Icon name="plane" size={15} /> Align ground
          </button>
        </div>
        {msg && <p className="text-[12px] text-muted">{msg}</p>}
      </Section>
      <Section title="Crop" hint="Keep only points inside this box (in the current, edited frame). Applies to points and exports; the splat and mesh are not cut.">
        {axisSlider(0, "X")}
        {axisSlider(1, "Y")}
        {axisSlider(2, "Z")}
        <div className="flex gap-2">
          <button className="btn btn-primary flex-1" onClick={() => { onPush({ type: "crop", params: box }); setView({ showBounds: false }); }}>
            <Icon name="crop" size={15} /> Apply crop
          </button>
          <button className="btn btn-ghost" onClick={() => setBox({ min: b.min, max: b.max })}>Reset box</button>
        </div>
      </Section>
      <Section title="Clean up" hint="Remove points below the confidence slider in View. Stored as an explicit list, so it can be undone.">
        <button
          className="btn btn-secondary w-full"
          onClick={() => {
            if (!points.confidence) return;
            const thr = Math.round(useStore.getState().view.confidence * 255);
            const idx = [];
            for (let i = 0; i < points.count; i++) if (points.confidence[i] < thr && (!keepMask || keepMask[i])) idx.push(i);
            if (idx.length) onPush({ type: "removePoints", params: { indices: idx } });
            setMsg(idx.length ? `Removed ${idx.length.toLocaleString()} low-confidence points.` : "Nothing below the current confidence threshold.");
          }}
        >
          <Icon name="trash" size={15} /> Remove low-confidence points
        </button>
      </Section>
      <Section title={`History · ${ops.length}`}>
        {ops.length ? (
          <ol className="space-y-1 text-[12.5px]">
            {ops.map((o, i) => (
              <li key={o.id || i} className="flex justify-between gap-2">
                <span className="text-ink-2">{(OP_LABEL[o.type] || (() => o.type))(o.params)}</span>
                <span className="font-mono text-faint">{i + 1}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-[12.5px] text-muted">No edits yet.</p>
        )}
      </Section>
    </>
  );
}
