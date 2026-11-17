"""Input-quality measurements and the plain-language quality report.

Every check here is a *heuristic*.  Messages are phrased as likelihoods, and
the report exposes the raw measurements so advanced users can judge for
themselves.  The overall score is a documented weighted sum (see
``docs/quality-score.md``), not an accuracy estimate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

ANALYSIS_WIDTH = 640


def _gray(img: np.ndarray, width: int = ANALYSIS_WIDTH) -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
    if g.shape[1] != width:
        h = int(round(g.shape[0] * width / g.shape[1]))
        g = cv2.resize(g, (width, h), interpolation=cv2.INTER_AREA)
    return g


# ------------------------------------------------------------ per frame
@dataclass
class FrameMetrics:
    sharpness: float  # variance of the Laplacian at 640px width
    tenengrad: float  # mean squared Sobel magnitude
    blur_anisotropy: float  # 0 isotropic … 1 strongly directional (motion)
    brightness: float  # mean luminance 0–255
    dynamic_range: float  # p95 − p5 luminance
    clipped_dark: float  # fraction of pixels ≤ 5
    clipped_bright: float  # fraction of pixels ≥ 250
    textureless_fraction: float  # fraction of 32px tiles with little gradient
    specular_fraction: float  # small saturated, desaturated highlights
    width: int = 0
    height: int = 0
    dhash: int = 0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["dhash"] = f"{self.dhash:016x}"
        return d


def dhash(gray: np.ndarray) -> int:
    """64-bit difference hash for near-duplicate detection."""
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int(np.packbits(bits).view(">u8")[0])


def hamming(a: int, b: int) -> int:
    return int(bin(a ^ b).count("1"))


def frame_metrics(img: np.ndarray) -> FrameMetrics:
    g = _gray(img)
    gf = g.astype(np.float32)
    lap = cv2.Laplacian(gf, cv2.CV_32F, ksize=3)
    gx = cv2.Sobel(gf, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gf, cv2.CV_32F, 0, 1, ksize=3)
    mag2 = gx * gx + gy * gy

    # Structure tensor over the whole frame: motion blur suppresses gradients
    # along the motion direction, making the tensor strongly anisotropic.
    jxx, jyy, jxy = float((gx * gx).mean()), float((gy * gy).mean()), float((gx * gy).mean())
    tr = jxx + jyy
    disc = np.sqrt(max((jxx - jyy) ** 2 + 4 * jxy * jxy, 0.0))
    l1, l2 = (tr + disc) / 2, (tr - disc) / 2
    anis = float((l1 - l2) / (l1 + l2 + 1e-9))

    p5, p95 = np.percentile(g, [5, 95])
    tile = 32
    h, w = g.shape
    th, tw = h // tile, w // tile
    tiles = mag2[: th * tile, : tw * tile].reshape(th, tile, tw, tile).mean(axis=(1, 3))
    textureless = float((tiles < 60.0).mean()) if tiles.size else 0.0

    hsv = cv2.cvtColor(cv2.resize(img, (g.shape[1], g.shape[0])), cv2.COLOR_RGB2HSV) if img.ndim == 3 else None
    spec = 0.0
    if hsv is not None:
        mask = ((hsv[..., 2] >= 245) & (hsv[..., 1] <= 40)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        # Highlights are small bright blobs; big blown-out areas are exposure.
        small = stats[1:, cv2.CC_STAT_AREA][stats[1:, cv2.CC_STAT_AREA] < 0.01 * g.size]
        spec = float(small.sum() / g.size)

    return FrameMetrics(
        sharpness=float(lap.var()),
        tenengrad=float(mag2.mean()),
        blur_anisotropy=anis,
        brightness=float(g.mean()),
        dynamic_range=float(p95 - p5),
        clipped_dark=float((g <= 5).mean()),
        clipped_bright=float((g >= 250).mean()),
        textureless_fraction=textureless,
        specular_fraction=spec,
        width=int(img.shape[1]),
        height=int(img.shape[0]),
        dhash=dhash(g),
    )


# ------------------------------------------------------------- pairwise
_ORB = None


def orb_features(img: np.ndarray, n: int = 1500):
    global _ORB
    if _ORB is None:
        _ORB = cv2.ORB_create(nfeatures=n, fastThreshold=12)
    g = _gray(img)
    kps, desc = _ORB.detectAndCompute(g, None)
    pts = np.array([k.pt for k in kps], dtype=np.float32) if kps else np.zeros((0, 2), np.float32)
    return pts, desc, g.shape


@dataclass
class PairMetrics:
    matches: int  # ratio-test matches
    inliers_f: int  # consistent with a fundamental matrix
    inliers_h: int  # consistent with a homography
    overlap: float  # inlier matches / min(feature counts)
    median_flow: float  # median displacement / image diagonal
    rigid_fraction: float  # inliers_f / matches

    @property
    def homography_dominant(self) -> bool:
        """True when a homography explains the matches nearly as well as F.

        That happens for pure camera rotation or a flat scene — both give no
        usable parallax for depth.
        """
        return self.inliers_f >= 20 and self.inliers_h >= 0.9 * self.inliers_f


def pair_metrics(fa, fb) -> PairMetrics:
    pa, da, shape = fa
    pb, db, _ = fb
    if da is None or db is None or len(pa) < 8 or len(pb) < 8:
        return PairMetrics(0, 0, 0, 0.0, 0.0, 0.0)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(da, db, k=2)
    good = [m[0] for m in knn if len(m) == 2 and m[0].distance < 0.8 * m[1].distance]
    if len(good) < 8:
        return PairMetrics(len(good), 0, 0, 0.0, 0.0, 0.0)
    x1 = pa[[m.queryIdx for m in good]]
    x2 = pb[[m.trainIdx for m in good]]
    diag = float(np.hypot(*shape))
    _, mf = cv2.findFundamentalMat(x1, x2, cv2.FM_RANSAC, 1.5, 0.99)
    _, mh = cv2.findHomography(x1, x2, cv2.RANSAC, 3.0)
    nf = int(mf.sum()) if mf is not None else 0
    nh = int(mh.sum()) if mh is not None else 0
    flow = np.linalg.norm(x2 - x1, axis=1)
    sel = mf.ravel().astype(bool) if mf is not None else np.ones(len(good), bool)
    return PairMetrics(
        matches=len(good),
        inliers_f=nf,
        inliers_h=nh,
        overlap=float(nf / max(1, min(len(pa), len(pb)))),
        median_flow=float(np.median(flow[sel]) / diag) if sel.any() else 0.0,
        rigid_fraction=float(nf / len(good)),
    )


# --------------------------------------------------------------- report
@dataclass
class Finding:
    code: str
    severity: str  # "info" | "warning" | "problem"
    message: str
    frames: list[int] = field(default_factory=list)
    measurement: dict = field(default_factory=dict)


@dataclass
class QualityReport:
    score: int
    grade: str
    components: dict
    findings: list[Finding]
    frame_flags: list[list[str]]

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "components": self.components,
            "findings": [asdict(f) for f in self.findings],
            "frameFlags": self.frame_flags,
            "method": "heuristic",
        }


def blur_flags(metrics: list[FrameMetrics]) -> list[bool]:
    """A frame is blurry if it is far below the set's median sharpness or
    below an absolute floor.  Relative scoring adapts to scene texture."""
    s = np.array([m.sharpness for m in metrics])
    med = float(np.median(s)) if len(s) else 0.0
    return [bool(v < 0.35 * med or v < 15.0) for v in s]


def duplicate_flags(metrics: list[FrameMetrics], max_hamming: int = 3) -> list[bool]:
    flags = [False] * len(metrics)
    for i in range(1, len(metrics)):
        if hamming(metrics[i].dhash, metrics[i - 1].dhash) <= max_hamming:
            flags[i] = True
    return flags


def build_report(
    metrics: list[FrameMetrics],
    pairs: list[PairMetrics],
    source_width: int,
    source_height: int,
    coverage_deg: float | None = None,
) -> QualityReport:
    n = len(metrics)
    findings: list[Finding] = []
    flags: list[list[str]] = [[] for _ in range(n)]
    if n == 0:
        return QualityReport(0, "unusable", {}, [Finding("empty", "problem", "No usable images were found.")], [])

    # --- sharpness
    blurry = blur_flags(metrics)
    for i, b in enumerate(blurry):
        if b:
            kind = "motion-blur" if metrics[i].blur_anisotropy > 0.35 else "blurry"
            flags[i].append(kind)
    n_blur = sum(blurry)
    if n_blur:
        motion = sum(1 for i, b in enumerate(blurry) if b and metrics[i].blur_anisotropy > 0.35)
        msg = f"{n_blur} of {n} frames look blurry. Removing them will likely improve the reconstruction."
        if motion > n_blur / 2:
            msg += " The blur looks directional, which usually means the camera moved too fast."
        findings.append(Finding("blur", "warning" if n_blur < n / 2 else "problem", msg,
                                [i for i, b in enumerate(blurry) if b], {"motionBlurLike": motion}))
    sharp_score = 1.0 - n_blur / n

    # --- exposure
    dark = [i for i, m in enumerate(metrics) if m.brightness < 45 or m.clipped_dark > 0.25]
    bright = [i for i, m in enumerate(metrics) if m.brightness > 220 or m.clipped_bright > 0.25]
    flat = [i for i, m in enumerate(metrics) if m.dynamic_range < 40]
    for i in dark:
        flags[i].append("dark")
    for i in bright:
        flags[i].append("overexposed")
    if dark:
        findings.append(Finding("lighting-dark", "warning", f"{len(dark)} frames look underexposed. Brighter, even lighting helps feature matching.", dark))
    if bright:
        findings.append(Finding("lighting-bright", "warning", f"{len(bright)} frames have large blown-out areas.", bright))
    if len(flat) > n / 3:
        findings.append(Finding("low-contrast", "info", "Many frames have low contrast, which may make matching harder.", flat))
    bvals = np.array([m.brightness for m in metrics])
    if n > 3 and bvals.std() > 35:
        findings.append(Finding("lighting-varies", "info", "Brightness changes a lot across the capture. Consistent lighting gives cleaner colors.",
                                measurement={"brightnessStd": float(bvals.std())}))
    expo_score = 1.0 - len(set(dark) | set(bright)) / n

    # --- resolution
    short = min(source_width, source_height)
    if short < 480:
        res_score = 0.2
        findings.append(Finding("low-resolution", "problem", f"The input is only {source_width}×{source_height}. At least 720p is recommended."))
    elif short < 720:
        res_score = 0.6
        findings.append(Finding("low-resolution", "info", f"The input is {source_width}×{source_height}. Higher resolution captures finer detail."))
    else:
        res_score = 1.0

    # --- texture
    tex = np.array([m.textureless_fraction for m in metrics])
    if np.median(tex) > 0.6:
        findings.append(Finding("textureless", "warning",
                                "Large parts of the images are plain or featureless. Smooth walls and blank surfaces are hard to reconstruct.",
                                measurement={"medianTexturelessFraction": float(np.median(tex))}))
    tex_score = float(np.clip(1.2 - np.median(tex), 0, 1))

    spec = np.array([m.specular_fraction for m in metrics])
    if np.median(spec) > 0.004:
        findings.append(Finding("reflective", "info",
                                "Several bright highlights were detected. Shiny or reflective surfaces may reconstruct poorly.",
                                measurement={"medianSpecularFraction": float(np.median(spec))}))

    # --- duplicates
    dups = duplicate_flags(metrics)
    for i, d in enumerate(dups):
        if d:
            flags[i].append("duplicate")
    n_dup = sum(dups)
    if n_dup > max(2, n // 10):
        findings.append(Finding("duplicates", "info",
                                f"{n_dup} frames are nearly identical to their neighbour. A smaller, more varied set is enough.",
                                [i for i, d in enumerate(dups) if d]))
    dup_score = 1.0 - min(1.0, n_dup / max(1, n))

    # --- overlap / parallax between consecutive frames
    overlap_score = 1.0
    if pairs:
        weak = [i + 1 for i, p in enumerate(pairs) if p.inliers_f < 30]
        for i in weak:
            flags[i].append("low-overlap")
        if weak:
            findings.append(Finding("low-overlap", "warning" if len(weak) < len(pairs) / 3 else "problem",
                                    f"{len(weak)} consecutive pairs share few matching features. Move more slowly so views overlap.", weak))
        rot_only = sum(p.homography_dominant for p in pairs)
        if rot_only > 0.7 * len(pairs):
            findings.append(Finding("no-parallax", "warning",
                                    "The camera seems to mostly rotate in place, or the scene is flat. Walk around the subject so depth can be measured."))
        nonrigid = [i + 1 for i, p in enumerate(pairs) if p.matches >= 40 and p.rigid_fraction < 0.45]
        if len(nonrigid) > max(2, len(pairs) // 5):
            findings.append(Finding("moving-content", "info",
                                    "Some matches don't agree with a single camera motion. There may be moving people or objects in the scene.", nonrigid))
        overlap_score = 1.0 - len(weak) / len(pairs)
        flows = np.array([p.median_flow for p in pairs])
        total = float(flows.sum())
        if total < 0.25 and n > 4:
            findings.append(Finding("low-coverage", "warning",
                                    "The viewpoint barely changes across the capture. Try recording around the subject.",
                                    measurement={"cumulativeFlow": total}))
            overlap_score *= 0.6

    coverage_score = None
    if coverage_deg is not None:
        coverage_score = float(np.clip(coverage_deg / 180.0, 0, 1))
        if coverage_deg < 60:
            findings.append(Finding("one-sided", "warning",
                                    f"Your camera covered about {coverage_deg:.0f}° around the subject. Try recording around it for a complete model.",
                                    measurement={"coverageDeg": coverage_deg}))

    if n < 8:
        findings.append(Finding("too-few", "problem" if n < 3 else "warning",
                                f"Only {n} usable views. 20–80 overlapping views usually work best."))

    components = {
        "sharpness": round(sharp_score, 3),
        "overlap": round(overlap_score, 3),
        "exposure": round(expo_score, 3),
        "texture": round(tex_score, 3),
        "resolution": round(res_score, 3),
        "variety": round(dup_score, 3),
    }
    weights = {"sharpness": 25, "overlap": 25, "exposure": 15, "texture": 15, "resolution": 10, "variety": 10}
    score = sum(components[k] * w for k, w in weights.items())
    if n < 3:
        score = min(score, 15)
    elif n < 8:
        score *= 0.8
    score = int(round(score))
    grade = "great" if score >= 85 else "good" if score >= 70 else "fair" if score >= 50 else "poor"
    if not findings:
        findings.append(Finding("ok", "info", "Your capture looks good. Sharp, well-lit, overlapping views."))
    if coverage_score is not None:
        components["coverage"] = round(coverage_score, 3)
    return QualityReport(score, grade, components, findings, flags)
