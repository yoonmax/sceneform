# sceneform

Turn photos and video into explorable 3D scenes.

**Live demo:** not deployed yet. This README gets a link only after a deployment has been checked.

sceneform is a 3D reconstruction studio. Upload a short video or a set of overlapping photos. It finds where every photo was taken, builds a dense coloured point cloud, depth maps, an optional surface mesh and (on supported GPUs) a trained Gaussian splat, then lets you explore the result in the browser.

## What works today

| Feature | Public static site | Local server |
|---|---|---|
| Open the four example scenes (points, splat, mesh, cameras) | ✅ | ✅ |
| Orbit, fly, top/front/side/ortho views, replay the capture path | ✅ | ✅ |
| Depth and confidence maps, photo-vs-reconstruction comparison | ✅ | ✅ |
| Measuring, setting a reference scale, edits (crop/rotate/recenter/align ground/remove) with undo | ✅ (edits kept in IndexedDB) | ✅ (edits kept on the server) |
| Exports: PLY, PCD, cameras JSON, COLMAP text, GLB, splat PLY, report, screenshot | ✅ | ✅ (plus OBJ, frames ZIP, depth ZIP) |
| Input quality check for your own footage | ✅ in the browser (no upload) | ✅ on the server (adds overlap and parallax checks) |
| **Reconstructing your own footage** | ❌ shows a clear notice and local setup steps | ✅ |
| Gaussian-splat training | ❌ | ✅ Apple Silicon (msplat, tested). NVIDIA (gsplat / splatfacto) is wired in with capability checks but **not tested** |

## How reconstruction works

1. **Ingest.** File types are identified from their content bytes, not the file extension. Images are decoded with a pixel budget and EXIF orientation applied. For video, FFmpeg decodes candidate frames and an adaptive selector keeps the sharpest frame once the view has changed enough. "Enough" is measured as ORB inlier overlap relative to each keyframe's own baseline, plus feature flow. Blurry frames are never promoted. Photo order comes from EXIF capture time or visual similarity, never from file names.
2. **Quality report.** Heuristic checks for blur (including direction, to separate motion blur from focus blur), exposure, resolution, texture, specular highlights, duplicates, overlap, homography-dominant pairs (no parallax), possible moving content, and coverage. The score is a documented weighted sum. It estimates how easy the input will be to reconstruct, not how accurate the result is.
3. **Structure from Motion.** COLMAP (via pycolmap) runs SIFT extraction, exhaustive or sequential matching, incremental mapping and bundle adjustment, then undistorts to a pinhole model.
4. **Canonical frame.** The scene is made Y-up using a RANSAC ground plane, checked against the cameras' average "up" direction. The first camera faces the default view, and the scale is normalised. Units are **relative** until the user sets a reference length.
5. **SfM-anchored depth fusion** (original code: `backend/app/pipeline/fusion.py`):
   - Depth Anything V2 Small predicts relative disparity for each view.
   - Each map is fitted to the SfM inverse depth with RANSAC plus Huber least squares, then given a smooth local correction on a coarse grid.
   - Depth-discontinuity ("flying") pixels are removed.
   - Every pixel is checked in co-visible neighbour views chosen with a baseline constraint. The tolerance adapts to each view's depth spread.
   - Points that would sit in front of a surface another camera clearly sees past are rejected (a free-space check).
   - Confidence is the fraction of neighbouring views that agree. It measures consistency between views, not accuracy.
6. **Point cloud.** Voxel downsampling, statistical outlier removal, PCA normals and robust bounds.
7. **Mesh (optional).** TSDF fusion of the confidence-weighted depth maps, marching cubes, and removal of small fragments. Diagnostics report watertightness and open edges.
8. **Gaussian splat (high-quality mode).** Training uses a maintained trainer: msplat (Metal), gsplat or Nerfstudio splatfacto. The project does not implement its own trainer. Floaters and near-transparent splats are pruned for the web, and the splat stays in the trainer's coordinate frame so its spherical harmonics stay valid. Held-out PSNR/SSIM are reported as the trainer computes them.

The geometry core (`backend/app/geometry/`) is written from first principles and tested on synthetic scenes. It covers camera models, OpenCV↔three.js conversions, the normalised eight-point algorithm, Sampson-distance RANSAC, essential-matrix decomposition with a cheirality check, DLT triangulation, Umeyama alignment and sparse bundle adjustment.

### Coordinate conventions
- World: right-handed, Y-up after alignment.
- Camera: OpenCV (x right, y down, z forward), stored world-to-camera as `x = R X + t`.
- three.js poses use `R_c2w = Rᵀ · diag(1, −1, −1)`.
- Pixel coordinates use the corner convention, as COLMAP does.

