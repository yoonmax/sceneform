import { useState } from "react";
import { Icon } from "./ui.jsx";

const FLAG_TEXT = {
  blurry: "Blurry",
  "motion-blur": "Motion blur",
  dark: "Dark",
  overexposed: "Overexposed",
  duplicate: "Near-duplicate",
  "low-overlap": "Low overlap",
};

/**
 * Photo contact sheet: review, remove, reorder (drag or keyboard), inspect.
 * items: [{ id, url, name, width, height, flags: [] }]
 */
export default function ContactSheet({ items, onRemove, onMove, onOpen }) {
  const [drag, setDrag] = useState(null);
  return (
    <ul className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-6" aria-label="Selected photos">
      {items.map((it, i) => {
        const flagged = it.flags?.length > 0;
        return (
          <li
            key={it.id}
            draggable={!!onMove}
            onDragStart={() => setDrag(i)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => {
              if (drag != null && drag !== i) onMove?.(drag, i);
              setDrag(null);
            }}
            className={`group relative overflow-hidden rounded-[2px] border bg-surface ${flagged ? "border-warn/60" : "border-line"}`}
          >
            <button className="block w-full" onClick={() => onOpen?.(i)} aria-label={`Inspect photo ${i + 1}: ${it.name}`}>
              <img src={it.url} alt="" loading="lazy" className="aspect-[4/3] w-full object-cover" />
            </button>
            <div className="flex items-center justify-between gap-1 px-1.5 py-1 text-[11px] text-muted">
              <span className="tabular">{String(i + 1).padStart(2, "0")}</span>
              {it.width ? <span className="font-mono tabular">{it.width}×{it.height}</span> : null}
            </div>
            {flagged && (
              <div className="absolute left-1.5 top-1.5 flex flex-wrap gap-1">
                {it.flags.map((f) => (
                  <span key={f} className="rounded bg-bg/90 px-1.5 py-0.5 text-[10.5px] font-medium text-warn">
                    {FLAG_TEXT[f] || f}
                  </span>
                ))}
              </div>
            )}
            <div className="absolute right-1 top-1 flex gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
              {onMove && (
                <>
                  <button className="rounded bg-bg/90 p-1 text-ink-2 hover:text-ink" onClick={() => onMove(i, Math.max(0, i - 1))} aria-label={`Move photo ${i + 1} earlier`}>
                    <Icon name="arrowLeft" size={13} />
                  </button>
                  <button className="rounded bg-bg/90 p-1 text-ink-2 hover:text-ink" onClick={() => onMove(i, Math.min(items.length - 1, i + 1))} aria-label={`Move photo ${i + 1} later`}>
                    <Icon name="chevron" size={13} />
                  </button>
                </>
              )}
              {onRemove && (
                <button className="rounded bg-bg/90 p-1 text-ink-2 hover:text-bad" onClick={() => onRemove(i)} aria-label={`Remove photo ${i + 1}`}>
                  <Icon name="close" size={13} />
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
