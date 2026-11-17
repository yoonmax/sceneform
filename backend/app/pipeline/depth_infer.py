"""Monocular relative-depth inference (runs in its own process).

PyTorch and pycolmap bundle different OpenMP runtimes, so this stage is
launched as ``python -m app.pipeline.depth_infer`` and communicates through
files.  The model output is *relative inverse depth* (affine-invariant
disparity); it has no metric meaning until :mod:`.fusion` aligns it to the
SfM geometry.

Default model: Depth Anything V2 Small (Apache-2.0).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


def pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--names", required=True, help="JSON list of image file names")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", default="depth-anything/Depth-Anything-V2-Small-hf")
    ap.add_argument("--max-side", type=int, default=640)
    args = ap.parse_args(argv)

    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    names = json.loads(args.names)
    args.out.mkdir(parents=True, exist_ok=True)
    device = pick_device()
    t0 = time.time()
    processor = AutoImageProcessor.from_pretrained(args.model)
    model = AutoModelForDepthEstimation.from_pretrained(args.model).to(device).eval()
    print(json.dumps({"event": "loaded", "device": device, "seconds": round(time.time() - t0, 2)}), flush=True)

    for i, name in enumerate(names):
        img = Image.open(args.images / name).convert("RGB")
        w, h = img.size
        s = min(1.0, args.max_side / max(w, h))
        ow, oh = int(round(w * s)), int(round(h * s))
        inputs = processor(images=img, return_tensors="pt").to(device)
        with torch.no_grad():
            pred = model(**inputs).predicted_depth  # [1,h',w'] relative disparity
        pred = torch.nn.functional.interpolate(pred[:, None], size=(oh, ow), mode="bicubic", align_corners=False)[0, 0]
        disp = pred.float().cpu().numpy()
        np.save(args.out / f"{Path(name).stem}.npy", disp.astype(np.float32))
        print(json.dumps({"event": "frame", "index": i, "total": len(names), "name": name}), flush=True)
    print(json.dumps({"event": "done", "device": device, "seconds": round(time.time() - t0, 2)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
