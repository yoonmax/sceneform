"""Turn uploaded photos or a video into a normalised, analysed frame set."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from ..config import settings
from .frame_selection import SelectionParams, order_photos, select_keyframes
from .media import (IMAGE_KINDS, VIDEO_KINDS, MediaError, decode_video_frames, focal_prior_px,
                    load_image, probe_video, sniff_file)
from .quality import build_report, frame_metrics, orb_features, pair_metrics

WORKING_MAX_SIDE = 1600


@dataclass
class IngestOptions:
    trim_start: float = 0.0
    trim_end: float | None = None
    sample_fps: float = 4.0
    max_frames: int = 120
    min_frames: int = 12
    exclude: list[str] = field(default_factory=list)  # input names the user removed
    order: list[str] | None = None  # explicit order chosen by the user
    drop_blurry: bool = True
    working_max_side: int = WORKING_MAX_SIDE


@dataclass
class IngestResult:
    frame_names: list[str]
    source: dict
    quality: dict
    selection: dict
    focal_px: float | None
    focal_source: str
    single_camera: bool


def ingest(inputs: list[Path], frames_dir: Path, opts: IngestOptions, progress=None) -> IngestResult:
    frames_dir.mkdir(parents=True, exist_ok=True)
    kinds = [sniff_file(p) for p in inputs]
    videos = [p for p, k in zip(inputs, kinds) if k in VIDEO_KINDS]
    images = [p for p, k in zip(inputs, kinds) if k in IMAGE_KINDS]
    if videos and images:
        raise MediaError("Please upload either one video or a set of photos, not both.")
    if len(videos) > 1:
        raise MediaError("Please upload a single video.")
    if videos:
        return _ingest_video(videos[0], frames_dir, opts, progress)
    if images:
        return _ingest_photos(images, frames_dir, opts, progress)
    raise MediaError("No supported files were found. Use MP4, MOV, WebM, JPEG, PNG or WebP.")


def _save(img: np.ndarray, path: Path) -> None:
    Image.fromarray(img).save(path, quality=93)


def _ingest_video(path: Path, frames_dir: Path, opts: IngestOptions, progress) -> IngestResult:
    info = probe_video(path)
    if info.duration > settings.max_video_seconds:
        raise MediaError(f"This video is {info.duration:.0f}s long. Please trim it to under {settings.max_video_seconds:.0f}s.")
    if progress:
        progress(None, f"Decoding video at {opts.sample_fps:g} frames per second")
    frames, stamps = [], []
    for ts, fr in decode_video_frames(path, opts.sample_fps, opts.working_max_side, opts.trim_start, opts.trim_end):
        frames.append(fr)
        stamps.append(ts)
    if len(frames) < 3:
        raise MediaError("The video segment is too short to reconstruct. Try a longer clip.")
    if progress:
        progress(None, f"Selecting sharp, well-spaced views from {len(frames)} candidates")
    sel = select_keyframes(frames, stamps, SelectionParams(min_frames=opts.min_frames, max_frames=opts.max_frames))
    names = []
    for k, i in enumerate(sel.selected):
        name = f"frame_{k:04d}.jpg"
        _save(frames[i], frames_dir / name)
        names.append(name)
    metrics = [sel.candidates[i].metrics for i in sel.selected]
    report = build_report(metrics, sel.pairs, info.width, info.height)
    h, w = frames[0].shape[:2]
    return IngestResult(
        frame_names=names,
        source={"type": "video", "duration": info.duration, "fps": info.fps, "width": info.width,
                "height": info.height, "codec": info.codec, "rotation": info.rotation,
                "trim": [opts.trim_start, opts.trim_end], "sampleFps": opts.sample_fps,
                "candidates": len(frames), "timestamps": [stamps[i] for i in sel.selected]},
        quality=report.as_dict(),
        selection=sel.as_dict(),
        focal_px=None,
        focal_source="default",
        single_camera=True,
    )


def _ingest_photos(paths: list[Path], frames_dir: Path, opts: IngestOptions, progress) -> IngestResult:
    if len(paths) > settings.max_images:
        raise MediaError(f"Please upload at most {settings.max_images} photos.")
    excluded = set(opts.exclude)
    paths = [p for p in paths if p.name not in excluded]
    imgs, infos, kept = [], [], []
    for k, p in enumerate(paths):
        try:
            img, info = load_image(p, max_side=opts.working_max_side)
        except MediaError:
            continue
        imgs.append(img)
        infos.append(info)
        kept.append(p)
        if progress:
            progress((k + 1) / len(paths) * 0.5, f"Read {k + 1} of {len(paths)} photos")
    if len(imgs) < 3:
        raise MediaError("At least 3 readable photos are needed. 20 or more usually work best.")

    if opts.order:
        pos = {n: i for i, n in enumerate(opts.order)}
        order = sorted(range(len(kept)), key=lambda i: pos.get(kept[i].name, 1 << 30))
        how = "user"
    else:
        order, how = order_photos(imgs, [i.timestamp for i in infos])
    imgs = [imgs[i] for i in order]
    infos = [infos[i] for i in order]
    kept = [kept[i] for i in order]

    metrics = [frame_metrics(im) for im in imgs]
    feats = [orb_features(im) for im in imgs]
    pairs = [pair_metrics(a, b) for a, b in zip(feats, feats[1:])]
    report = build_report(metrics, pairs, min(i.width for i in infos), min(i.height for i in infos))
    flags = report.frame_flags
    drop = {i for i, f in enumerate(flags) if opts.drop_blurry and ("blurry" in f or "motion-blur" in f)}
    # Never drop so many that reconstruction becomes impossible.
    if len(imgs) - len(drop) < max(3, opts.min_frames // 2):
        drop = set()
    names, original = [], []
    for k, (img, p) in enumerate(zip(imgs, kept)):
        if k in drop:
            continue
        name = f"frame_{len(names):04d}.jpg"
        _save(img, frames_dir / name)
        names.append(name)
        original.append(p.name)
        if progress:
            progress(0.5 + 0.5 * (k + 1) / len(imgs), f"Prepared {len(names)} frames")

    sizes = {(im.shape[1], im.shape[0]) for im in imgs}
    models = {i.camera_model for i in infos}
    single = len(sizes) == 1 and len(models) == 1
    f, fsrc = focal_prior_px(infos[0], imgs[0].shape[1], imgs[0].shape[0])
    return IngestResult(
        frame_names=names,
        source={"type": "photos", "count": len(paths), "readable": len(kept), "order": how,
                "originalNames": original, "cameraModels": sorted(m for m in models if m)},
        quality=report.as_dict(),
        selection={"selected": [k for k in range(len(imgs)) if k not in drop],
                   "dropped": [{"index": k, "name": kept[k].name, "flags": flags[k]} for k in sorted(drop)]},
        focal_px=f if (fsrc == "exif" and single) else None,
        focal_source=fsrc,
        single_camera=single,
    )


def save_ingest(result: IngestResult, path: Path) -> None:
    path.write_text(json.dumps(result.__dict__, indent=1, default=float))
