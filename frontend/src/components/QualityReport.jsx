import { Icon, Severity } from "./ui.jsx";
import { useStore } from "../state/store.js";

const LABELS = {
  sharpness: "Sharpness",
  overlap: "View overlap",
  exposure: "Exposure",
  texture: "Surface texture",
  resolution: "Resolution",
  variety: "Variety",
  coverage: "Coverage",
};

export default function QualityReport({ report, compact = false }) {
  const expertise = useStore((s) => s.expertise);
  if (!report) return null;
  const tone = report.score >= 70 ? "text-ok" : report.score >= 50 ? "text-warn" : "text-bad";
  return (
    <section aria-label="Input quality" className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="label">Input check</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className={`font-mono text-[24px] leading-none tabular ${tone}`}>{report.score}</span>
            <span className="text-[13px] text-muted">/ 100 · {report.grade}</span>
          </div>
        </div>
        <span className="font-mono text-[10.5px] text-muted" title="Scores come from image measurements (sharpness, exposure, overlap…), not from a reconstruction.">
          heuristic estimate
        </span>
      </div>
      <ul className="space-y-2">
        {report.findings.map((f, i) => (
          <li key={i} className="flex gap-2.5 text-[13.5px] leading-snug">
            <span className="mt-0.5 shrink-0">
              <Severity level={f.code === "ok" ? "ok" : f.severity} />
            </span>
            <span className="text-ink-2">{f.message}</span>
          </li>
        ))}
      </ul>
      {(!compact || expertise === "advanced") && report.components && (
        <details className="group text-[12.5px]">
          <summary className="cursor-pointer select-none text-muted hover:text-ink">How this score is measured</summary>
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
            {Object.entries(report.components).map(([k, v]) => (
              <div key={k}>
                <div className="flex justify-between text-muted">
                  <span>{LABELS[k] || k}</span>
                  <span className="font-mono tabular">{Math.round(v * 100)}</span>
                </div>
                <div className="mt-1 h-1 rounded bg-surface-2">
                  <div className="h-1 rounded bg-ink-2" style={{ width: `${v * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-muted">
            Weighted sum: sharpness 25, overlap 25, exposure 15, texture 15, resolution 10, variety 10. Method: {report.method}. It predicts how
            easy the input is to reconstruct — it is not an accuracy measurement.
          </p>
        </details>
      )}
    </section>
  );
}
