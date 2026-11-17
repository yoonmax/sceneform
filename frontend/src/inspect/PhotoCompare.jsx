import { useEffect, useRef, useState } from "react";
import { Icon, Seg, Slider } from "../components/ui.jsx";
import { TURBO_LUT } from "../lib/colormap.js";
import { useStore } from "../state/store.js";

/**
 * Source photo vs. the reconstruction rendered from the *estimated* pose of
 * that photo. The difference view is an appearance difference over pixels
 * the reconstruction covers — not a calibrated geometric error.
 */
export default function PhotoCompare({ viewer, index, cameras, src, onClose }) {
  const layer = useStore((s) => s.view.layer);
  const [mode, setMode] = useState("split");
  const [split, setSplit] = useState(0.5);
  const [opacity, setOpacity] = useState(0.5);
  const [stats, setStats] = useState(null);
  const [photoUrl, setPhotoUrl] = useState(null);
  const [renderUrl, setRenderUrl] = useState(null);
  const [diffUrl, setDiffUrl] = useState(null);
  const [error, setError] = useState(null);
  const [aspect, setAspect] = useState(4 / 3);
  const wrap = useRef();
  const cam = cameras.cameras[index];

  useEffect(() => {
    let live = true;
    setRenderUrl(null);
    setDiffUrl(null);
    setStats(null);
    setError(null);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (!live) return;
      const w = img.naturalWidth,
        h = img.naturalHeight;
      setAspect(w / h);
      setPhotoUrl(img.src);
      // Give the splat a moment to finish sorting for this pose.
      setTimeout(() => {
        try {
          const rendered = viewer.current.capture(index, w, h);
          const c = document.createElement("canvas");
          c.width = w;
          c.height = h;
          const ctx = c.getContext("2d");
          ctx.putImageData(rendered, 0, 0);
          const out = c.toDataURL("image/png");
          // Photo pixels
          ctx.clearRect(0, 0, w, h);
          ctx.drawImage(img, 0, 0, w, h);
          const photo = ctx.getImageData(0, 0, w, h).data;
          const diff = ctx.createImageData(w, h);
          let sum = 0,
            covered = 0;
          for (let i = 0; i < w * h; i++) {
            const a = rendered.data[i * 4 + 3];
            if (a < 200) continue;
            covered++;
            const d = (Math.abs(rendered.data[i * 4] - photo[i * 4]) + Math.abs(rendered.data[i * 4 + 1] - photo[i * 4 + 1]) + Math.abs(rendered.data[i * 4 + 2] - photo[i * 4 + 2])) / 3;
            sum += d;
            const k = Math.min(255, Math.round(d * 2)) * 4;
            diff.data[i * 4] = TURBO_LUT[k];
            diff.data[i * 4 + 1] = TURBO_LUT[k + 1];
            diff.data[i * 4 + 2] = TURBO_LUT[k + 2];
            diff.data[i * 4 + 3] = 255;
          }
          ctx.clearRect(0, 0, w, h);
          ctx.putImageData(diff, 0, 0);
          if (!live) return;
          setRenderUrl(out);
          setDiffUrl(c.toDataURL("image/png"));
          setStats({ coverage: covered / (w * h), mad: covered ? sum / covered : null });
        } catch (e) {
          setError(`The reconstruction couldn’t be rendered from this camera (${e.message}).`);
        }
      }, layer === "splat" ? 450 : 60);
    };
    img.onerror = () => live && setError("The source photo couldn’t be loaded.");
    img.src = src.url(cam.frame);
    return () => {
      live = false;
    };
  }, [index, cam, src, viewer, layer]);

  const dragSplit = (e) => {
    const r = wrap.current.getBoundingClientRect();
    setSplit(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)));
  };

  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-bg/95" role="dialog" aria-label={`Compare camera ${index + 1} with its photo`}>
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5">
        <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close comparison">
          <Icon name="close" />
        </button>
        <div className="text-[13.5px] font-medium">Camera {index + 1} · photo vs. reconstruction ({layer})</div>
        <div className="ml-auto">
          <Seg label="Comparison mode" value={mode} onChange={setMode}
            options={[{ value: "original", label: "Photo" }, { value: "reconstruction", label: "Reconstruction" }, { value: "split", label: "Split" }, { value: "overlay", label: "Overlay" }, { value: "difference", label: "Difference" }]} />
        </div>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center p-4">
        {error ? (
          <p className="text-bad">{error}</p>
        ) : (
          <div
            ref={wrap}
            className="relative max-h-full w-full max-w-5xl overflow-hidden rounded-[2px] border border-line bg-[repeating-conic-gradient(var(--surface)_0_25%,var(--raised)_0_50%)] [background-size:16px_16px]"
            style={{ aspectRatio: aspect }}
            onPointerDown={(e) => mode === "split" && (e.currentTarget.setPointerCapture(e.pointerId), dragSplit(e))}
            onPointerMove={(e) => mode === "split" && e.buttons && dragSplit(e)}
          >
            {photoUrl && (mode === "original" || mode === "split" || mode === "overlay") && <img src={photoUrl} alt="Source photo" className="absolute inset-0 h-full w-full" />}
            {renderUrl && mode === "reconstruction" && <img src={renderUrl} alt="Reconstruction rendered from the estimated camera" className="absolute inset-0 h-full w-full" />}
            {renderUrl && mode === "overlay" && <img src={renderUrl} alt="" className="absolute inset-0 h-full w-full" style={{ opacity }} />}
            {renderUrl && mode === "split" && (
              <>
                <img src={renderUrl} alt="Reconstruction" className="absolute inset-0 h-full w-full" style={{ clipPath: `inset(0 0 0 ${split * 100}%)` }} />
                <div className="absolute inset-y-0 w-0.5 bg-white shadow" style={{ left: `${split * 100}%` }} aria-hidden="true" />
                <span className="absolute left-2 top-2 chip border-0 bg-bg/90">photo</span>
                <span className="absolute right-2 top-2 chip border-0 bg-bg/90">reconstruction</span>
              </>
            )}
            {diffUrl && mode === "difference" && <img src={diffUrl} alt="Per-pixel color difference where the reconstruction covers the photo" className="absolute inset-0 h-full w-full" />}
            {!renderUrl && <div className="absolute inset-0 flex items-center justify-center text-[13px] text-muted">Rendering from the estimated camera…</div>}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-2 border-t border-line px-5 py-3 text-[12.5px] text-muted">
        {mode === "overlay" && (
          <div className="w-56">
            <Slider label="Reconstruction opacity" value={opacity} min={0} max={1} step={0.05} onChange={setOpacity} format={(v) => `${Math.round(v * 100)}%`} />
          </div>
        )}
        {mode === "split" && <span>Drag across the image to move the divider.</span>}
        {stats && (
          <span className="font-mono tabular">
            coverage {(stats.coverage * 100).toFixed(1)}% · mean color difference {stats.mad != null ? stats.mad.toFixed(1) : "—"} / 255
          </span>
        )}
        <span className="basis-full">
          Difference is an appearance comparison over covered pixels. It mixes geometry, color, lighting, point size and pose errors, so it is not a calibrated reconstruction error.
        </span>
      </div>
    </div>
  );
}
