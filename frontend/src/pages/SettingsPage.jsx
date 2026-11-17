import { useEffect, useState } from "react";
import { Seg, useToast } from "../components/ui.jsx";
import { useStore } from "../state/store.js";
import { detectBackend } from "../api/client.js";
import { localdb } from "../storage/localdb.js";

function Row({ title, desc, children }) {
  return (
    <div className="flex flex-col gap-3 border-b border-line py-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="max-w-md">
        <div className="text-[14px] font-medium">{title}</div>
        <p className="mt-0.5 text-[13px] text-muted">{desc}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

const CREDITS = [
  ["COLMAP / pycolmap", "Structure-from-Motion", "BSD-3-Clause"],
  ["Depth Anything V2 (Small)", "Monocular depth model", "Apache-2.0"],
  ["msplat", "Gaussian-splat training on Apple Silicon", "Apache-2.0"],
  ["Spark", "Gaussian-splat rendering in the browser", "MIT"],
  ["three.js, React Three Fiber, Drei", "3D rendering", "MIT"],
  ["OpenCV, NumPy, SciPy, scikit-image, trimesh", "Vision & geometry", "Apache-2.0 / BSD / MIT"],
  ["Source Serif 4, IBM Plex Sans, IBM Plex Mono", "Typefaces (Google Fonts)", "SIL OFL 1.1"],
];

export default function SettingsPage() {
  const s = useStore();
  const toast = useToast();
  const [api, setApi] = useState(s.apiOverride);
  const [backend, setBackend] = useState(null);
  useEffect(() => {
    detectBackend().then(setBackend);
  }, []);

  return (
    <div className="mx-auto max-w-[820px] px-4 py-10 sm:px-6">
      <h1 className="serif text-[30px]">Settings</h1>

      <section className="mt-8">
        <Row title="Appearance" desc="Follow your system, or choose light or dark.">
          <Seg label="Theme" value={s.theme} onChange={(v) => s.setPref("theme", v)} options={[{ value: "system", label: "System" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
        </Row>
        <Row title="Experience" desc="Beginner keeps things simple. Advanced shows camera matrices, job logs, diagnostics and every reconstruction setting.">
          <Seg label="Experience" value={s.expertise} onChange={(v) => s.setPref("expertise", v)} options={[{ value: "beginner", label: "Beginner" }, { value: "advanced", label: "Advanced" }]} />
        </Row>
        <Row title="Rendering quality" desc="Lower quality renders fewer pixels so large scenes stay smooth on laptops and phones.">
          <Seg label="Rendering quality" value={s.renderQuality} onChange={(v) => s.setPref("renderQuality", v)} options={[{ value: "performance", label: "Performance" }, { value: "balanced", label: "Balanced" }, { value: "quality", label: "Quality" }]} />
        </Row>
        <Row
          title="Reconstruction server"
          desc={backend?.available ? `Connected (v${backend.version}). Fast preview available; high quality ${backend.capabilities.high.available ? "available" : "not available on this server"}.` : "Not connected. Point this at your own sceneform server to reconstruct footage."}
        >
          {s.expertise === "advanced" ? (
            <form
              className="flex gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                s.setPref("apiOverride", api.trim());
                const b = await detectBackend(true);
                setBackend(b);
                toast(b.available ? "Connected to server" : "No sceneform server at that address", b.available ? "success" : "error");
              }}
            >
              <input className="field w-60 font-mono text-[12px]" placeholder="http://localhost:8000" value={api} onChange={(e) => setApi(e.target.value)} aria-label="Server URL" />
              <button className="btn btn-secondary">Connect</button>
            </form>
          ) : (
            <span className="chip">{backend?.available ? "connected" : "viewer mode"}</span>
          )}
        </Row>
        <Row title="Local data" desc="Preferences, recently opened scenes, saved edits on examples and your anonymous project key are stored in this browser only.">
          <button
            className="btn btn-secondary"
            onClick={async () => {
              await localdb.clearAll();
              try {
                ["sceneform.prefs", "sceneform.theme", "sceneform.activeJob"].forEach((k) => localStorage.removeItem(k));
              } catch {
                /* ignore */
              }
              toast("Local data cleared", "success");
            }}
          >
            Clear local data
          </button>
        </Row>
      </section>

      <section className="mt-10">
        <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-muted">Privacy</h2>
        <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">
          This public site never uploads your files — it only analyses them in your browser. When you connect a sceneform server, uploads go only to that
          server, are tied to an anonymous key stored in this browser, are not listed to anyone else, and are deleted automatically after the server’s
          retention period (72 hours by default) or immediately when you delete the project.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-muted">Open-source components</h2>
        <ul className="mt-3 divide-y divide-line text-[13px]">
          {CREDITS.map(([n, w, l]) => (
            <li key={n} className="flex justify-between gap-4 py-2">
              <span><span className="text-ink">{n}</span> <span className="text-muted">— {w}</span></span>
              <span className="shrink-0 font-mono text-[12px] text-muted">{l}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[12.5px] text-muted">Example scene sources and their licenses are listed in each scene’s Overview tab and in the repository’s THIRD_PARTY_NOTICES.</p>
      </section>
    </div>
  );
}
