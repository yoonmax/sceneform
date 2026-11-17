import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Icon, Seg } from "../components/ui.jsx";
import { LocalSetup } from "../components/CreateFlow.jsx";

/* Original, minimal capture diagrams. Animations respect reduced motion via CSS. */
function ObjectOrbit() {
  return (
    <svg viewBox="0 0 320 200" className="h-auto w-full" role="img" aria-label="A camera circling an object in two rings, one at eye level and one higher, always pointing at the object">
      <ellipse cx="160" cy="120" rx="120" ry="38" fill="none" stroke="var(--line-strong)" strokeDasharray="4 5" />
      <ellipse cx="160" cy="88" rx="96" ry="26" fill="none" stroke="var(--line-strong)" strokeDasharray="4 5" />
      <rect x="140" y="92" width="40" height="44" rx="6" fill="var(--surface-2)" stroke="var(--ink-2)" />
      <path d="M140 100 160 90l20 10" fill="none" stroke="var(--ink-2)" />
      <g style={{ offsetPath: "path('M40 120 a120 38 0 1 0 240 0 a120 38 0 1 0 -240 0')", animation: "orbit 9s linear infinite" }}>
        <rect x="-9" y="-6" width="18" height="12" rx="2" fill="var(--ink)" />
        <circle r="3" fill="var(--bg)" />
      </g>
      <style>{`@keyframes orbit{from{offset-distance:0%}to{offset-distance:100%}}`}</style>
    </svg>
  );
}

function RoomSweep() {
  return (
    <svg viewBox="0 0 320 200" className="h-auto w-full" role="img" aria-label="Top view of a room: the camera walks a loop near the walls, facing into the room, with overlapping views">
      <rect x="30" y="20" width="260" height="160" fill="none" stroke="var(--ink-2)" />
      <rect x="120" y="80" width="80" height="40" rx="4" fill="var(--surface-2)" stroke="var(--line-strong)" />
      <path d="M70 60 H250 V140 H70 Z" fill="none" stroke="var(--line-strong)" strokeDasharray="4 5" />
      {[[70, 60, 45], [160, 60, 90], [250, 60, 135], [250, 140, 225], [160, 140, 270], [70, 140, 315]].map(([x, y, a], i) => (
        <g key={i} transform={`translate(${x} ${y}) rotate(${a})`}>
          <path d="M0 0 L46 -18 L46 18 Z" fill="var(--accent)" opacity="0.12" />
          <rect x="-7" y="-5" width="14" height="10" rx="2" fill="var(--ink)" />
        </g>
      ))}
    </svg>
  );
}

const TIPS = {
  object: [
    ["Circle the subject", "Walk all the way around once at eye level, then again a bit higher, keeping the subject in frame."],
    ["Move slowly", "Aim for about 20 seconds per circle. Fast motion causes blur, which ruins matching."],
    ["Keep overlap", "Each view should share most of its content with the previous one."],
    ["Fill the frame", "Stay close enough that the object covers about half the image."],
    ["Textured background helps", "A plain white table gives the cameras nothing to lock onto; a patterned cloth does."],
  ],
  room: [
    ["Walk, don’t pivot", "Turning in place gives no depth. Walk a loop near the walls and face into the room."],
    ["Overlap generously", "Move a step, then turn a little. Consecutive views should overlap by two-thirds."],
    ["Light it evenly", "Turn on all the lights and avoid strong sun patches moving across the floor."],
    ["Mind the blank walls", "Plain painted walls and ceilings have little texture; include furniture and edges in each view."],
    ["Close the loop", "Finish where you started so the reconstruction can tie both ends together."],
  ],
};

const CHECKLIST = [
  "Sharp images — no motion blur",
  "Consistent, even lighting",
  "Many viewpoints, not just one side",
  "Nothing moving in the scene (people, pets, trees in wind)",
  "Few mirrors, glass or glossy surfaces",
  "Enough texture on surfaces",
  "20–150 photos, or a 20–90 second video",
];

const LIMITS = [
  ["Reflective & shiny surfaces", "Reflections move with the camera, so they look like different geometry from each view."],
  ["Glass & transparency", "The camera sees through it; there is no consistent surface to reconstruct."],
  ["Moving people or objects", "Anything that moves breaks the assumption that the scene is static. It is usually removed or smeared."],
  ["Plain, textureless surfaces", "Blank walls give no features to match. Depth there is guessed by the network and often filtered out."],
  ["Too few viewpoints", "Sides that were never filmed can’t be reconstructed. The mesh stays open there."],
  ["Heavy motion blur", "Blurry frames have few reliable features; sceneform skips them when it can."],
  ["Changing light", "Shifting exposure or sunlight makes the same surface look different between views."],
  ["Scale", "Photos alone don’t reveal real size. Distances are relative until you give a known length."],
];

