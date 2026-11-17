"""End-to-end smoke test against a running API server.

    python scripts/api_smoke.py http://127.0.0.1:8000 path/to/photos [--mode quick]

Creates a project, uploads photos, runs the input check, starts a job,
follows it to completion, and verifies the outputs can be downloaded and
re-read. Prints the project/run ids so the scene can be opened in the UI.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("photos", type=Path)
    ap.add_argument("--mode", default="quick")
    ap.add_argument("--owner", default=None, help="owner token (defaults to a fresh random one)")
    ap.add_argument("--cancel-after", type=float, default=None)
    args = ap.parse_args()
    owner = args.owner or secrets.token_hex(24)
    h = {"X-Sceneform-Owner": owner}
    c = httpx.Client(base_url=args.base, headers=h, timeout=600)

    p = c.post("/api/projects", json={"name": "API smoke test"}).raise_for_status().json()
    pid = p["id"]
    files = sorted(f for f in args.photos.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png") and f.name[0].isdigit())
    up = c.post(f"/api/projects/{pid}/uploads", files=[("files", (f.name, f.read_bytes(), "image/jpeg")) for f in files]).raise_for_status().json()
    print(f"uploaded {len(up['added'])} files, rejected {len(up['rejected'])}")
    rep = c.post(f"/api/projects/{pid}/analyze").raise_for_status().json()["report"]
    print(f"input check {rep['score']}/100: {[f['code'] for f in rep['findings']]}")
    job = c.post(f"/api/projects/{pid}/jobs", json={"mode": args.mode, "settings": {"mesh": True}}).raise_for_status().json()
    t0 = time.time()
    last = None
    while True:
        j = c.get(f"/api/jobs/{job['id']}").raise_for_status().json()
        line = (j["state"], j["stage"], None if j["progress"] is None else round(j["progress"], 2))
        if line[:2] != (last or (None, None))[:2]:
            print(f"[{time.time() - t0:6.1f}s] {j['state']:<9} {j['stage'] or '':<22} {j['message'] or ''}")
        last = line
        if args.cancel_after and time.time() - t0 > args.cancel_after and j["state"] == "running" and not j["cancel_requested"]:
            c.post(f"/api/jobs/{job['id']}/cancel").raise_for_status()
            print("cancel requested")
        if j["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(1)
    print(json.dumps({k: j[k] for k in ("state", "error", "error_code", "run_id")}))
    if j["state"] != "succeeded":
        return 0 if args.cancel_after and j["state"] == "cancelled" else 1
    proj = c.get(f"/api/projects/{pid}").raise_for_status().json()
    sig = proj["sig"]
    rid = j["run_id"]
    base = f"/api/projects/{pid}/files/runs/{rid}/outputs/"
    m = httpx.get(args.base + base + "manifest.json", params={"sig": sig}).raise_for_status().json()
    print(f"manifest: {m['metrics']['registeredViews']}/{m['metrics']['inputFrames']} cams, {m['pointCloud']['stats']['count']} pts")
    from app.pipeline.export import read_pcd, read_ply

    with tempfile.TemporaryDirectory() as td:
        for kind, fname in [("points-ply", "p.ply"), ("points-pcd", "p.pcd"), ("mesh-glb", "m.glb"), ("report-md", "r.md"), ("depth-zip", "d.zip")]:
            r = httpx.get(f"{args.base}/api/projects/{pid}/runs/{rid}/export/{kind}", params={"sig": sig, "confidence": 0.5}, timeout=300)
            r.raise_for_status()
            path = Path(td) / fname
            path.write_bytes(r.content)
            if fname.endswith(".ply"):
                print(f"  {kind}: {len(read_ply(path)['x'])} points re-read")
            elif fname.endswith(".pcd"):
                print(f"  {kind}: {len(read_pcd(path)['points'])} points re-read")
            else:
                print(f"  {kind}: {len(r.content)} bytes")
    other = httpx.get(f"{args.base}/api/projects/{pid}", headers={"X-Sceneform-Owner": secrets.token_hex(24)})
    print(f"other owner sees project: {other.status_code}")
    print(f"OPEN /scene/project/{pid}/{rid}  owner={owner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
