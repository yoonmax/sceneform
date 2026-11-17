"""Reconstruct the public example scenes and publish them to the frontend.

Every example is produced by this repository's pipeline from openly licensed
source media.  Raw media is not redistributed (except the selected frames
shown in the viewer, under the source license); see ``examples/SOURCES.md``.

    python scripts/build_examples.py [example-id ...]
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.runner import Context, RunConfig, run  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
RUNS = ROOT / "data" / "runs"
PUBLIC = ROOT / "frontend" / "public" / "examples"

EXAMPLES = [
    {
        "id": "plaster-skull",
        "title": "Plaster skull",
        "category": "Decorative sculpture",
        "summary": "75 handheld photos circling a plaster skull on a stand.",
        "inputs": lambda: sorted((RAW / "skull").glob("[0-9][0-9].JPG")),
        "config": dict(mode="high", splat_iterations=4000, splat_preset="balanced"),
        "license": {
            "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": '"Photogrammetry Test Set: Skull - Cameramoves - Weak Light - No Background" by alansartlog',
            "source": "https://gitlab.com/photogrammetry-test-sets/skull-cameramoves-weak-light-no-background",
            "author": "alansartlog", "authorUrl": "https://alansartlog.com",
        },
    },
    {
        "id": "painted-die",
        "title": "Painted die",
        "category": "Tabletop object",
        "summary": "34 turntable photos of a watercolour-painted die on white.",
        "inputs": lambda: sorted((RAW / "dice").glob("[0-9][0-9].JPG")),
        "config": dict(mode="high", splat_iterations=4000, splat_preset="balanced"),
        "license": {
            "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": '"Photogrammetry Test Set: Dice - Turntable - Strong Lights - Thin Messy Watercolors" by alansartlog',
            "source": "https://gitlab.com/photogrammetry-test-sets/dice-turntable-strong-lights-thin-messy-watercolors",
            "author": "alansartlog", "authorUrl": "https://alansartlog.com",
        },
    },
    {
        "id": "liberation-hall",
        "title": "Hall of Liberation",
        "category": "Room interior",
        "summary": "A 57-second handheld phone video inside the Befreiungshalle, Kelheim.",
        "inputs": lambda: [RAW / "videos" / "befreiungshalle.mp4"],
        "config": dict(mode="high", splat_iterations=5000, sample_fps=3.0, max_frames=90, web_max_splats=350_000, web_keep_sh=False),
        "license": {
            "name": "Public domain", "url": "https://commons.wikimedia.org/wiki/File:Kelheim_Befreiungshalle_Video.ogv",
            "attribution": "Kelheim Befreiungshalle Video by User:Mattes (Wikimedia Commons), released into the public domain",
            "source": "https://commons.wikimedia.org/wiki/File:Kelheim_Befreiungshalle_Video.ogv",
            "author": "Mattes", "authorUrl": "https://commons.wikimedia.org/wiki/User:Mattes",
            "note": "Transcoded from Ogg Theora to MP4 before processing.",
        },
    },
    {
        "id": "geneva-sculpture",
        "title": "Seated figure, Geneva",
        "category": "Outdoor sculpture",
        "summary": "A 10-second turntable video of a stone sculpture by Theodora Barazzone.",
        "inputs": lambda: [RAW / "videos" / "barazzone.mp4"],
        "config": dict(mode="high", splat_iterations=4000, sample_fps=10.0, max_frames=100),
        "license": {
            "name": "CC BY-SA 3.0 FR", "url": "https://creativecommons.org/licenses/by-sa/3.0/fr/deed.en",
            "attribution": "Sculpture by Theodora Barazzone at Cimetière des Rois (turntable video) by Rama, Wikimedia Commons",
            "source": "https://commons.wikimedia.org/wiki/File:Sculpture_by_Theodora_Barazzone_at_Cimeti%C3%A8re_des_Rois-turntable-0001-0250.ogv",
            "author": "Rama",
            "note": ("The source video is itself a rendered turntable of a 3D scan, not raw camera footage. "
                     "Derived outputs in this folder are shared under the same license."),
        },
    },
]

SKIP_PUBLIC = {"points.ply", "mesh.obj"}


def publish(ex: dict, run_dir: Path) -> dict:
    src = run_dir / "outputs"
    dst = PUBLIC / ex["id"]
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if n in SKIP_PUBLIC])
    m = json.loads((dst / "manifest.json").read_text())
    m["id"] = ex["id"]
    m["license"] = ex["license"]
    m["category"] = ex["category"]
    m["summary"] = ex["summary"]
    m["example"] = True
    if m.get("mesh"):
        m["mesh"].pop("obj", None)
    m["pointCloud"].pop("ply", None)
    # Never publish absolute local paths.
    m["processing"]["config"] = {k: v for k, v in m["processing"]["config"].items() if k not in ("exclude", "order")}
    (dst / "manifest.json").write_text(json.dumps(m, indent=1))
    lic = ex["license"]
    (dst / "ATTRIBUTION.txt").write_text(
        f"{lic['attribution']}\nLicense: {lic['name']} ({lic['url']})\nSource: {lic['source']}\n"
        + (f"Note: {lic['note']}\n" if lic.get("note") else "")
        + "Reconstruction (point cloud, cameras, depth, mesh, splat) produced with sceneform from the source above.\n"
    )
    size = sum(p.stat().st_size for p in dst.rglob("*") if p.is_file())
    return {
        "id": ex["id"], "title": ex["title"], "category": ex["category"], "summary": ex["summary"],
        "cover": f"examples/{ex['id']}/cover.jpg", "manifest": f"examples/{ex['id']}/manifest.json",
        "points": m["pointCloud"]["stats"]["count"], "cameras": m["cameras"]["count"],
        "hasSplat": bool(m.get("splat")), "hasMesh": bool(m.get("mesh")),
        "sourceType": m["source"]["type"], "license": lic["name"], "bytes": size,
        "quality": m["quality"]["score"],
        "inputFrames": m["metrics"]["inputFrames"],
        "reprojectionPx": m["metrics"]["sparseReprojectionErrorPx"]["mean"],
        "coverageDeg": m["metrics"]["coverageDeg"],
        "splatPsnr": (m["metrics"].get("splatHeldout") or {}).get("psnr"),
        "splatCount": m["splat"]["stats"]["count"] if m.get("splat") else None,
        "meshFaces": m["mesh"]["diagnostics"]["faces"] if m.get("mesh") else None,
        "seconds": m["processing"]["totalSeconds"],
        "author": ex["license"]["author"],
    }


def main(ids: list[str]) -> int:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    index_path = PUBLIC / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"examples": []}
    by_id = {e["id"]: e for e in index["examples"]}
    for ex in EXAMPLES:
        if ids and ex["id"] not in ids:
            continue
        inputs = ex["inputs"]()
        print(f"== {ex['id']}: {len(inputs)} input file(s)", flush=True)
        t0 = time.time()
        last = {"t": 0}

        def on(ev):
            if ev["type"] == "stage" or ev["type"] == "log" or time.time() - last["t"] > 10:
                last["t"] = time.time()
                print(f"  [{time.time() - t0:6.1f}s] {ev.get('label') or ev.get('message')}", flush=True)

        cfg = RunConfig(title=ex["title"], **ex["config"])
        try:
            run(inputs, RUNS / ex["id"], cfg, Context(on))
        except Exception as exc:  # report and continue with the next example
            print(f"  FAILED: {exc}", flush=True)
            continue
        by_id[ex["id"]] = publish(ex, RUNS / ex["id"])
        print(f"  published {by_id[ex['id']]['bytes'] / 1e6:.1f} MB", flush=True)
    order = [e["id"] for e in EXAMPLES]
    index["examples"] = sorted(by_id.values(), key=lambda e: order.index(e["id"]) if e["id"] in order else 99)
    index_path.write_text(json.dumps(index, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