export default function LearnPage() {
  const [guide, setGuide] = useState("object");
  const [checked, setChecked] = useState({});
  const loc = useLocation();
  useEffect(() => {
    if (loc.hash) document.getElementById(loc.hash.slice(1))?.scrollIntoView({ behavior: "smooth" });
  }, [loc.hash]);
  return (
    <div className="mx-auto max-w-[1000px] px-4 py-10 sm:px-6">
      <h1 className="serif text-[30px]">Learn</h1>
      <p className="mt-2 max-w-xl text-[14px] text-muted">How to film for 3D, what happens to your footage, and where reconstruction struggles.</p>

      <section className="mt-10" aria-labelledby="guide-h">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="guide-h" className="serif text-[20px]">Capture guide</h2>
          <Seg label="Guide" value={guide} onChange={setGuide} options={[{ value: "object", label: "Recording an object" }, { value: "room", label: "Recording a room" }]} />
        </div>
        <div className="mt-6 grid items-start gap-8 md:grid-cols-[1fr_1.1fr]">
          <div className="panel p-4">{guide === "object" ? <ObjectOrbit /> : <RoomSweep />}</div>
          <ol className="space-y-4">
            {TIPS[guide].map(([t, d], i) => (
              <li key={t} className="flex gap-3">
                <span className="font-mono text-[12px] text-faint">0{i + 1}</span>
                <div>
                  <div className="text-[14px] font-medium">{t}</div>
                  <p className="text-[13px] text-muted">{d}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mt-14" aria-labelledby="check-h">
        <h2 id="check-h" className="serif text-[20px]">Before you upload</h2>
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {CHECKLIST.map((c) => (
            <li key={c}>
              <label className="flex cursor-pointer items-center gap-3 rounded-[2px] border border-line bg-raised px-3.5 py-2.5 text-[13.5px]">
                <input type="checkbox" checked={!!checked[c]} onChange={(e) => setChecked({ ...checked, [c]: e.target.checked })} className="h-4 w-4 accent-[var(--ink)]" />
                {c}
              </label>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[12.5px] text-muted">sceneform also checks blur, lighting, overlap and duplicates automatically when you upload.</p>
      </section>

      <section className="mt-14" aria-labelledby="how-h">
        <h2 id="how-h" className="serif text-[20px]">What happens to your footage</h2>
        <ol className="mt-5 space-y-5 border-l border-line pl-6">
          {[
            ["Frames are chosen", "For video, frames are sampled and scored. Blurry and redundant ones are skipped; a new view is kept once the scene has moved enough."],
            ["Cameras are found", "Distinctive points (SIFT features) are matched between views. COLMAP’s Structure-from-Motion solves for every camera’s position, orientation and lens, refining everything together with bundle adjustment."],
            ["Depth is estimated", "A depth network (Depth Anything V2) predicts relative depth for each view. sceneform anchors it to the triangulated points so all views agree on scale."],
            ["Views must agree", "Each depth pixel is projected into neighbouring cameras. Points survive only if several cameras see the same surface; that agreement is the confidence you can filter by."],
            ["Optional: surface and splat", "Depth maps are fused into a volume to extract a mesh. In high-quality mode a Gaussian splat is trained on the posed photos for photorealistic viewing."],
          ].map(([t, d]) => (
            <li key={t}>
              <div className="text-[14.5px] font-medium">{t}</div>
              <p className="mt-0.5 max-w-2xl text-[13.5px] text-muted">{d}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-14" aria-labelledby="limits-h">
        <h2 id="limits-h" className="serif text-[20px]">Known limitations</h2>
        <div className="mt-5 grid gap-x-8 gap-y-4 sm:grid-cols-2">
          {LIMITS.map(([t, d]) => (
            <div key={t} className="flex gap-3">
              <Icon name="alert" size={16} className="mt-0.5 shrink-0 text-warn" />
              <div>
                <div className="text-[14px] font-medium">{t}</div>
                <p className="text-[13px] text-muted">{d}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section id="local" className="mt-14 scroll-mt-20" aria-labelledby="local-h">
        <h2 id="local-h" className="serif text-[20px]">Run locally</h2>
        <p className="mt-2 max-w-2xl text-[13.5px] text-muted">
          The public site shows precomputed examples. To reconstruct your own footage, run the Python server. Fast preview runs on any modern computer
          (CPU for camera estimation, GPU/Apple Silicon accelerates depth). Gaussian-splat training needs Apple Silicon (Metal) or an NVIDIA GPU.
        </p>
        <div className="mt-4 panel p-5">
          <LocalSetup />
        </div>
      </section>
    </div>
  );
}
