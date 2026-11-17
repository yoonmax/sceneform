"""End-to-end reconstruction orchestration.

The runner is HTTP-agnostic: the worker, the CLI (``scripts/reconstruct.py``)
and the example-building script all call :func:`run`.  Progress is reported
per *real* stage; a fraction is only given when the stage can measure one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..config import settings
from . import point_cloud as pcm
from .alignment import canonical_frame, coverage_degrees
from .ingest import IngestOptions, ingest, save_ingest
from .sparse_model import SparseModel

STAGES = [
    ("validating", "Checking your files"),
    ("extracting", "Preparing frames"),
    ("estimating_geometry", "Recovering camera positions"),
    ("estimating_depth", "Estimating depth"),
    ("building_point_cloud", "Building the point cloud"),
    ("building_mesh", "Building a surface mesh"),
    ("training_splats", "Training the Gaussian splat"),
    ("preparing_output", "Preparing your scene"),
]

PIPELINE_VERSION = "0.4.0"


@dataclass
class RunConfig:
    mode: str = "quick"  # quick | high
    title: str = "Untitled scene"
    sample_fps: float = 4.0
    trim_start: float = 0.0
    trim_end: float | None = None
    max_frames: int = 120
    exclude: list[str] = field(default_factory=list)
    order: list[str] | None = None
    drop_blurry: bool = True
    working_max_side: int = 1600
    max_features: int = 6000
    matcher: str = "auto"  # auto | exhaustive | sequential
    depth_max_side: int = 640
    confidence_floor: float = 0.2  # points below this are not even shipped
    voxel_fraction: float = 1 / 500  # voxel size relative to scene radius
    outlier_std: float = 2.0
    mesh: bool = True
    mesh_resolution: int = 192
    splat_preset: str = "balanced"  # performance | balanced | quality
    splat_iterations: int | None = None
    splat_trainer: str | None = None
    web_max_points: int = 1_200_000
    web_max_splats: int | None = None  # defaults to the preset's budget
    web_keep_sh: bool = True  # False keeps only base colour (≈4× smaller)


class Cancelled(Exception):
    pass


class Context:
    """Progress/cancellation hooks supplied by the caller."""

    def __init__(self, on_event: Callable[[dict], None] | None = None, is_cancelled: Callable[[], bool] | None = None):
        self._on = on_event or (lambda e: None)
        self._cancelled = is_cancelled or (lambda: False)
        self.stage_name = None
        self.timings: dict[str, float] = {}
        self._t = None

    def stage(self, name: str) -> None:
        self.check()
        now = time.time()
        if self.stage_name and self._t:
            self.timings[self.stage_name] = round(now - self._t, 2)
        self.stage_name, self._t = name, now
        label = dict(STAGES).get(name, name)
        self._on({"type": "stage", "stage": name, "label": label, "progress": None})

    def finish(self) -> None:
        if self.stage_name and self._t:
            self.timings[self.stage_name] = round(time.time() - self._t, 2)

    def progress(self, fraction: float | None, message: str = "") -> None:
        self.check()
        self._on({"type": "progress", "stage": self.stage_name, "progress": fraction, "message": message})

    def log(self, message: str, level: str = "info") -> None:
        self._on({"type": "log", "stage": self.stage_name, "level": level, "message": message})

    def check(self) -> None:
        if self._cancelled():
            raise Cancelled()

    def cancelled(self) -> bool:
        return self._cancelled()


def _versions() -> dict:
    out = {"sceneform": PIPELINE_VERSION}
    for mod in ("numpy", "cv2", "pycolmap", "scipy"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:
            pass
    try:
        from importlib.metadata import version

        out["msplat"] = version("msplat")
        out["transformers"] = version("transformers")
        out["torch"] = version("torch")
    except Exception:
        pass
    return out


def run_depth_subprocess(images_dir: Path, names: list[str], out_dir: Path, max_side: int, ctx: Context) -> None:
    cmd = [sys.executable, "-m", "app.pipeline.depth_infer", "--images", str(images_dir), "--names",
           json.dumps(names), "--out", str(out_dir), "--model", settings.depth_model, "--max-side", str(max_side)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            cwd=str(Path(__file__).resolve().parents[2]))
    device = None
    for line in proc.stdout:
        if ctx.cancelled():
            proc.terminate()
            raise Cancelled()
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "loaded":
            device = ev.get("device")
            ctx.log(f"Depth model loaded on {device}")
        elif ev.get("event") == "frame":
            ctx.progress((ev["index"] + 1) / ev["total"], f"Estimated depth for {ev['index'] + 1} of {ev['total']} views")
    code = proc.wait()
    if code != 0:
        err = proc.stderr.read()[-2000:]
        raise RuntimeError(f"Depth estimation failed: {err.strip().splitlines()[-1] if err.strip() else code}")
    return device


def run(inputs: list[Path], run_dir: Path, cfg: RunConfig, ctx: Context | None = None) -> dict:
    """Execute the pipeline. Writes ``run_dir/outputs/manifest.json``."""
    ctx = ctx or Context()
    t_start = time.time()
    run_dir.mkdir(parents=True, exist_ok=True)
    work = run_dir / "work"
    out = run_dir / "outputs"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (run_dir / "config.json").write_text(json.dumps(asdict(cfg), indent=1))

    # ---------------------------------------------------------- validating
    ctx.stage("validating")
    if cfg.mode == "high":
        from .gaussian_splat import detect_trainers

        trainers = detect_trainers()
        if not any(t.available and (cfg.splat_trainer in (None, t.name)) for t in trainers):
            reasons = "; ".join(f"{t.name}: {t.reason}" for t in trainers)
            raise RuntimeError(f"High-quality mode needs a supported GPU trainer, none is available ({reasons}).")
        ctx.log("Splat trainers: " + ", ".join(f"{t.name}={'yes' if t.available else 'no'}" for t in trainers))

    # ---------------------------------------------------------- extracting
    ctx.stage("extracting")
    frames_dir = work / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    ing = ingest(inputs, frames_dir, IngestOptions(
        trim_start=cfg.trim_start, trim_end=cfg.trim_end, sample_fps=cfg.sample_fps, max_frames=cfg.max_frames,
        exclude=cfg.exclude, order=cfg.order, drop_blurry=cfg.drop_blurry, working_max_side=cfg.working_max_side,
    ), progress=ctx.progress)
    save_ingest(ing, work / "ingest.json")
    ctx.log(f"Prepared {len(ing.frame_names)} frames; input quality {ing.quality['score']}/100")

    # -------------------------------------------------- estimating_geometry
    ctx.stage("estimating_geometry")
    from .sfm_colmap import SfMError, run_colmap

    sequential = cfg.matcher == "sequential" or (cfg.matcher == "auto" and len(ing.frame_names) > 150)
    try:
        model, und_dir = run_colmap(
            frames_dir, work / "colmap", ing.frame_names, single_camera=ing.single_camera,
            focal_px=ing.focal_px, sequential=sequential, max_features=cfg.max_features,
            progress=lambda s, f, m: ctx.progress(f, m), is_cancelled=ctx.cancelled,
        )
    except SfMError as exc:
        if str(exc) == "cancelled":
            raise Cancelled()
        raise
    ctx.check()
    if len(model.views) < 3:
        raise RuntimeError("Only a couple of views could be placed. The capture needs more overlap between views.")
    reg_ratio = len(model.views) / len(ing.frame_names)
    ctx.log(f"Registered {len(model.views)}/{len(ing.frame_names)} views, {len(model.points)} sparse points")
    # msplat & most trainers expect sparse/0
    (und_dir / "sparse" / "0").mkdir(exist_ok=True)
    for f in (und_dir / "sparse").glob("*.bin"):
        shutil.copy(f, und_dir / "sparse" / "0" / f.name)

    sim, align_info = canonical_frame(model)
    aligned = model.transformed(sim)
    aligned.save(work / "sparse_aligned")
    coverage = coverage_degrees(aligned)
    # Coverage "around the subject" only means something when cameras look
    # inward (object captures); for rooms the cameras face outward.
    focus = np.median(aligned.points, axis=0)
    inward = float(np.mean([v.camera.forward @ ((focus - v.camera.center) / (np.linalg.norm(focus - v.camera.center) + 1e-9))
                            for v in aligned.views]))
    if inward > 0.6 and coverage < 60:
        ing.quality["findings"].append({
            "code": "one-sided", "severity": "warning", "frames": [], "measurement": {"coverageDeg": coverage},
            "message": f"Your camera covered about {coverage:.0f}° around the subject. Record all the way around it for a complete model.",
        })
    ing.quality["capture"] = {"inwardFacing": inward > 0.6, "coverageDeg": coverage}

    # ---------------------------------------------------- estimating_depth
    ctx.stage("estimating_depth")
    names = [v.name for v in model.views]
    disp_dir = work / "disparity"
    device = run_depth_subprocess(und_dir / "images", names, disp_dir, cfg.depth_max_side, ctx)

    # ------------------------------------------------ building_point_cloud
    ctx.stage("building_point_cloud")
    from .fusion import FusionParams, fuse

    images, disps = [], []
    for v in aligned.views:
        d = np.load(disp_dir / f"{Path(v.name).stem}.npy")
        im = Image.open(und_dir / "images" / v.name).convert("RGB").resize((d.shape[1], d.shape[0]), Image.Resampling.LANCZOS)
        images.append(np.asarray(im))
        disps.append(d)
    fres = fuse(aligned, images, disps, FusionParams(), progress=lambda f, m: ctx.progress(0.8 * f, m))
    cloud = pcm.remove_nonfinite(fres.cloud)
    cloud = pcm.filter_confidence(cloud, cfg.confidence_floor)
    bounds0 = pcm.robust_bounds(cloud.points)
    voxel = max(bounds0["radius"], 1e-6) * cfg.voxel_fraction
    cloud = pcm.voxel_downsample(cloud, voxel)
    ctx.progress(0.88, "Removing outliers")
    cloud = pcm.statistical_outlier_removal(cloud, k=16, std_ratio=cfg.outlier_std)
    while len(cloud) > cfg.web_max_points:
        voxel *= 1.25
        cloud = pcm.voxel_downsample(cloud, voxel)
    ctx.progress(0.95, "Estimating normals")
    cloud = pcm.estimate_normals(cloud, k=12, viewpoints=aligned.centers)
    from ..geometry.validation import validate_point_cloud

    vrep = validate_point_cloud(cloud.points, cloud.colors)
    if not vrep.ok:
        raise RuntimeError("Point cloud validation failed: " + "; ".join(vrep.errors))

    # ------------------------------------------------------- building_mesh
    mesh = None
    if cfg.mesh:
        ctx.stage("building_mesh")
        from .mesh import keep_largest_components, tsdf_fuse

        b = pcm.robust_bounds(cloud.points, 0.5, 99.5)
        pad = 0.05 * (np.array(b["max"]) - np.array(b["min"]))
        try:
            mesh = tsdf_fuse(fres.views, np.array(b["min"]) - pad, np.array(b["max"]) + pad,
                             resolution=cfg.mesh_resolution, progress=ctx.progress)
            if mesh is not None:
                mesh = keep_largest_components(mesh)
        except MemoryError:
            ctx.log("Mesh skipped: not enough memory for the requested resolution", "warning")
            mesh = None
        if mesh is None:
            ctx.log("Not enough consistent depth to extract a surface mesh", "warning")

    # ----------------------------------------------------- training_splats
    splat = None
    if cfg.mode == "high":
        ctx.stage("training_splats")
        from .gaussian_splat import train

        splat = train(und_dir, work / "splat", preset=cfg.splat_preset, trainer=cfg.splat_trainer,
                      iterations=cfg.splat_iterations, progress=ctx.progress, is_cancelled=ctx.cancelled)

    # ---------------------------------------------------- preparing_output
    ctx.stage("preparing_output")
    from .web_package import package

    manifest = package(
        out_dir=out, cfg=cfg, model=aligned, raw_model=model, sim=sim, align_info=align_info, cloud=cloud,
        fusion=fres, images_dir=und_dir / "images", ingest=ing, mesh=mesh, splat=splat,
        splat_dir=work / "splat", coverage=coverage, depth_device=device,
        versions=_versions(), timings=ctx.timings, registration_ratio=reg_ratio, progress=ctx.progress,
    )
    ctx.finish()
    manifest["processing"]["stageSeconds"] = ctx.timings
    manifest["processing"]["totalSeconds"] = round(time.time() - t_start, 1)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest
