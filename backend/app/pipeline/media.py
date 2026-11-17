"""Input inspection: content sniffing, safe decoding, EXIF, and video probing.

File types are identified from their leading bytes, never from the name or
the client-supplied MIME type.  Images are decoded with a pixel budget to
avoid decompression bombs.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image, ImageOps

from ..config import settings

IMAGE_KINDS = {"jpeg", "png", "webp"}
VIDEO_KINDS = {"mp4", "mov", "webm"}


class MediaError(ValueError):
    """A user-facing problem with an uploaded file."""


def sniff(head: bytes) -> str | None:
    """Identify a file from its first bytes. Returns a kind or None."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm" if b"webm" in head[:64] else "mkv"
    box = head[4:8]
    if box == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
            return "heic"
        if brand == b"qt  ":
            return "mov"
        return "mp4"
    if box in (b"moov", b"wide", b"mdat", b"free", b"skip", b"pnot"):
        return "mov"
    return None


def sniff_file(path: Path) -> str | None:
    with open(path, "rb") as fh:
        return sniff(fh.read(64))


UNSUPPORTED_HINTS = {
    "heic": "HEIC photos aren't supported yet. Export them as JPEG (on iPhone: Settings → Camera → Formats → Most Compatible).",
    "mkv": "Matroska video isn't supported. Please convert it to MP4 or WebM.",
}


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip directories and unusual characters from a client file name."""
    name = Path(name or "").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or fallback)[:96]


# ----------------------------------------------------------------- images
@dataclass
class ImageInfo:
    width: int
    height: int
    kind: str
    focal_35mm: float | None = None
    timestamp: float | None = None
    camera_model: str | None = None


def _exif_dict(img: Image.Image) -> dict:
    try:
        exif = img.getexif()
    except Exception:  # corrupt EXIF must never block an upload
        return {}
    out = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    try:
        sub = exif.get_ifd(0x8769)  # Exif sub-IFD holds focal length & time
        out.update({ExifTags.TAGS.get(k, k): v for k, v in sub.items()})
    except Exception:
        pass
    return out


def _parse_exif_time(value) -> float | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip("\x00 "), "%Y:%m:%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def load_image(path: Path, max_side: int | None = None) -> tuple[np.ndarray, ImageInfo]:
    """Decode an image as RGB uint8 honouring EXIF orientation.

    Raises :class:`MediaError` with a friendly message on failure.
    """
    kind = sniff_file(path)
    if kind not in IMAGE_KINDS:
        raise MediaError(UNSUPPORTED_HINTS.get(kind or "", "This file isn't a JPEG, PNG or WebP image."))
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(path) as im:
            if im.width * im.height > settings.max_image_pixels:
                raise MediaError("This image is too large to process (over 100 megapixels).")
            exif = _exif_dict(im)
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            if max_side and max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            arr = np.asarray(im)
    except MediaError:
        raise
    except Image.DecompressionBombError as exc:
        raise MediaError("This image is too large to process safely.") from exc
    except Exception as exc:
        raise MediaError("This image appears to be damaged and couldn't be opened.") from exc
    f35 = exif.get("FocalLengthIn35mmFilm")
    info = ImageInfo(
        width=arr.shape[1],
        height=arr.shape[0],
        kind=kind,
        focal_35mm=float(f35) if f35 else None,
        timestamp=_parse_exif_time(exif.get("DateTimeOriginal") or exif.get("DateTime")),
        camera_model=str(exif.get("Model")).strip("\x00 ") if exif.get("Model") else None,
    )
    return arr, info


def focal_prior_px(info: ImageInfo, width: int, height: int) -> tuple[float, str]:
    """Initial focal length guess in pixels and where it came from.

    EXIF is used only as a starting point: values implying a field of view
    outside 20–120° are rejected, and bundle adjustment refines the result.
    """
    diag = float(np.hypot(width, height))
    if info.focal_35mm and info.focal_35mm > 0:
        f = info.focal_35mm / np.hypot(36.0, 24.0) * diag
        fov = np.rad2deg(2 * np.arctan(max(width, height) / (2 * f)))
        if 20.0 <= fov <= 120.0:
            return f, "exif"
    # ~ 53° horizontal FOV, typical for phone main cameras.
    return 1.2 * max(width, height), "default"


# ------------------------------------------------------------------ video
@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float
    codec: str | None
    rotation: int = 0


def ffmpeg_exe() -> str:
    import shutil

    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


_DUR = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VID = re.compile(r"Stream #\S+.*?Video:\s*(\w+)[^\n]*?,\s*(\d{2,5})x(\d{2,5})")
_FPS = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_ROT = re.compile(r"(?:rotate\s*:\s*|rotation of\s*)(-?\d+(?:\.\d+)?)")


def probe_video(path: Path) -> VideoInfo:
    kind = sniff_file(path)
    if kind not in VIDEO_KINDS:
        raise MediaError(UNSUPPORTED_HINTS.get(kind or "", "This file isn't an MP4, MOV or WebM video."))
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    text = proc.stderr
    m_dur, m_vid = _DUR.search(text), _VID.search(text)
    if not m_dur or not m_vid:
        raise MediaError("We couldn't read a video track from this file. It may be damaged.")
    h, mi, s = m_dur.groups()
    duration = int(h) * 3600 + int(mi) * 60 + float(s)
    stream_line = text[m_vid.start() : text.find("\n", m_vid.start())]
    m_fps = _FPS.search(stream_line)
    m_rot = _ROT.search(text)
    return VideoInfo(
        width=int(m_vid.group(2)),
        height=int(m_vid.group(3)),
        fps=float(m_fps.group(1)) if m_fps else 30.0,
        duration=duration,
        codec=m_vid.group(1),
        rotation=int(float(m_rot.group(1))) % 360 if m_rot else 0,
    )


def decode_video_frames(
    path: Path,
    sample_fps: float,
    max_side: int,
    start: float = 0.0,
    end: float | None = None,
):
    """Yield (timestamp_seconds, RGB frame) at ``sample_fps``.

    FFmpeg handles decoding, display rotation, and resizing; frames are read
    from a raw RGB pipe so nothing touches disk.
    """
    info = probe_video(path)
    end = info.duration if end is None else min(end, info.duration)
    if end <= start:
        raise MediaError("The selected video segment is empty.")
    w, h = (info.height, info.width) if info.rotation in (90, 270) else (info.width, info.height)
    scale = min(1.0, max_side / max(w, h))
    ow, oh = int(round(w * scale / 2)) * 2, int(round(h * scale / 2)) * 2
    cmd = [
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(path),
        "-vf", f"fps={sample_fps},scale={ow}:{oh}:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = ow * oh * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            yield start + i / sample_fps, np.frombuffer(buf, np.uint8).reshape(oh, ow, 3).copy()
            i += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
