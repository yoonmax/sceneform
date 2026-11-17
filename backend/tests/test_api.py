"""HTTP API: ownership isolation, uploads, validation, jobs, files."""

import io
import secrets
import time

import numpy as np
import pytest
from PIL import Image

from app.storage.db import db
from app.workers import jobs


def jpeg_bytes(seed=0, size=(320, 240)):
    rng = np.random.default_rng(seed)
    img = Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_project(client, headers, name="Desk lamp"):
    r = client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_capabilities(client):
    assert client.get("/api/health").json()["service"] == "sceneform"
    caps = client.get("/api/capabilities").json()
    assert caps["quick"]["available"] is True
    assert "trainers" in caps["high"]


def test_owner_token_required(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"X-Sceneform-Owner": "short"}).status_code == 401


def test_projects_are_isolated_between_owners(client, owner_headers):
    p = make_project(client, owner_headers)
    other = {"X-Sceneform-Owner": secrets.token_hex(24)}
    assert client.get(f"/api/projects/{p['id']}", headers=other).status_code == 404
    assert client.get("/api/projects", headers=other).json()["projects"] == []
    assert client.delete(f"/api/projects/{p['id']}", headers=other).status_code == 404
    # Files need a valid signature or the owner header.
    assert client.get(f"/api/projects/{p['id']}/files/thumbs/abc.jpg").status_code == 404
    assert client.get(f"/api/projects/{p['id']}/files/thumbs/abc.jpg?sig=123.abc").status_code == 404


def test_project_name_validation_and_rename(client, owner_headers):
    assert client.post("/api/projects", json={"name": "   "}, headers=owner_headers).status_code == 422
    assert client.post("/api/projects", json={"name": "x" * 81}, headers=owner_headers).status_code == 422
    p = make_project(client, owner_headers, "  my   scene ")
    assert p["name"] == "my scene"
    r = client.patch(f"/api/projects/{p['id']}", json={"name": "Renamed"}, headers=owner_headers)
    assert r.json()["name"] == "Renamed"


def test_upload_images_with_sniffing_and_dedupe(client, owner_headers):
    p = make_project(client, owner_headers)
    files = [("files", (f"img{i}.jpg", jpeg_bytes(i), "image/jpeg")) for i in range(3)]
    files.append(("files", ("evil.jpg", b"#!/bin/sh\necho hi", "image/jpeg")))
    files.append(("files", ("dupe.jpg", jpeg_bytes(0), "image/jpeg")))
    files.append(("files", ("photo.heic", b"\0\0\0\x18ftypheic" + b"\0" * 100, "image/heic")))
    r = client.post(f"/api/projects/{p['id']}/uploads", files=files, headers=owner_headers)
    body = r.json()
    assert len(body["added"]) == 3
    reasons = {x["name"]: x["reason"] for x in body["rejected"]}
    assert "evil.jpg" in reasons and "dupe.jpg" in reasons and "HEIC" in reasons["photo.heic"]
    a = body["assets"][0]
    assert a["width"] == 320 and a["height"] == 240
    # Stored names are random, not the client's names.
    stored = db().execute("SELECT stored_name FROM assets").fetchall()
    assert all(not s["stored_name"].startswith("img") for s in stored)
    # The signed thumbnail URL works without the owner header.
    assert client.get(a["thumb"]).status_code == 200
    proj = client.get(f"/api/projects/{p['id']}", headers=owner_headers).json()
    assert proj["inputType"] == "photos" and proj["inputCount"] == 3


def test_path_traversal_blocked(client, owner_headers):
    p = make_project(client, owner_headers)
    sig = p["sig"]
    for bad in ["../../sceneform.sqlite3", "inputs/../../../etc/passwd", "runs/abc/work/frames/x.jpg", ".signing_key"]:
        r = client.get(f"/api/projects/{p['id']}/files/{bad}?sig={sig}")
        assert r.status_code in (401, 404) and b"SQLite" not in r.content


