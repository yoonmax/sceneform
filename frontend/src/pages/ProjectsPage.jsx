import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon, Modal, Seg, useToast } from "../components/ui.jsx";
import { api, apiUrl, detectBackend } from "../api/client.js";
import { localdb } from "../storage/localdb.js";
import { formatBytes, formatCount } from "../lib/scene.js";

const STATUS = {
  draft: ["Draft", "text-muted"],
  queued: ["Queued", "text-warn"],
  processing: ["Processing", "text-warn"],
  ready: ["Ready", "text-ok"],
  failed: ["Failed", "text-bad"],
};

function when(t) {
  const d = new Date(t * 1000);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function ProjectCard({ p, layout, onRename, onDelete, onDuplicate, onRetry }) {
  const [label, cls] = STATUS[p.status] || STATUS.draft;
  const run = p.runs?.[0];
  const open = run ? `/scene/project/${p.id}/${run.id}` : null;
  const thumb = p.thumbnail ? apiUrl(p.thumbnail) : null;
  const meta = (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-faint tabular">
      <span>{p.inputType ? `${p.inputCount} ${p.inputType === "video" ? "video" : "photos"}` : "no input"}</span>
      {run?.summary && <span>{formatCount(run.summary.points)} pts</span>}
      {run && <span>{run.mode === "high" ? "high quality" : "fast preview"}</span>}
      {run?.summary?.bytes && <span>{formatBytes(run.summary.bytes)}</span>}
      {p.runs?.length > 1 && <span>{p.runs.length} versions</span>}
    </div>
  );
  const actions = (
    <div className="flex items-center gap-1">
      {p.status === "failed" && p.job && (
        <button className="btn btn-ghost h-8 px-2 text-[12.5px]" onClick={() => onRetry(p)}>
          <Icon name="refresh" size={14} /> Retry
        </button>
      )}
      <button className="btn btn-ghost btn-icon h-8 w-8" onClick={() => onRename(p)} aria-label={`Rename ${p.name}`}><Icon name="edit" size={15} /></button>
      <button className="btn btn-ghost btn-icon h-8 w-8" onClick={() => onDuplicate(p)} aria-label={`Duplicate ${p.name}`}><Icon name="copy" size={15} /></button>
      <button className="btn btn-ghost btn-icon h-8 w-8 hover:text-bad" onClick={() => onDelete(p)} aria-label={`Delete ${p.name}`}><Icon name="trash" size={15} /></button>
    </div>
  );
  const status = (
    <span className={`inline-flex items-center gap-1.5 text-[12px] ${cls}`}>
      <span className="h-1.5 w-1.5 bg-current" aria-hidden="true" />
      {label}
    </span>
  );
  if (layout === "list") {
    return (
      <li className="flex items-center gap-4 border-b border-line py-3">
        <div className="h-12 w-16 shrink-0 overflow-hidden rounded-[2px] bg-surface">{thumb && <img src={thumb} alt="" className="h-full w-full object-cover" />}</div>
        <div className="min-w-0 flex-1">
          {open ? <Link to={open} className="font-medium hover:underline">{p.name}</Link> : <span className="font-medium">{p.name}</span>}
          {meta}
        </div>
        <span className="hidden text-[12px] text-muted sm:block">{when(p.updatedAt)}</span>
        {status}
        {actions}
      </li>
    );
  }
  return (
    <li className="overflow-hidden rounded-[2px] border border-line bg-raised">
      <Link to={open || "#"} className={`block aspect-[3/2] bg-surface ${open ? "" : "pointer-events-none"}`} aria-label={open ? `Open ${p.name}` : `${p.name} (not reconstructed yet)`}>
        {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-faint"><Icon name="cube" size={28} /></div>}
      </Link>
      <div className="space-y-1.5 p-3.5">
        <div className="flex items-start justify-between gap-2">
          <h3 className="truncate font-medium">{p.name}</h3>
          {status}
        </div>
        {meta}
        <div className="flex items-center justify-between pt-1">
          <span className="text-[11.5px] text-muted">{when(p.updatedAt)}</span>
          {actions}
        </div>
      </div>
    </li>
  );
}

export default function ProjectsPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [backend, setBackend] = useState(null);
  const [projects, setProjects] = useState(null);
  const [recent, setRecent] = useState([]);
  const [layout, setLayout] = useState("grid");
  const [renaming, setRenaming] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [retention, setRetention] = useState(null);

  const refresh = () =>
    api.listProjects().then((r) => {
      setProjects(r.projects);
      setRetention(r.retentionHours);
    }).catch((e) => toast(e.message, "error"));

  useEffect(() => {
    detectBackend().then((b) => {
      setBackend(b);
      if (b.available) refresh();
    });
    localdb.all("recent").then((r) => setRecent(r.map((x) => x.value).sort((a, b) => b.openedAt - a.openedAt).slice(0, 8)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!projects?.some((p) => p.status === "processing" || p.status === "queued")) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-10 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="serif text-[30px]">Projects</h1>
          <p className="mt-2 text-[14px] text-muted">
            {backend?.available
              ? `Your reconstructions on this server. Uploads and results are private to this browser and deleted after ${retention ? Math.round(retention / 24) : 3} days.`
              : "Projects live on a reconstruction server. This public site is viewer-only, so only recently opened scenes are listed."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {projects?.length > 0 && <Seg label="Layout" value={layout} onChange={setLayout} options={[{ value: "grid", label: "Grid" }, { value: "list", label: "List" }]} />}
          <Link to="/" className="btn btn-primary"><Icon name="upload" size={15} /> New scene</Link>
        </div>
      </div>

      {backend?.available && (
        <section className="mt-8">
          {projects === null ? (
            <div className="grid gap-4 sm:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="aspect-[3/2] skeleton rounded-[2px]" />)}</div>
          ) : projects.length === 0 ? (
            <div className="rounded-[3px] border border-dashed border-line-strong p-10 text-center">
              <p className="serif text-[18px]">No projects yet</p>
              <p className="mt-1 text-[13.5px] text-muted">Upload a video or photos in the studio to create your first scene.</p>
              <Link to="/" className="btn btn-primary mt-5">Create a 3D scene</Link>
            </div>
          ) : (
            <ul className={layout === "grid" ? "grid gap-4 sm:grid-cols-2 lg:grid-cols-3" : ""}>
              {projects.map((p) => (
                <ProjectCard
                  key={p.id}
                  p={p}
                  layout={layout}
                  onRename={setRenaming}
                  onDelete={setDeleting}
                  onDuplicate={async (x) => {
                    try {
                      await api.duplicateProject(x.id);
                      toast("Project duplicated with its inputs and settings", "success");
                      refresh();
                    } catch (e) {
                      toast(e.message, "error");
                    }
                  }}
                  onRetry={async (x) => {
                    try {
                      await api.retryJob(x.job.id);
                      try { localStorage.setItem("sceneform.activeJob", JSON.stringify({ id: x.job.id, projectId: x.id, mode: x.job.mode })); } catch { /* ignore */ }
                      navigate("/");
                    } catch (e) {
                      toast(e.message, "error");
                    }
                  }}
                />
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="mt-12">
        <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-muted">Recently opened</h2>
        {recent.length ? (
          <ul className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {recent.map((r) => (
              <li key={r.path}>
                <Link to={r.path} className="flex items-center gap-3 rounded-[2px] border border-line bg-raised p-2 hover:border-line-strong">
                  <img src={r.cover} alt="" className="h-10 w-14 rounded object-cover" />
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium">{r.title}</span>
                    <span className="text-[11.5px] text-muted">{r.kind === "example" ? "Example" : "Project"}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-[13px] text-muted">Nothing yet. <Link to="/explore" className="underline">Open an example</Link>.</p>
        )}
      </section>

      <Modal open={!!renaming} onClose={() => setRenaming(null)} title="Rename project">
        {renaming && (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const name = new FormData(e.currentTarget).get("name");
              try {
                await api.renameProject(renaming.id, name);
                setRenaming(null);
                refresh();
              } catch (err) {
                toast(err.message, "error");
              }
            }}
            className="space-y-4"
          >
            <input name="name" className="field" defaultValue={renaming.name} maxLength={80} autoFocus aria-label="Project name" />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn btn-ghost" onClick={() => setRenaming(null)}>Cancel</button>
              <button className="btn btn-primary">Save</button>
            </div>
          </form>
        )}
      </Modal>
      <Modal open={!!deleting} onClose={() => setDeleting(null)} title="Delete project?">
        {deleting && (
          <div className="space-y-4">
            <p className="text-[13.5px] text-ink-2">
              “{deleting.name}” and all its uploads, frames and reconstructions will be permanently deleted from the server. This can’t be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button className="btn btn-ghost" onClick={() => setDeleting(null)}>Cancel</button>
              <button
                className="btn btn-primary bg-bad text-white hover:bg-bad"
                onClick={async () => {
                  try {
                    await api.deleteProject(deleting.id);
                    toast("Project deleted", "success");
                    setDeleting(null);
                    refresh();
                  } catch (e) {
                    toast(e.message, "error");
                  }
                }}
              >
                Delete permanently
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
