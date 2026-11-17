"""Gaussian-splat training through maintained third-party trainers.

sceneform does not implement its own rasteriser/optimiser.  It prepares a
validated COLMAP dataset, picks a trainer that can actually run on this
machine, monitors training, evaluates held-out views, and post-processes the
result for the browser.

Supported trainers (capability-checked, never silently substituted):

* ``msplat`` – Metal 3DGS trainer for Apple Silicon (Apache-2.0).
* ``gsplat`` – CUDA 3DGS library from the Nerfstudio team (Apache-2.0),
  driven through its ``simple_trainer.py`` example when available.
* ``splatfacto`` – Nerfstudio's ``ns-train splatfacto`` CLI (Apache-2.0).

If none is available, :func:`detect_trainers` says so and high-quality mode
refuses to start — it never falls back to a fake result.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SH_C0 = 0.28209479177387814

QUALITY_PRESETS = {
    "performance": {"iterations": 7000, "sh_degree": 1, "max_splats_web": 400_000},
    "balanced": {"iterations": 15000, "sh_degree": 3, "max_splats_web": 800_000},
    "quality": {"iterations": 30000, "sh_degree": 3, "max_splats_web": 1_500_000},
}


@dataclass
class TrainerInfo:
    name: str
    available: bool
    device: str
    reason: str = ""


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def detect_trainers() -> list[TrainerInfo]:
    out = []
    apple = sys.platform == "darwin" and platform.machine() == "arm64"
    if _has_module("msplat") and apple:
        out.append(TrainerInfo("msplat", True, "metal"))
    else:
        out.append(TrainerInfo("msplat", False, "metal", "needs Apple Silicon and the msplat package"))
    cuda = False
    if _has_module("torch"):
        # Probe in a subprocess: importing torch here would clash with
        # pycolmap's OpenMP runtime in the worker process.
        try:
            r = subprocess.run([sys.executable, "-c", "import torch;print(torch.cuda.is_available())"],
                               capture_output=True, text=True, timeout=60)
            cuda = r.stdout.strip() == "True"
        except Exception:
            cuda = False
    gs = _has_module("gsplat") and cuda and bool(os.environ.get("SCENEFORM_GSPLAT_TRAINER"))
    out.append(TrainerInfo("gsplat", gs, "cuda",
                           "" if gs else "needs an NVIDIA GPU, the gsplat package, and SCENEFORM_GSPLAT_TRAINER pointing at simple_trainer.py"))
    ns = shutil.which("ns-train") is not None and cuda
    out.append(TrainerInfo("splatfacto", ns, "cuda", "" if ns else "needs an NVIDIA GPU and Nerfstudio (ns-train)"))
    return out


def best_trainer() -> TrainerInfo | None:
    for t in detect_trainers():
        if t.available:
            return t
    return None


# ------------------------------------------------------------- training
def train(
    dataset_dir: Path,
    out_dir: Path,
    preset: str = "balanced",
    trainer: str | None = None,
    iterations: int | None = None,
    progress=None,
    is_cancelled=lambda: False,
) -> dict:
    """Train a splat on a COLMAP-format dataset (``images/`` + ``sparse/``).

    Returns metadata including held-out evaluation metrics when the trainer
    provides them.
    """
    cfg = dict(QUALITY_PRESETS[preset])
    if iterations:
        cfg["iterations"] = iterations
    info = next((t for t in detect_trainers() if t.name == trainer), None) if trainer else best_trainer()
    if info is None or not info.available:
        raise RuntimeError(
            "High-quality reconstruction needs a supported GPU trainer, and none is available here. "
            + ("; ".join(f"{t.name}: {t.reason}" for t in detect_trainers()))
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    if info.name == "msplat":
        return _train_msplat(dataset_dir, out_dir, cfg, progress, is_cancelled)
    if info.name == "gsplat":
        return _train_subprocess_gsplat(dataset_dir, out_dir, cfg, progress, is_cancelled)
    return _train_subprocess_splatfacto(dataset_dir, out_dir, cfg, progress, is_cancelled)


class Cancelled(Exception):
    pass


def _train_msplat(dataset_dir, out_dir, cfg, progress, is_cancelled) -> dict:
    import msplat

    t0 = time.time()
    ds = msplat.load_dataset(str(dataset_dir), eval_mode=True)
    tc = msplat.TrainingConfig()
    tc.iterations = cfg["iterations"]
    tc.sh_degree = cfg["sh_degree"]
    tc.num_downscales = 1
    tc.bg_color = [0.0, 0.0, 0.0]
    tc.keep_crs = True  # stay in the COLMAP frame so scene alignment applies
    trainer = msplat.GaussianTrainer(ds, tc)
    total = cfg["iterations"]
    last = {"t": 0.0}

    def cb(s):
        if is_cancelled():
            raise Cancelled()
        now = time.time()
        if progress and now - last["t"] > 1.0:
            last["t"] = now
            progress(s.iteration / total, f"Optimising splats: step {s.iteration:,} of {total:,}, {s.splat_count:,} splats")

    try:
        trainer.train(cb, callback_every=100)
    except Cancelled:
        raise RuntimeError("cancelled")
    raw = out_dir / "splat_raw.ply"
    trainer.export_ply(str(raw))
    metrics = {}
    try:
        m = trainer.evaluate()
        metrics = {k: float(v) for k, v in (m.items() if isinstance(m, dict) else vars(m).items())
                   if isinstance(v, (int, float))}
    except Exception as exc:  # evaluation is best-effort, never fabricated
        metrics = {"error": str(exc)}
    return {
        "trainer": "msplat",
        "device": "metal",
        "iterations": total,
        "sh_degree": cfg["sh_degree"],
        "seconds": round(time.time() - t0, 1),
        "train_views": int(ds.num_train),
        "test_views": int(ds.num_test),
        "heldout_metrics": metrics,
        "raw_ply": raw.name,
        "splats": int(trainer.splat_count),
        "max_splats_web": cfg["max_splats_web"],
    }


def _run_logged(cmd, log_path, progress, is_cancelled, total_steps, step_key="Step") -> int:
    with open(log_path, "w") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            log.write(line)
            if is_cancelled():
                proc.terminate()
                raise RuntimeError("cancelled")
            if progress and step_key in line:
                digits = [int(t) for t in line.replace("/", " ").split() if t.isdigit()]
                if digits:
                    progress(min(1.0, digits[0] / total_steps), line.strip()[:120])
        return proc.wait()


def _train_subprocess_gsplat(dataset_dir, out_dir, cfg, progress, is_cancelled) -> dict:
    script = os.environ["SCENEFORM_GSPLAT_TRAINER"]
    cmd = [sys.executable, script, "default", "--data_dir", str(dataset_dir), "--result_dir", str(out_dir),
           "--max_steps", str(cfg["iterations"]), "--sh_degree", str(cfg["sh_degree"]), "--disable_viewer",
           "--save_ply", "--ply_steps", str(cfg["iterations"])]
    t0 = time.time()
    code = _run_logged(cmd, out_dir / "train.log", progress, is_cancelled, cfg["iterations"])
    if code != 0:
        raise RuntimeError(f"gsplat trainer exited with code {code}; see train.log")
    plys = sorted((out_dir / "ply").glob("*.ply"))
    if not plys:
        raise RuntimeError("gsplat finished without writing a PLY")
    shutil.copy(plys[-1], out_dir / "splat_raw.ply")
    stats = {}
    for f in sorted((out_dir / "stats").glob("val_step*.json")):
        stats = json.loads(f.read_text())
    return {"trainer": "gsplat", "device": "cuda", "iterations": cfg["iterations"], "sh_degree": cfg["sh_degree"],
            "seconds": round(time.time() - t0, 1), "heldout_metrics": stats, "raw_ply": "splat_raw.ply",
            "max_splats_web": cfg["max_splats_web"]}


def _train_subprocess_splatfacto(dataset_dir, out_dir, cfg, progress, is_cancelled) -> dict:
    cmd = ["ns-train", "splatfacto", "--output-dir", str(out_dir), "--max-num-iterations", str(cfg["iterations"]),
           "--viewer.quit-on-train-completion", "True", "colmap", "--data", str(dataset_dir),
           "--colmap-path", "sparse"]
    t0 = time.time()
    code = _run_logged(cmd, out_dir / "train.log", progress, is_cancelled, cfg["iterations"])
    if code != 0:
        raise RuntimeError(f"ns-train exited with code {code}; see train.log")
    cfgs = sorted(out_dir.rglob("config.yml"))
    if not cfgs:
        raise RuntimeError("splatfacto run produced no config")
    exp = out_dir / "export"
    subprocess.run(["ns-export", "gaussian-splat", "--load-config", str(cfgs[-1]), "--output-dir", str(exp)], check=True)
    shutil.copy(exp / "splat.ply", out_dir / "splat_raw.ply")
    return {"trainer": "splatfacto", "device": "cuda", "iterations": cfg["iterations"], "sh_degree": cfg["sh_degree"],
            "seconds": round(time.time() - t0, 1), "heldout_metrics": {}, "raw_ply": "splat_raw.ply",
            "max_splats_web": cfg["max_splats_web"]}


# ------------------------------------------------------ post-processing
def read_splat_ply(path: Path) -> dict[str, np.ndarray]:
    from .export import read_ply

    v = read_ply(path)
    required = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3", "opacity",
                "f_dc_0", "f_dc_1", "f_dc_2"]
    missing = [k for k in required if k not in v]
    if missing:
        raise ValueError(f"not a 3D Gaussian splat PLY (missing {', '.join(missing)})")
    return v


def splat_stats(v: dict[str, np.ndarray]) -> dict:
    op = 1 / (1 + np.exp(-v["opacity"].astype(np.float64)))
    sc = np.exp(np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], 1).astype(np.float64))
    n_rest = sum(1 for k in v if k.startswith("f_rest_"))
    return {
        "count": int(len(op)),
        "sh_rest_coeffs": n_rest,
        "opacity_median": float(np.median(op)),
        "low_opacity_fraction": float((op < 0.05).mean()),
        "scale_median": float(np.median(sc.max(1))),
        "finite": bool(all(np.isfinite(v[k]).all() for k in ("x", "y", "z", "opacity"))),
    }


def prune_for_web(src: Path, dst: Path, sim=None, max_splats: int = 800_000, min_opacity: float = 0.02,
                  keep_sh: bool = False, bounds_radius: float | None = None) -> dict:
    """Make a viewer-friendly splat PLY.

    * applies the scene-alignment similarity (positions, rotations, scales),
    * drops nearly transparent and non-finite splats and far floaters,
    * keeps the most visible splats (opacity × area) up to ``max_splats``,
    * optionally drops view-dependent SH bands to shrink the file 4×.
    """
    v = read_splat_ply(src)
    pos = np.stack([v["x"], v["y"], v["z"]], 1).astype(np.float64)
    q = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], 1).astype(np.float64)  # w x y z
    q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-12
    logs = np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], 1).astype(np.float64)
    if sim is not None:
        pos = sim.apply(pos)
        logs = logs + np.log(sim.s)
        qs = _matrix_to_wxyz(sim.R)
        q = _quat_mul(qs, q)
    op = 1 / (1 + np.exp(-v["opacity"].astype(np.float64)))
    keep = np.isfinite(pos).all(1) & np.isfinite(logs).all(1) & (op >= min_opacity)
    if bounds_radius:
        c = np.median(pos[keep], axis=0)
        keep &= np.linalg.norm(pos - c, axis=1) < bounds_radius
    idx = np.where(keep)[0]
    if len(idx) > max_splats:
        area = np.exp(logs[idx]).prod(1) ** (2 / 3)
        score = op[idx] * area
        idx = idx[np.argsort(-score)[:max_splats]]
    fields = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
    rest = sorted((k for k in v if k.startswith("f_rest_")), key=lambda k: int(k.split("_")[-1])) if keep_sh else []
    fields += rest + ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    arr = np.zeros(len(idx), dtype=[(f, "<f4") for f in fields])
    arr["x"], arr["y"], arr["z"] = pos[idx].T
    for k in ["f_dc_0", "f_dc_1", "f_dc_2", "opacity"] + rest:
        arr[k] = v[k][idx]
    arr["scale_0"], arr["scale_1"], arr["scale_2"] = logs[idx].T
    arr["rot_0"], arr["rot_1"], arr["rot_2"], arr["rot_3"] = q[idx].T
    header = "ply\nformat binary_little_endian 1.0\n" + f"element vertex {len(idx)}\n"
    header += "".join(f"property float {f}\n" for f in fields) + "end_header\n"
    with open(dst, "wb") as fh:
        fh.write(header.encode("ascii"))
        fh.write(arr.tobytes())
    return {"input": int(len(op)), "output": int(len(idx)), "sh_kept": bool(rest), "bytes": dst.stat().st_size}


def _matrix_to_wxyz(R):
    from ..geometry.cameras import rotation_to_quaternion_xyzw

    x, y, z, w = rotation_to_quaternion_xyzw(R)
    return np.array([w, x, y, z])


def _quat_mul(a, b):
    """Hamilton product a ⊗ b for a single ``a`` and an array ``b`` (wxyz)."""
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b.T
    return np.stack([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ], 1)
