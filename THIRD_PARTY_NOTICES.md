# Third-party notices

sceneform depends on the open-source components below. Each remains under its own licence; the full licence texts ship with the installed packages (`backend/.venv/lib/python3.12/site-packages/*/LICENSE*`, `frontend/node_modules/*/LICENSE*`).

## Backend

| Component | Use | Licence |
|---|---|---|
| COLMAP / pycolmap | Structure-from-Motion, undistortion | BSD-3-Clause |
| Depth Anything V2 Small (weights and code, via Hugging Face transformers) | Monocular relative depth | Apache-2.0 |
| PyTorch | Depth inference | BSD-3-Clause |
| transformers (Hugging Face) | Model loading | Apache-2.0 |
| msplat | Gaussian-splat training on Apple Silicon | Apache-2.0 |
| OpenCV (opencv-contrib-python-headless) | Image processing, features | Apache-2.0 |
| NumPy, SciPy, scikit-image | Numerics, sparse least squares, marching cubes | BSD-3-Clause |
| trimesh | Mesh export | MIT |
| plyfile | PLY reading and writing | GPL-3.0 (used only by the test suite as an independent reader) |
| Pillow | Image decoding | MIT-CMU (HPND) |
| imageio-ffmpeg (bundles FFmpeg) | Video decoding | BSD-2-Clause (wrapper); FFmpeg is LGPL-2.1+/GPL depending on build |
| FastAPI, Starlette, Pydantic, Uvicorn | HTTP API | MIT / BSD-3-Clause |

## Frontend

| Component | Use | Licence |
|---|---|---|
| three.js | WebGL rendering | MIT |
| React, React DOM | UI | MIT |
| React Three Fiber, Drei | React renderer for three.js, helpers | MIT |
| Spark (@sparkjsdev/spark) | Gaussian-splat rendering | MIT |
| Zustand | State | MIT |
| GSAP | Capture-path replay animation | GreenSock Standard "No Charge" licence |
| React Router | Routing | MIT |
| Tailwind CSS, Vite | Styling, build | MIT |
| Source Serif 4, IBM Plex Sans, IBM Plex Mono (Google Fonts) | Typefaces | SIL Open Font License 1.1 |

## Example data

The reconstructions in `frontend/public/examples/` are derived from the works below. Each folder has an `ATTRIBUTION.txt`; derived outputs keep the source licence.

| Folder | Source | Licence |
|---|---|---|
| `plaster-skull` | "Photogrammetry Test Set: Skull - Cameramoves - Weak Light - No Background" by alansartlog — https://gitlab.com/photogrammetry-test-sets/skull-cameramoves-weak-light-no-background | CC BY 4.0 |
| `painted-die` | "Photogrammetry Test Set: Dice - Turntable - Strong Lights - Thin Messy Watercolors" by alansartlog — https://gitlab.com/photogrammetry-test-sets/dice-turntable-strong-lights-thin-messy-watercolors | CC BY 4.0 |
| `liberation-hall` | "Kelheim Befreiungshalle Video" by User:Mattes, Wikimedia Commons — https://commons.wikimedia.org/wiki/File:Kelheim_Befreiungshalle_Video.ogv | Public domain |
| `geneva-sculpture` | "Sculpture by Theodora Barazzone at Cimetière des Rois (turntable video)" by Rama, Wikimedia Commons | CC BY-SA 3.0 FR |
