import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";

const P = {
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  video: "M15 10l4.55-2.28A1 1 0 0 1 21 8.62v6.76a1 1 0 0 1-1.45.9L15 14M4 6h9a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z",
  photos: "M4 7h3l2-2h6l2 2h3v12H4V7Zm8 9.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
  cube: "M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Zm0 0v9m0 0 8-4.5M12 12l-8-4.5",
  grid: "M4 4h7v7H4V4Zm9 0h7v7h-7V4ZM4 13h7v7H4v-7Zm9 0h7v7h-7v-7Z",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  compass: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm3.5-12.5-2 5-5 2 2-5 5-2Z",
  book: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5Zm0 14a2 2 0 0 1 2-2h13",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-14v1m0 16v1m9-9h-1M4 12H3m15.4-6.4-.7.7M6.3 17.7l-.7.7m12.8 0-.7-.7M6.3 6.3l-.7-.7",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z",
  close: "M6 6l12 12M18 6 6 18",
  check: "M5 12.5 10 17l9-10",
  alert: "M12 9v4m0 4h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  info: "M12 16v-4m0-4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  play: "M7 5v14l11-7L7 5Z",
  stop: "M7 7h10v10H7z",
  camera: "M3 8a2 2 0 0 1 2-2h2l1.5-2h7L17 6h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Zm9 9a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
  ruler: "M3 17 17 3l4 4L7 21l-4-4Zm4-4 2 2m1-5 2 2m1-5 2 2",
  layers: "m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5",
  download: "M12 4v12m0 0 4-4m-4 4-4-4M4 20h16",
  undo: "M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
  redo: "m15 14 5-5-5-5m5 5H9a5 5 0 0 0 0 10h3",
  home: "M3 11 12 4l9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-9Z",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5m11-5v5h-5",
  plane: "M2 16l10 5 10-5-10-5-10 5Zm10-5V3",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  crop: "M6 2v16h16M2 6h16v16",
  trash: "M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13",
  copy: "M8 8h12v12H8V8Zm-4 8V4h12",
  edit: "M4 20h4L19 9l-4-4L4 16v4Z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  split: "M12 3v18M4 5h16v14H4z",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  fly: "M12 3v4m0 10v4M3 12h4m10 0h4m-9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  orbit: "M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm-9 0c0-3 4-6 9-6s9 3 9 6-4 2-9 2-9 1-9-2Z",
  image: "M4 5h16v14H4V5Zm0 11 5-5 4 4 2-2 5 5M15 9h.01",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z",
  chevron: "m9 6 6 6-6 6",
  menu: "M4 7h16M4 12h16M4 17h16",
  dots: "M12 6h.01M12 12h.01M12 18h.01",
  arrowLeft: "M15 6l-6 6 6 6",
  external: "M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
};

export function Icon({ name, size = 18, className = "", stroke = 1.6, label }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
    >
      <path d={P[name] || P.info} />
    </svg>
  );
}

export function Tip({ text, children }) {
  const id = useId();
  const [show, setShow] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      <span aria-describedby={id}>{children}</span>
      <span
        id={id}
        role="tooltip"
        className={`pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-max max-w-[240px] -translate-x-1/2 rounded-[2px] bg-ink px-2 py-1 text-[12px] leading-snug text-bg shadow transition-opacity ${show ? "opacity-100" : "opacity-0"}`}
      >
        {text}
      </span>
    </span>
  );
}

export function InfoTip({ text }) {
  return (
    <Tip text={text}>
      <button type="button" className="text-faint hover:text-ink" aria-label={`More info: ${text}`}>
        <Icon name="info" size={14} />
      </button>
    </Tip>
  );
}

export function Seg({ value, options, onChange, label }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          disabled={o.disabled}
          title={o.disabled ? o.disabledReason : undefined}
          onClick={() => onChange(o.value)}
          className="disabled:opacity-40"
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Slider({ label, value, min, max, step, onChange, format = (v) => v, hint }) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[12.5px]">
        <label htmlFor={id} className="flex items-center gap-1.5 text-ink-2">
          {label} {hint && <InfoTip text={hint} />}
        </label>
        <span className="font-mono text-[11.5px] text-muted tabular">{format(value)}</span>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

export function Toggle({ label, checked, onChange, hint }) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <label htmlFor={id} className="flex items-center gap-1.5 text-[13px] text-ink-2">
        {label} {hint && <InfoTip text={hint} />}
      </label>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-[18px] w-8 border transition-colors ${checked ? "border-ink bg-ink" : "border-line-strong bg-surface-2"}`}
      >
        <span className={`absolute top-[2px] h-3 w-3 bg-bg transition-transform ${checked ? "translate-x-[16px]" : "translate-x-[2px]"}`} />
      </button>
    </div>
  );
}

export function Stat({ label, value, sub }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="mt-0.5 font-mono text-[14px] tabular">{value}</div>
      {sub && <div className="text-[11.5px] text-muted">{sub}</div>}
    </div>
  );
}

export function Severity({ level }) {
  const map = {
    problem: ["alert", "text-bad", "Problem"],
    warning: ["alert", "text-warn", "Warning"],
    info: ["info", "text-muted", "Note"],
    ok: ["check", "text-ok", "OK"],
  };
  const [icon, cls, text] = map[level] || map.info;
  return (
    <span className={`inline-flex items-center ${cls}`}>
      <Icon name={icon} size={15} />
      <span className="sr-only">{text}: </span>
    </span>
  );
}

export function Modal({ open, onClose, title, children, wide }) {
  const ref = useRef();
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement;
    ref.current?.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-0 sm:items-center sm:p-6" onMouseDown={onClose}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`panel max-h-[90vh] w-full overflow-auto shadow-xl outline-none scroll-thin ${wide ? "sm:max-w-3xl" : "sm:max-w-lg"} rounded-b-none sm:rounded-b-xl`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

const ToastCtx = createContext(() => {});
export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((msg, kind = "info") => {
    const id = Math.random();
    setItems((s) => [...s, { id, msg, kind }]);
    setTimeout(() => setItems((s) => s.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="pointer-events-auto flex max-w-md items-center gap-2 border border-ink bg-ink px-3.5 py-2 text-[13px] text-bg">
            <Icon name={t.kind === "error" ? "alert" : t.kind === "success" ? "check" : "info"} size={16} />
            {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

export function ProgressBar({ value, label }) {
  const indeterminate = value == null;
  return (
    <div
      className={`h-1.5 w-full overflow-hidden bg-surface-2 ${indeterminate ? "indeterminate" : ""}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(value * 100)}
      aria-valuetext={indeterminate ? "In progress" : `${Math.round(value * 100)}%`}
    >
      {!indeterminate && <div className="h-full bg-ink transition-[width] duration-500" style={{ width: `${Math.max(2, value * 100)}%` }} />}
    </div>
  );
}

export function Wordmark({ className = "" }) {
  return (
    <span className={`inline-flex items-baseline gap-2 ${className}`}>
      <span className="serif text-[18px] font-semibold tracking-[-0.01em]">sceneform</span>
    </span>
  );
}
