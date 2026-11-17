import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import UploadDropzone from "./UploadDropzone.jsx";
import ContactSheet from "./ContactSheet.jsx";
import VideoReview from "./VideoReview.jsx";
import QualityReport from "./QualityReport.jsx";
import QualitySelector, { AdvancedSettings, DEFAULT_SETTINGS } from "./QualitySelector.jsx";
import ProcessingStatus from "./ProcessingStatus.jsx";
import { Icon, Modal, ProgressBar, useToast } from "./ui.jsx";
import { api, apiUrl, detectBackend, uploadFiles } from "../api/client.js";
import { buildClientReport, fileToBitmap, frameMetrics, grayFromSource, sampleVideo } from "../lib/clientQuality.js";
import { useStore } from "../state/store.js";

const ACTIVE = "sceneform.activeJob";
const readActive = () => {
  try {
    return JSON.parse(localStorage.getItem(ACTIVE) || "null");
  } catch {
    return null;
  }
};
const writeActive = (v) => {
  try {
    v ? localStorage.setItem(ACTIVE, JSON.stringify(v)) : localStorage.removeItem(ACTIVE);
  } catch {
    /* ignore */
  }
};

function Steps({ step }) {
  const names = ["Add media", "Review", "Quality", "Reconstruct"];
  return (
    <ol className="flex items-center gap-2 text-[12.5px]" aria-label="Progress">
      {names.map((n, i) => (
        <li key={n} className="flex items-center gap-2">
          <span className={`flex h-5 w-5 items-center justify-center font-mono text-[10.5px] ${i < step ? "bg-ink text-bg" : i === step ? "border border-ink text-ink" : "border border-line-strong text-faint"}`} aria-current={i === step ? "step" : undefined}>
            {i < step ? <Icon name="check" size={11} stroke={2.6} /> : i + 1}
          </span>
          <span className={`hidden sm:inline ${i === step ? "text-ink" : "text-muted"}`}>{n}</span>
          {i < names.length - 1 && <span className="mx-1 h-px w-5 bg-line-strong" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

export function LocalSetup() {
  return (
    <div className="space-y-2 text-[13px]">
      <p className="text-ink-2">Run the reconstruction server on your own machine (Apple Silicon Mac or a Linux/Windows PC with an NVIDIA GPU for splats):</p>
      <pre className="overflow-x-auto rounded-[2px] bg-surface p-3 font-mono text-[12px] leading-relaxed text-ink-2">{`cd sceneform/backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000

cd ../frontend && npm install && npm run dev`}</pre>
      <p className="text-muted">
        Then open <span className="font-mono">http://localhost:5173</span>. Full instructions are in{" "}
        <Link className="underline" to="/learn#local">learn → run locally</Link>.
      </p>
    </div>
  );
}

export default function CreateFlow({ onReset }) {
  const navigate = useNavigate();
  const toast = useToast();
  const advanced = useStore((s) => s.expertise === "advanced");
  const [backend, setBackend] = useState(null);
  const [step, setStep] = useState(0);
  const [kind, setKind] = useState(null);
  const [items, setItems] = useState([]); // photos: {id,url,name,width,height,flags,file?}
  const [videoFile, setVideoFile] = useState(null);
  const [project, setProject] = useState(null);
  const [uploadPct, setUploadPct] = useState(null);
  const [report, setReport] = useState(null);
  const [candidates, setCandidates] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [trim, setTrim] = useState([0, null]);
  const [fps, setFps] = useState(2);
  const [mode, setMode] = useState("quick");
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [inspect, setInspect] = useState(null);
  const [name, setName] = useState("");

  useEffect(() => {
    detectBackend().then((b) => {
      setBackend(b);
      const active = readActive();
      if (b.available && active) {
        setJob(active);
        setMode(active.mode || "quick");
        setStep(3);
      }
    });
  }, []);

  const caps = backend?.capabilities;
  const highAvailable = !!caps?.high?.available;
  const highReason = caps
    ? caps.high.trainers?.map((t) => t.reason).filter(Boolean)[0]
    : "Connect a reconstruction server to enable this.";

  const reset = () => {
    items.forEach((i) => i.local && URL.revokeObjectURL(i.url));
    setStep(0);
    setKind(null);
    setItems([]);
    setVideoFile(null);
    setProject(null);
    setReport(null);
    setCandidates(null);
    setJob(null);
    setUploadPct(null);
    writeActive(null);
    onReset?.();
  };

  async function onFiles({ kind: k, files, skipped }) {
    setKind(k);
    setStep(1);
    setName(files[0].name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").slice(0, 60) || "Untitled scene");
    if (skipped?.length) toast(`${skipped.length} unsupported file(s) were skipped.`);
    if (k === "video") setVideoFile(files[0]);
    if (backend?.available) {
      try {
        setBusy(true);
        const p = await api.createProject(files[0].name.replace(/\.[^.]+$/, "").slice(0, 60) || "Untitled scene");
        setProject(p);
        setUploadPct(0);
        const res = await uploadFiles(p.id, files, setUploadPct);
        setUploadPct(null);
        if (res.rejected?.length) toast(`${res.rejected.length} file(s) were rejected: ${res.rejected[0].reason}`, "error");
        if (!res.assets.length) throw new Error(res.rejected?.[0]?.reason || "No files could be used.");
        if (k === "photos") {
          setItems(res.assets.map((a) => ({ id: a.id, url: apiUrl(a.thumb), full: apiUrl(a.url), name: a.name, width: a.width, height: a.height, flags: [] })));
          await analyzePhotosServer(p.id, res.assets);
        }
      } catch (e) {
        toast(e.message, "error");
        setUploadPct(null);
      } finally {
        setBusy(false);
      }
    } else if (k === "photos") {
      const list = files.slice(0, 300).map((f, i) => ({ id: `${i}-${f.name}`, url: URL.createObjectURL(f), full: null, name: f.name, file: f, flags: [], local: true }));
      setItems(list);
      analyzePhotosLocal(list);
    }
  }

  async function analyzePhotosServer(pid, assets) {
    setAnalyzing(true);
    try {
      const r = await api.analyze(pid);
      setReport(r.report);
      const flags = Object.fromEntries(r.assets.map((a) => [a.id, a.flags]));
      setItems((cur) => cur.map((it) => ({ ...it, flags: flags[it.id] || [] })));
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function analyzePhotosLocal(list) {
    setAnalyzing(true);
    try {
      const metrics = [];
      const dims = [];
      for (const it of list) {
        const bmp = await fileToBitmap(it.file);
        dims.push([bmp.width, bmp.height]);
        metrics.push(frameMetrics(grayFromSource(bmp, bmp.width, bmp.height)));
        bmp.close();
      }
      const minW = Math.min(...dims.map((d) => d[0])),
        minH = Math.min(...dims.map((d) => d[1]));
      const rep = buildClientReport(metrics, minW, minH);
      setReport(rep);
      setItems((cur) => cur.map((it, i) => ({ ...it, width: dims[i]?.[0], height: dims[i]?.[1], flags: rep.frameFlags[i] || [] })));
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function analyzeVideo() {
    setAnalyzing(true);
    try {
      if (backend?.available && project) {
        const r = await api.analyze(project.id, { sample_fps: fps, trim_start: trim[0], trim_end: trim[1] });
        setReport(r.report);
        setCandidates(r.candidates.map((c) => ({ ...c, thumb: apiUrl(c.thumb) })));
      } else {
        const v = document.createElement("video");
        v.src = URL.createObjectURL(videoFile);
        v.muted = true;
        await new Promise((res, rej) => {
          v.onloadeddata = res;
          v.onerror = () => rej(new Error("This browser can't decode this video for a preview."));
        });
        const frames = await sampleVideo(v, { start: trim[0], end: trim[1], fps, max: 160 });
        const rep = buildClientReport(frames.map((f) => f.metrics), v.videoWidth, v.videoHeight);
        setReport(rep);
        setCandidates(frames.map((f, i) => ({ index: i, timestamp: f.t, thumb: f.thumb, blurry: rep.frameFlags[i].includes("blurry"), selected: !rep.frameFlags[i].length })));
        URL.revokeObjectURL(v.src);
      }
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function removeItem(i) {
    const it = items[i];
    if (backend?.available && project) {
      try {
        await api.deleteAsset(project.id, it.id);
      } catch (e) {
        return toast(e.message, "error");
      }
    } else if (it.local) URL.revokeObjectURL(it.url);
    const next = items.filter((_, k) => k !== i);
    setItems(next);
  }

  async function moveItem(from, to) {
    const next = [...items];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setItems(next);
    if (backend?.available && project) api.reorderAssets(project.id, next.map((n) => n.id)).catch((e) => toast(e.message, "error"));
  }

  async function start() {
    if (!backend?.available || !project) return;
    setBusy(true);
    try {
      if (name && name !== project.name) await api.renameProject(project.id, name);
      const payload = { ...settings, trim_start: trim[0], trim_end: trim[1] };
      if (kind === "video") payload.sample_fps = Math.max(settings.sample_fps, 1);
      const j = await api.startJob(project.id, mode, payload);
      const active = { id: j.id, projectId: project.id, mode, mesh: settings.mesh };
      writeActive(active);
      setJob(active);
      setStep(3);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const canContinue = kind === "photos" ? items.length >= 3 : !!videoFile;
  const stats = useMemo(() => {
    const flagged = items.filter((i) => i.flags.length).length;
    return { flagged };
  }, [items]);

  if (backend === null) return <div className="h-64 skeleton rounded-[3px]" aria-label="Loading" />;

  if (step === 0) {
    return (
      <div className="space-y-3">
        <UploadDropzone onFiles={onFiles} />
        {!backend.available && (
          <p className="flex items-start gap-2 text-[12.5px] text-muted">
            <Icon name="info" size={15} className="mt-0.5 shrink-0" />
            This public site is a viewer: you can check your footage here, but reconstruction runs on a GPU server you start yourself.{" "}
            <Link to="/learn#local" className="underline">How to run it</Link>
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="panel p-5 sm:p-7">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Steps step={step} />
        {step < 3 && (
          <button className="btn btn-ghost" onClick={reset}>
            Start over
          </button>
        )}
      </div>

      {step === 1 && (
        <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
          <div className="min-w-0 space-y-4">
            {uploadPct != null && (
              <div className="space-y-2">
                <div className="flex justify-between text-[13px]">
                  <span>Uploading securely…</span>
                  <span className="font-mono tabular text-muted">{Math.round(uploadPct * 100)}%</span>
                </div>
                <ProgressBar value={uploadPct} label="Upload progress" />
              </div>
            )}
            {kind === "photos" && (
              <>
                <div className="flex items-baseline justify-between">
                  <h2 className="text-[15px] font-medium">{items.length} photos</h2>
                  <p className="text-[12.5px] text-muted">{stats.flagged ? `${stats.flagged} flagged — review or remove them` : "Drag to reorder · tap to inspect"}</p>
                </div>
                <ContactSheet items={items} onRemove={removeItem} onMove={moveItem} onOpen={setInspect} />
              </>
            )}
            {kind === "video" && videoFile && (
              <VideoReview file={videoFile} trim={trim} onTrim={setTrim} fps={fps} onFps={setFps} candidates={candidates} analyzing={analyzing || uploadPct != null} onAnalyze={analyzeVideo} advanced={advanced} />
            )}
          </div>
          <aside className="space-y-5">
            {analyzing && !report && <div className="h-40 skeleton rounded-[2px]" aria-label="Checking input quality" />}
            {report ? <QualityReport report={report} compact /> : !analyzing && <p className="text-[13px] text-muted">{kind === "video" ? "Check frames to get feedback on blur, lighting and coverage." : "Analysing your photos…"}</p>}
            <button className="btn btn-primary w-full" disabled={!canContinue || busy || uploadPct != null} onClick={() => setStep(2)}>
              Continue <Icon name="chevron" size={16} />
            </button>
          </aside>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-6">
          <div className="max-w-md space-y-1.5">
            <label htmlFor="scene-name" className="label">Scene name</label>
            <input id="scene-name" className="field" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </div>
          <QualitySelector mode={mode} onMode={setMode} highAvailable={highAvailable} highReason={highReason} />
          <div>
            <button className="btn btn-ghost -ml-2" onClick={() => setShowAdvanced((v) => !v)} aria-expanded={showAdvanced || advanced}>
              <Icon name="chevron" size={15} className={`transition-transform ${showAdvanced || advanced ? "rotate-90" : ""}`} /> Advanced settings
            </button>
            {(showAdvanced || advanced) && (
              <div className="mt-4 rounded-[2px] border border-line p-5">
                <AdvancedSettings settings={settings} onChange={setSettings} kind={kind} mode={mode} />
              </div>
            )}
          </div>
          {!backend.available && (
            <div className="rounded-[2px] border border-line bg-surface p-5">
              <div className="mb-2 flex items-center gap-2 text-[14px] font-medium">
                <Icon name="info" size={16} /> Reconstruction isn’t available on this website
              </div>
              <p className="mb-3 text-[13px] text-muted">
                Turning footage into 3D needs a GPU-capable server, and none is connected to this public site. Nothing will be uploaded.
                You can explore the example scenes, or run sceneform locally:
              </p>
              <LocalSetup />
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
            <button className="btn btn-ghost" onClick={() => setStep(1)}>
              Back
            </button>
            <div className="flex gap-2">
              {!backend.available && (
                <Link className="btn btn-secondary" to="/explore">
                  Explore examples
                </Link>
              )}
              <button className="btn btn-primary btn-lg" disabled={!backend.available || busy} onClick={start} title={backend.available ? undefined : "No reconstruction server connected"}>
                <Icon name="cube" /> Reconstruct
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 3 && job && (
        <ProcessingStatus
          jobId={job.id}
          mode={job.mode}
          mesh={job.mesh !== false}
          onDone={(j) => {
            writeActive(null);
            toast("Your scene is ready", "success");
            navigate(`/scene/project/${job.projectId}/${j.run_id}`);
          }}
          onCancelled={() => {
            writeActive(null);
            toast("Reconstruction cancelled");
            reset();
          }}
        />
      )}

      <Modal open={inspect != null} onClose={() => setInspect(null)} title={inspect != null ? `Photo ${inspect + 1} · ${items[inspect]?.name}` : ""} wide>
        {inspect != null && items[inspect] && (
          <div className="space-y-3">
            <img src={items[inspect].full || items[inspect].url} alt={items[inspect].name} className="max-h-[60vh] w-full rounded-[2px] object-contain" />
            <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted">
              <span className="font-mono">{items[inspect].width}×{items[inspect].height}</span>
              <span>{items[inspect].flags.length ? items[inspect].flags.join(", ") : "No issues detected"}</span>
              <button className="btn btn-secondary" onClick={() => { removeItem(inspect); setInspect(null); }}>
                <Icon name="trash" size={15} /> Remove
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
