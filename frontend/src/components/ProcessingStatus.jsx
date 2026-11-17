import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { Icon, ProgressBar } from "./ui.jsx";
import { useStore } from "../state/store.js";

export const STAGES = [
  ["validating", "Checking your files"],
  ["extracting", "Preparing frames"],
  ["estimating_geometry", "Recovering camera positions"],
  ["estimating_depth", "Estimating depth"],
  ["building_point_cloud", "Building the point cloud"],
  ["building_mesh", "Building a surface mesh"],
  ["training_splats", "Training the Gaussian splat"],
  ["preparing_output", "Preparing your scene"],
];

/** Polls the job (1 Hz) and shows real backend stages. Survives refreshes:
 *  the active job id is kept in localStorage by the caller. */
export default function ProcessingStatus({ jobId, mode, mesh = true, onDone, onCancelled }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [logs, setLogs] = useState(null);
  const advanced = useStore((s) => s.expertise === "advanced");
  const announce = useRef("");
  const [live, setLive] = useState("");

  useEffect(() => {
    let alive = true;
    let timer;
    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (!alive) return;
        setJob(j);
        setError(null);
        if (j.stage_label && j.stage_label !== announce.current) {
          announce.current = j.stage_label;
          setLive(j.stage_label);
        }
        if (j.state === "succeeded") return onDone?.(j);
        if (j.state === "cancelled") return onCancelled?.(j);
        if (j.state === "failed") return;
      } catch (e) {
        if (alive) setError(e.message);
      }
      timer = setTimeout(tick, 1000);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  useEffect(() => {
    if (!advanced || !logs) return;
    const t = setInterval(() => api.jobLogs(jobId).then((d) => setLogs(d.events)).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [advanced, logs, jobId]);

  const stages = STAGES.filter(([k]) => (k !== "training_splats" || mode === "high") && (k !== "building_mesh" || mesh));
  const idx = job ? stages.findIndex(([k]) => k === job.stage) : -1;
  const done = job?.state === "succeeded";
  const failed = job?.state === "failed";
  const elapsed = job?.started_at ? Math.max(0, (job.finished_at || Date.now() / 1000) - job.started_at) : null;

  return (
    <div className="space-y-6">
      <div aria-live="polite" className="sr-only">
        {live}
      </div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="label">{failed ? "Stopped" : done ? "Finished" : job?.state === "queued" ? "Waiting" : "Reconstructing"}</div>
          <h2 className="mt-1 serif text-[22px] leading-tight">
            {failed ? "That didn’t work out" : done ? "Your scene is ready" : job?.state === "queued" ? "In the queue" : job?.stage_label || "Starting…"}
          </h2>
          {job?.state === "queued" && job.queuePosition > 0 && (
            <p className="mt-1 text-[13px] text-muted">{job.queuePosition} reconstruction(s) ahead of yours.</p>
          )}
        </div>
        {elapsed != null && <span className="font-mono text-[12px] text-muted tabular">t = {fmt(elapsed)}</span>}
      </div>

      {!failed && !done && (
        <div className="space-y-2">
          <ProgressBar value={job?.state === "running" ? job.progress : null} label={job?.stage_label || "Reconstruction progress"} />
          <p className="min-h-[1.25rem] text-[13px] text-muted">{job?.message}</p>
          <p className="text-[12px] text-faint">
            {job?.progress == null ? "This step doesn’t report a percentage — the bar shows it’s still working." : "Progress within the current step."}
          </p>
        </div>
      )}

      <ol className="space-y-1.5">
        {stages.map(([k, label], i) => {
          const state = done || (idx > i) ? "done" : idx === i ? (failed ? "failed" : "active") : "pending";
          return (
            <li key={k} className="flex items-center gap-3 text-[13.5px]">
              <span
                className={`flex h-[18px] w-[18px] items-center justify-center border ${state === "done" ? "border-ink bg-ink text-bg" : state === "active" ? "border-ink" : state === "failed" ? "border-bad text-bad" : "border-line-strong"}`}
                aria-hidden="true"
              >
                {state === "done" && <Icon name="check" size={11} stroke={2.6} />}
                {state === "active" && <span className="h-1.5 w-1.5 animate-pulse bg-ink" />}
                {state === "failed" && <Icon name="close" size={11} stroke={2.4} />}
              </span>
              <span className={state === "pending" ? "text-faint" : "text-ink"}>{label}</span>
              <span className="sr-only">{state}</span>
            </li>
          );
        })}
      </ol>

      {failed && (
        <div role="alert" className="rounded-[2px] border border-bad/40 bg-bad/5 p-4">
          <p className="text-[14px] text-ink">{job.error}</p>
          <p className="mt-2 text-[13px] text-muted">
            {job.error_code === "camera_failure"
              ? "Try recording more slowly with more overlap between views, or add photos from in-between angles."
              : job.error_code === "input"
                ? "Fix the input and try again."
                : "You can retry. If it keeps failing, check the job log in advanced mode."}
          </p>
          <div className="mt-3 flex gap-2">
            <button className="btn btn-primary" onClick={async () => setJob(await api.retryJob(jobId))}>
              <Icon name="refresh" size={16} /> Retry
            </button>
          </div>
        </div>
      )}

      {error && <p className="text-[13px] text-warn">{error}</p>}

      <div className="flex flex-wrap gap-2">
        {!done && !failed && job?.state !== "cancelled" && (
          <button
            className="btn btn-secondary"
            disabled={job?.cancel_requested}
            onClick={async () => {
              try {
                setJob(await api.cancelJob(jobId));
              } catch (e) {
                setError(e.message);
              }
            }}
          >
            {job?.cancel_requested ? "Stopping…" : "Cancel"}
          </button>
        )}
        {advanced && (
          <button className="btn btn-ghost" onClick={() => api.jobLogs(jobId).then((d) => setLogs(d.events))}>
            {logs ? "Refresh log" : "Show job log"}
          </button>
        )}
      </div>
      {advanced && logs && (
        <pre className="max-h-64 overflow-auto rounded-[2px] bg-surface p-3 font-mono text-[11.5px] leading-relaxed text-ink-2 scroll-thin">
          {logs
            .filter((e) => e.type !== "progress" || e.message)
            .slice(-200)
            .map((e) => `${new Date(e.t * 1000).toLocaleTimeString()}  ${e.type === "stage" ? "▸ " + e.label : e.message ?? ""}`)
            .join("\n")}
        </pre>
      )}
    </div>
  );
}

function fmt(s) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}
