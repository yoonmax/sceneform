"""Preprocessing: sniffing, decoding, blur/duplicate detection, frame selection."""

import subprocess

import cv2
import numpy as np
import pytest
from PIL import Image

from app.pipeline.frame_selection import SelectionParams, order_photos, select_keyframes
from app.pipeline.media import MediaError, decode_video_frames, ffmpeg_exe, load_image, probe_video, safe_filename, sniff
from app.pipeline.quality import blur_flags, build_report, duplicate_flags, frame_metrics, orb_features, pair_metrics


def texture(h=900, w=1600, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (h // 8, w // 8, 3), dtype=np.uint8)
    img = cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)
    for _ in range(300):
        c = tuple(int(x) for x in rng.integers(0, 255, 3))
        cv2.circle(img, (int(rng.integers(0, w)), int(rng.integers(0, h))), int(rng.integers(4, 40)), c, -1)
    return img


def crop_sequence(n=40, step=12, size=(480, 640)):
    big = texture()
    h, w = size
    return [big[50:50 + h, 20 + i * step: 20 + i * step + w].copy() for i in range(n)]


# --------------------------------------------------------------- sniff
@pytest.mark.parametrize("head,kind", [
    (b"\xff\xd8\xff\xe0" + b"\0" * 20, "jpeg"),
    (b"\x89PNG\r\n\x1a\n" + b"\0" * 20, "png"),
    (b"RIFF\0\0\0\0WEBPVP8 ", "webp"),
    (b"\0\0\0\x18ftypisom" + b"\0" * 8, "mp4"),
    (b"\0\0\0\x14ftypqt  " + b"\0" * 8, "mov"),
    (b"\x1a\x45\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01webm", "webm"),
    (b"\0\0\0\x18ftypheic" + b"\0" * 8, "heic"),
    (b"MZ\x90\0" + b"\0" * 20, None),
    (b"#!/bin/sh\nrm -rf /", None),
])
def test_sniff_identifies_by_content(head, kind):
    assert sniff(head) == kind


def test_extension_is_not_trusted(tmp_path):
    fake = tmp_path / "photo.jpg"
    fake.write_bytes(b"<html>not an image</html>")
    with pytest.raises(MediaError):
        load_image(fake)


def test_corrupt_jpeg_gives_friendly_error(tmp_path):
    bad = tmp_path / "x.jpg"
    bad.write_bytes(b"\xff\xd8\xff\xe0" + b"garbage" * 20)
    with pytest.raises(MediaError, match="damaged"):
        load_image(bad)


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("my photo (1).JPG") == "my_photo_1_.JPG"
    assert safe_filename("") == "file"
    assert "/" not in safe_filename("a/b\\c")


def test_exif_orientation_applied(tmp_path):
    img = Image.fromarray(np.zeros((100, 200, 3), np.uint8))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW on display
    p = tmp_path / "r.jpg"
    img.save(p, exif=exif)
    arr, info = load_image(p)
    assert arr.shape[:2] == (200, 100)


# -------------------------------------------------------------- quality
def test_blur_detection_flags_blurred_frames():
    frames = crop_sequence(12)
    frames[3] = cv2.GaussianBlur(frames[3], (0, 0), 6)
    k = np.zeros((1, 31), np.float32)
    k[0, :] = 1 / 31
    frames[7] = cv2.filter2D(frames[7], -1, k)  # horizontal motion blur
    m = [frame_metrics(f) for f in frames]
    flags = blur_flags(m)
    assert flags[3] and flags[7]
    assert sum(flags) == 2
    assert m[7].blur_anisotropy > m[0].blur_anisotropy


def test_duplicate_detection():
    frames = crop_sequence(6)
    frames.insert(3, frames[2].copy())
    flags = duplicate_flags([frame_metrics(f) for f in frames])
    assert flags[3] and sum(flags) == 1


def test_pair_metrics_overlap_decreases_with_motion():
    seq = crop_sequence(30, step=10)
    fa = orb_features(seq[0])
    near = pair_metrics(fa, orb_features(seq[2]))
    far = pair_metrics(fa, orb_features(seq[25]))
    assert near.inliers_f > far.inliers_f
    assert near.overlap > far.overlap


def test_quality_report_messages_and_score():
    frames = crop_sequence(10)
    frames[4] = cv2.GaussianBlur(frames[4], (0, 0), 8)
    m = [frame_metrics(f) for f in frames]
    feats = [orb_features(f) for f in frames]
    pairs = [pair_metrics(a, b) for a, b in zip(feats, feats[1:])]
    rep = build_report(m, pairs, 1920, 1080).as_dict()
    assert 0 <= rep["score"] <= 100
    codes = {f["code"] for f in rep["findings"]}
    assert "blur" in codes
    assert rep["method"] == "heuristic"
    dark = [frame_metrics((f * 0.1).astype(np.uint8)) for f in frames]
    rep2 = build_report(dark, pairs, 1920, 1080).as_dict()
    assert "lighting-dark" in {f["code"] for f in rep2["findings"]}
    assert rep2["score"] < rep["score"]


def test_low_resolution_and_too_few_frames():
    m = [frame_metrics(f) for f in crop_sequence(3, size=(240, 320))]
    rep = build_report(m, [], 320, 240).as_dict()
    codes = {f["code"] for f in rep["findings"]}
    assert {"low-resolution", "too-few"} <= codes


# ---------------------------------------------------------- selection
def test_keyframe_selection_skips_blur_and_redundancy():
    seq = crop_sequence(60, step=6)
    for i in (20, 21, 22):
        seq[i] = cv2.GaussianBlur(seq[i], (0, 0), 7)
    res = select_keyframes(seq, [i / 10 for i in range(60)], SelectionParams(min_frames=4, max_frames=40))
    sel = res.selected
    assert 4 <= len(sel) < 40, "adaptive selection should drop redundant frames"
    assert not set(sel) & {20, 21, 22}, "blurry frames must not be selected"
    assert sel == sorted(sel)
    assert all(res.candidates[i].selected for i in sel)


def test_photo_ordering_never_uses_filenames_and_prefers_exif():
    seq = crop_sequence(8, step=40)
    order, how = order_photos(seq, [float(10 - i) for i in range(8)])
    assert how == "exif-time" and order == list(range(7, -1, -1))
    shuffled = [seq[i] for i in (3, 0, 6, 1, 7, 2, 5, 4)]
    order, how = order_photos(shuffled, [None] * 8)
    assert how == "visual-similarity" and sorted(order) == list(range(8))


# ---------------------------------------------------------------- video
@pytest.fixture()
def video(tmp_path):
    seq = crop_sequence(48, step=8)
    path = tmp_path / "clip.mp4"
    h, w = seq[0].shape[:2]
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", "12", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, input=b"".join(f.tobytes() for f in seq), check=True)
    return path


def test_video_probe_and_decode(video):
    info = probe_video(video)
    assert info.width == 640 and info.height == 480
    assert 3.5 < info.duration < 4.5
    frames = list(decode_video_frames(video, sample_fps=4, max_side=320))
    assert 14 <= len(frames) <= 17
    ts, fr = frames[1]
    assert fr.shape == (240, 320, 3) and abs(ts - 0.25) < 1e-6
    trimmed = list(decode_video_frames(video, sample_fps=4, max_side=320, start=1.0, end=2.0))
    assert 3 <= len(trimmed) <= 5 and trimmed[0][0] == pytest.approx(1.0)


def test_video_rejects_non_video(tmp_path):
    p = tmp_path / "x.mp4"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    with pytest.raises(MediaError):
        probe_video(p)