def test_analyze_and_job_lifecycle(client, owner_headers):
    p = make_project(client, owner_headers)
    files = [("files", (f"img{i}.jpg", jpeg_bytes(i, (640, 480)), "image/jpeg")) for i in range(4)]
    client.post(f"/api/projects/{p['id']}/uploads", files=files, headers=owner_headers)
    rep = client.post(f"/api/projects/{p['id']}/analyze", headers=owner_headers).json()
    assert 0 <= rep["report"]["score"] <= 100 and len(rep["assets"]) == 4

    bad = client.post(f"/api/projects/{p['id']}/jobs", json={"mode": "quick", "settings": {"max_frames": 9999}},
                      headers=owner_headers)
    assert bad.status_code == 422
    job = client.post(f"/api/projects/{p['id']}/jobs", json={"mode": "quick"}, headers=owner_headers).json()
    assert job["state"] == "queued"
    again = client.post(f"/api/projects/{p['id']}/jobs", json={"mode": "quick"}, headers=owner_headers)
    assert again.status_code == 409
    other = {"X-Sceneform-Owner": secrets.token_hex(24)}
    assert client.get(f"/api/jobs/{job['id']}", headers=other).status_code == 404
    c = client.post(f"/api/jobs/{job['id']}/cancel", headers=owner_headers).json()
    assert c["state"] == "cancelled"
    r = client.post(f"/api/jobs/{job['id']}/retry", headers=owner_headers).json()
    assert r["state"] == "queued" and r["attempts"] == 1 and r["run_id"] != job["run_id"]


def test_delete_project_removes_files(client, owner_headers, data_dir):
    p = make_project(client, owner_headers)
    client.post(f"/api/projects/{p['id']}/uploads", files=[("files", ("a.jpg", jpeg_bytes(), "image/jpeg"))],
                headers=owner_headers)
    pdir = data_dir / "projects" / p["id"]
    assert any(pdir.rglob("*.jpg"))
    assert client.delete(f"/api/projects/{p['id']}", headers=owner_headers).json()["deleted"]
    assert not pdir.exists()
    assert db().execute("SELECT COUNT(*) c FROM assets").fetchone()["c"] == 0


def test_duplicate_project_copies_inputs_not_outputs(client, owner_headers):
    p = make_project(client, owner_headers)
    client.post(f"/api/projects/{p['id']}/uploads",
                files=[("files", (f"{i}.jpg", jpeg_bytes(i), "image/jpeg")) for i in range(2)], headers=owner_headers)
    d = client.post(f"/api/projects/{p['id']}/duplicate", headers=owner_headers).json()
    assert d["id"] != p["id"] and d["inputCount"] == 2 and d["latestRun"] is None


def test_rate_limit(client, owner_headers, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_minute", 5)
    codes = [client.get("/api/projects", headers=owner_headers).status_code for _ in range(8)]
    assert 429 in codes


def test_edits_roundtrip_and_validation(client, owner_headers):
    p = make_project(client, owner_headers)
    db().execute("INSERT INTO runs(id, project_id, mode, created_at) VALUES('abcd', ?, 'quick', 0)", (p["id"],))
    ops = {"version": 1, "ops": [{"type": "rotate", "params": {"axis": [0, 1, 0], "degrees": 90}},
                                 {"type": "crop", "params": {"min": [-1, -1, -1], "max": [1, 1, 1]}}]}
    r = client.put(f"/api/projects/{p['id']}/runs/abcd/edits", json=ops, headers=owner_headers)
    assert r.status_code == 200
    assert client.get(f"/api/projects/{p['id']}/runs/abcd/edits", headers=owner_headers).json()["ops"][0]["type"] == "rotate"
    bad = client.put(f"/api/projects/{p['id']}/runs/abcd/edits", json={"ops": [{"type": "rm -rf"}]}, headers=owner_headers)
    assert bad.status_code == 422
