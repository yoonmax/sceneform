import { Icon, InfoTip, Seg, Slider, Toggle } from "./ui.jsx";
import { useStore } from "../state/store.js";

export const DEFAULT_SETTINGS = {
  sample_fps: 4,
  max_frames: 120,
  drop_blurry: true,
  working_max_side: 1600,
  max_features: 6000,
  matcher: "auto",
  depth_max_side: 640,
  confidence_floor: 0.2,
  outlier_std: 2,
  mesh: true,
  mesh_resolution: 192,
  splat_preset: "balanced",
  splat_iterations: null,
};

export default function QualitySelector({ mode, onMode, highAvailable, highReason }) {
  const options = [
    {
      value: "quick",
      title: "Fast preview",
      body: "Camera positions, a dense colored point cloud, depth maps and a rough surface. Usually a few minutes.",
      meta: "Point cloud · depth · mesh",
    },
    {
      value: "high",
      title: "High-quality reconstruction",
      body: "Everything in Fast preview, plus a trained Gaussian splat for photorealistic viewing.",
      meta: "Adds Gaussian splat · needs a supported GPU",
      disabled: !highAvailable,
    },
  ];
  return (
    <fieldset className="grid gap-3 sm:grid-cols-2">
      <legend className="label mb-2">Quality</legend>
      {options.map((o) => (
        <label
          key={o.value}
          className={`relative cursor-pointer rounded-[2px] border p-4 transition-colors ${mode === o.value ? "border-ink bg-raised" : "border-line bg-raised hover:border-line-strong"} ${o.disabled ? "cursor-not-allowed opacity-60" : ""}`}
        >
          <input type="radio" name="mode" value={o.value} checked={mode === o.value} disabled={o.disabled} onChange={() => onMode(o.value)} className="sr-only" />
          <div className="flex items-center justify-between">
            <span className="text-[14.5px] font-medium">{o.title}</span>
            <span className={`flex h-4 w-4 items-center justify-center border ${mode === o.value ? "border-ink bg-ink text-bg" : "border-line-strong"}`}>
              {mode === o.value && <Icon name="check" size={11} stroke={2.4} />}
            </span>
          </div>
          <p className="mt-1.5 text-[13px] leading-snug text-muted">{o.body}</p>
          <p className="mt-3 text-[11.5px] text-faint">{o.meta}</p>
          {o.disabled && <p className="mt-2 text-[12px] text-warn">{highReason || "No supported GPU trainer is available on this server."}</p>}
        </label>
      ))}
    </fieldset>
  );
}

export function AdvancedSettings({ settings, onChange, kind, mode }) {
  const set = (k) => (v) => onChange({ ...settings, [k]: v });
  return (
    <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
      {kind === "video" && (
        <Slider label="Frame sampling" value={settings.sample_fps} min={1} max={10} step={0.5} onChange={set("sample_fps")} format={(v) => `${v} fps`}
          hint="How many candidate frames per second to examine. sceneform then keeps only sharp, well-spaced views." />
      )}
      <Slider label="Maximum views" value={settings.max_frames} min={12} max={300} step={4} onChange={set("max_frames")}
        hint="Upper limit on views used for reconstruction. More views take longer." />
      <Slider label="Working resolution" value={settings.working_max_side} min={960} max={3200} step={160} onChange={set("working_max_side")} format={(v) => `${v}px`}
        hint="Long side used for feature detection and camera estimation." />
      <Slider label="Features per image" value={settings.max_features} min={2000} max={16000} step={500} onChange={set("max_features")}
        hint="SIFT keypoints per view. More helps low-texture scenes but is slower." />
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-[12.5px] text-ink-2">
          Matching strategy <InfoTip text="Exhaustive compares every pair of views (robust, slower). Sequential compares nearby frames (fast for long videos)." />
        </div>
        <Seg value={settings.matcher} onChange={set("matcher")} label="Matching strategy"
          options={[{ value: "auto", label: "Auto" }, { value: "exhaustive", label: "Exhaustive" }, { value: "sequential", label: "Sequential" }]} />
      </div>
      <Slider label="Depth resolution" value={settings.depth_max_side} min={320} max={1280} step={64} onChange={set("depth_max_side")} format={(v) => `${v}px`}
        hint="Resolution of the per-view depth maps fused into the point cloud." />
      <Slider label="Minimum confidence kept" value={settings.confidence_floor} min={0} max={0.8} step={0.05} onChange={set("confidence_floor")} format={(v) => v.toFixed(2)}
        hint="Points whose multi-view agreement is below this are discarded. You can still filter further in the viewer." />
      <Slider label="Outlier filter" value={settings.outlier_std} min={0.5} max={5} step={0.25} onChange={set("outlier_std")} format={(v) => `${v}σ`}
        hint="Statistical outlier removal: drop points whose neighbour distance exceeds the mean by this many standard deviations." />
      <div>
        <Toggle label="Skip blurry frames" checked={settings.drop_blurry} onChange={set("drop_blurry")} hint="Automatically leave out frames the input check marks as blurry." />
        <Toggle label="Build surface mesh" checked={settings.mesh} onChange={set("mesh")} hint="Fuse depth maps into a TSDF volume and extract a mesh (approximate; unseen sides stay open)." />
      </div>
      {settings.mesh && (
        <Slider label="Mesh resolution" value={settings.mesh_resolution} min={96} max={320} step={16} onChange={set("mesh_resolution")} format={(v) => `${v}³`}
          hint="Voxel grid size along the longest axis." />
      )}
      {mode === "high" && (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[12.5px] text-ink-2">
              Splat quality <InfoTip text="Performance ≈ 7k steps, Balanced ≈ 15k, Quality ≈ 30k optimisation steps." />
            </div>
            <Seg value={settings.splat_preset} onChange={set("splat_preset")} label="Splat quality"
              options={[{ value: "performance", label: "Performance" }, { value: "balanced", label: "Balanced" }, { value: "quality", label: "Quality" }]} />
          </div>
          <Slider label="Training steps (override)" value={settings.splat_iterations || 0} min={0} max={30000} step={500}
            onChange={(v) => set("splat_iterations")(v || null)} format={(v) => (v ? v.toLocaleString() : "preset")}
            hint="Leave at 'preset' unless you know you need more or fewer steps." />
        </>
      )}
    </div>
  );
}

export function useIsAdvanced() {
  return useStore((s) => s.expertise === "advanced");
}