These are documented in `backend/app/geometry/cameras.py` and covered by tests.

## Example scenes

All four were produced by this pipeline (high-quality mode, msplat on an M4 Pro). Sources and licences:

| Scene | Source | Licence | Cameras | Reprojection error | Held-out PSNR (full frame) |
|---|---|---|---|---|---|
| Plaster skull | "Photogrammetry Test Set: Skull – Cameramoves – Weak Light – No Background" by alansartlog | CC BY 4.0 | 74/74 | 0.45 px | 15.7 dB* |
| Painted die | "Photogrammetry Test Set: Dice – Turntable – Strong Lights – Thin Messy Watercolors" by alansartlog | CC BY 4.0 | 34/34 | 0.29 px | 23.2 dB |
| Hall of Liberation | Kelheim Befreiungshalle Video, User:Mattes, Wikimedia Commons | Public domain | 90/90 | 0.87 px | 24.9 dB |
| Seated figure, Geneva | Turntable video by Rama, Wikimedia Commons (itself a render of a 3D scan) | CC BY-SA 3.0 FR | 43/43 | 0.59 px | 40.7 dB† |

\* The skull photos have a defocused background that few views see. The trainer overfits it, so full-frame held-out PSNR is low even though the subject renders well. We measured held-out PSNR *falling* as training ran longer, which is why this example uses 4k steps.
† The source is a rendered turntable on a black background, so this number is not comparable with the others.

Each example folder contains an `ATTRIBUTION.txt`.

## Run locally

Requirements:
- Python 3.12 (msplat wheels exist for 3.12 and 3.13 on Apple Silicon)
- Node 20 or newer
- About 3 GB of disk for models and wheels
- FFmpeg comes with `imageio-ffmpeg`

```bash
cd sceneform/backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
```

```bash
cd sceneform/frontend
npm install
npm run dev
```

Then open http://localhost:5173. The dev server proxies `/api` to port 8000.

Command-line reconstruction:

```bash
cd sceneform/backend
.venv/bin/python scripts/reconstruct.py path/to/photos_or_video --out runs/my-scene --mode quick
```

To rebuild the public examples: `scripts/build_examples.py`.

**Hardware.** Fast preview runs SfM on the CPU and depth on MPS, CUDA or CPU. High-quality mode needs Apple Silicon (Metal) or an NVIDIA GPU with gsplat or Nerfstudio installed. Without one, the server refuses high-quality jobs up front and says why. It never falls back to a fake result.

## Testing

Backend: `.venv/bin/python -m pytest tests`. **78 tests pass**, covering:
- geometry and coordinate conversions
- epipolar geometry, triangulation and bundle adjustment
- media sniffing, blur and duplicate detection, keyframe selection, real video decoding
- the job state machine, cancellation, timeouts, worker crashes and retention cleanup
- the API: owner isolation, upload validation, path traversal, rate limiting, edits
- exports re-read with independent readers (plyfile, trimesh, pycolmap)
- an end-to-end reconstruction of a ray-traced scene, checked against ground-truth cameras and surfaces

`scripts/api_smoke.py` runs the full HTTP flow (upload → analyse → job → exports) against a live server.

Manual browser checks so far, in Chromium:
- example scenes in points, splat and mesh modes
- the cameras, depth and photo-comparison panels
- the projects page against a live server

Frontend unit tests and Playwright end-to-end tests are **not written yet**.

## Privacy & security
- Content-type sniffing, size, count and duration limits.
- Random 128-bit project IDs and stored file names.
- Anonymous per-browser owner tokens; only a hash is stored.
- Short-lived HMAC-signed file URLs.
- Path-traversal guards.
- Per-owner rate and concurrency limits.
- Each job runs in its own process.
- 72-hour retention by default; deletion is immediate when requested.

The public static site never uploads files.

## Third-party components
- COLMAP / pycolmap (BSD-3-Clause)
- Depth Anything V2 Small (Apache-2.0)
- msplat (Apache-2.0)
- Spark (MIT)
- three.js, React Three Fiber, Drei (MIT)
- OpenCV (Apache-2.0)
- NumPy, SciPy, scikit-image (BSD)
- trimesh (MIT)
- FastAPI (MIT)
- Fonts: Source Serif 4, IBM Plex Sans, IBM Plex Mono (SIL OFL 1.1)

Full list with licences and example-data attributions: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

No model in this repository was trained from scratch.
