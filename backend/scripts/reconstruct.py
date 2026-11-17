"""Run the sceneform pipeline from the command line.

    python scripts/reconstruct.py INPUT... --out runs/my-scene [--mode high]

INPUT may be a video file, image files, or a directory of images.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.runner import Context, RunConfig, run  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def collect(paths: list[str]) -> list[Path]:
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() in IMAGE_EXT)
        else:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="sceneform reconstruction")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--mode", choices=["quick", "high"], default="quick")
    ap.add_argument("--title", default="Untitled scene")
    ap.add_argument("--preset", choices=["performance", "balanced", "quality"], default="balanced")
    ap.add_argument("--iterations", type=int)
    ap.add_argument("--max-frames", type=int, default=120)
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--no-mesh", action="store_true")
    ap.add_argument("--mesh-resolution", type=int, default=192)
    ap.add_argument("--working-size", type=int, default=1600)
    args = ap.parse_args()

    cfg = RunConfig(mode=args.mode, title=args.title, splat_preset=args.preset, splat_iterations=args.iterations,
                    max_frames=args.max_frames, sample_fps=args.fps, mesh=not args.no_mesh,
                    mesh_resolution=args.mesh_resolution, working_max_side=args.working_size)
    t0 = time.time()
    state = {"stage": None, "last": 0.0}

    def on_event(ev):
        now = time.time()
        if ev["type"] == "stage":
            state["stage"] = ev["stage"]
            print(f"[{now - t0:7.1f}s] ▸ {ev['label']}", flush=True)
        elif ev["type"] == "log":
            print(f"[{now - t0:7.1f}s]   {ev['message']}", flush=True)
        elif ev["type"] == "progress" and now - state["last"] > 2:
            state["last"] = now
            pct = "" if ev["progress"] is None else f"{100 * ev['progress']:5.1f}% "
            print(f"[{now - t0:7.1f}s]   {pct}{ev['message']}", flush=True)

    manifest = run(collect(args.inputs), args.out, cfg, Context(on_event))
    m = manifest["metrics"]
    print(json.dumps({
        "registered": f"{m['registeredViews']}/{m['inputFrames']}",
        "points": manifest["pointCloud"]["stats"]["count"],
        "reprojection_px": m["sparseReprojectionErrorPx"],
        "coverage_deg": round(m["coverageDeg"], 1),
        "mesh": bool(manifest["mesh"]),
        "splat": manifest["splat"]["stats"] if manifest["splat"] else None,
        "splat_heldout": m["splatHeldout"],
        "seconds": manifest["processing"]["totalSeconds"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
