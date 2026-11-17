import { useEffect, useMemo, useRef, useState } from "react";
import { Icon, Slider } from "./ui.jsx";

/**
 * Video preview with trim handles and a frame strip. Candidates come either
 * from the server (`candidates` with selected/blurry flags) or from in-browser
 * sampling (viewer-only mode).
 */
export default function VideoReview({ file, trim, onTrim, fps, onFps, candidates, analyzing, onAnalyze, advanced }) {
  const url = useMemo(() => URL.createObjectURL(file), [file]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  const video = useRef();
  const [duration, setDuration] = useState(null);
  const [error, setError] = useState(null);

  const start = trim[0];
  const end = trim[1] ?? duration ?? 0;

  return (
    <div className="space-y-5">
      <div className="overflow-hidden rounded-[2px] border border-line bg-black">
        <video
          ref={video}
          src={url}
          controls
          playsInline
          muted
          className="mx-auto max-h-[46vh] w-full"
          onLoadedMetadata={(e) => {
            setDuration(e.currentTarget.duration);
            onTrim([0, e.currentTarget.duration]);
          }}
          onError={() => setError("This browser can’t preview this video, but the server may still be able to read it.")}
        />
      </div>
      {error && <p className="text-[13px] text-warn">{error}</p>}
      {duration != null && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Slider label="Start" value={start} min={0} max={Math.max(0, end - 1)} step={0.1} onChange={(v) => { onTrim([v, end]); if (video.current) video.current.currentTime = v; }} format={(v) => `${v.toFixed(1)}s`}
            hint="Skip the beginning of the clip (for example while you were getting into position)." />
          <Slider label="End" value={end} min={Math.min(duration, start + 1)} max={duration} step={0.1} onChange={(v) => { onTrim([start, v]); if (video.current) video.current.currentTime = v; }} format={(v) => `${v.toFixed(1)}s`}
            hint="Cut the end of the clip." />
          {advanced && (
            <Slider label="Candidate sampling" value={fps} min={0.5} max={6} step={0.5} onChange={onFps} format={(v) => `${v} fps`}
              hint="How densely to look for good frames in this preview." />
          )}
        </div>
      )}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13.5px] font-medium">Frames</div>
          <p className="text-[12.5px] text-muted">
            {candidates
              ? `${candidates.filter((c) => c.selected).length} sharp, well-spaced views chosen from ${candidates.length} candidates.`
              : "Preview which frames will be used."}
          </p>
        </div>
        <button className="btn btn-secondary" onClick={onAnalyze} disabled={analyzing || duration == null}>
          <Icon name="refresh" size={15} /> {analyzing ? "Checking…" : candidates ? "Re-check" : "Check frames"}
        </button>
      </div>
      {candidates && (
        <ul className="flex gap-1.5 overflow-x-auto pb-2 scroll-thin" aria-label="Candidate frames">
          {candidates.map((c) => (
            <li key={c.index} className="relative shrink-0">
              <img
                src={c.thumb}
                alt={`Frame at ${c.timestamp.toFixed(1)} seconds${c.selected ? ", selected" : ""}${c.blurry ? ", blurry" : ""}`}
                className={`h-16 rounded-[2px] object-cover ${c.selected ? "ring-2 ring-ink" : "opacity-45"}`}
              />
              <span className="absolute bottom-0.5 left-1 rounded bg-black/60 px-1 font-mono text-[9.5px] text-white">{c.timestamp.toFixed(1)}s</span>
              {c.blurry && <span className="absolute right-1 top-0.5 rounded bg-bg/90 px-1 text-[9.5px] font-medium text-warn">blur</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
