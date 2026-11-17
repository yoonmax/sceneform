"""Adaptive keyframe selection for video and ordering for photo sets.

Video strategy (not "every n-th frame"):
  1. Decode candidates at a modest rate (default 4 fps).
  2. Score each candidate's sharpness.
  3. Walk forward from the current keyframe, tracking how much of it is still
     visible (ORB inlier overlap) and how far the content has moved.
  4. When overlap falls below ``target_overlap`` (or motion exceeds
     ``max_flow``), promote the *sharpest* candidate from the window since
     the last keyframe that still overlaps it by at least ``min_overlap``.
  5. Blurry candidates are never promoted unless nothing else is available.

This keeps views that are sharp, distinct, and still well connected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .quality import FrameMetrics, PairMetrics, blur_flags, frame_metrics, orb_features, pair_metrics


@dataclass
class SelectionParams:
    target_overlap: float = 0.5  # relative to the keyframe's next-frame overlap
    min_overlap: float = 0.15
    max_flow: float = 0.08  # fraction of the image diagonal
    min_frames: int = 12
    max_frames: int = 120


@dataclass
class Candidate:
    index: int
    timestamp: float
    metrics: FrameMetrics
    blurry: bool = False
    selected: bool = False
    reason: str = ""
    overlap_to_prev_key: float | None = None


@dataclass
class SelectionResult:
    candidates: list[Candidate]
    selected: list[int]
    pairs: list[PairMetrics] = field(default_factory=list)  # between consecutive selected frames

    def as_dict(self) -> dict:
        return {
            "selected": self.selected,
            "candidates": [
                {
                    "index": c.index,
                    "timestamp": round(c.timestamp, 3),
                    "sharpness": round(c.metrics.sharpness, 2),
                    "blurry": c.blurry,
                    "selected": c.selected,
                    "reason": c.reason,
                    "overlapToPrevKey": None if c.overlap_to_prev_key is None else round(c.overlap_to_prev_key, 3),
                }
                for c in self.candidates
            ],
        }


def select_keyframes(frames: list[np.ndarray], timestamps: list[float], params: SelectionParams | None = None) -> SelectionResult:
    params = params or SelectionParams()
    n = len(frames)
    metrics = [frame_metrics(f) for f in frames]
    blurry = blur_flags(metrics)
    cands = [Candidate(i, timestamps[i], metrics[i], blurry[i]) for i in range(n)]
    if n == 0:
        return SelectionResult(cands, [])
    feats = [orb_features(f) for f in frames]

    # First keyframe: sharpest of the first few candidates.
    head = list(range(min(n, 5)))
    first = max(head, key=lambda i: (not blurry[i], metrics[i].sharpness))
    keys = [first]
    cands[first].selected, cands[first].reason = True, "first sharp view"

    def baseline(k: int) -> float:
        """Overlap of keyframe k with its next non-blurry frame: ORB inlier
        ratios depend on texture, so motion is judged relative to this."""
        for j in range(k + 1, min(n, k + 4)):
            if not blurry[j]:
                return max(pair_metrics(feats[k], feats[j]).overlap, 1e-3)
        return 1.0

    ref = baseline(first)
    window: list[tuple[int, float]] = []  # (index, relative overlap with last key)
    i = first + 1
    while i < n:
        pm = pair_metrics(feats[keys[-1]], feats[i])
        rel = pm.overlap / ref
        cands[i].overlap_to_prev_key = pm.overlap
        window.append((i, rel))
        moved_enough = rel < params.target_overlap or pm.median_flow > params.max_flow
        if moved_enough:
            usable = [(j, o) for j, o in window if o >= params.min_overlap]
            sharp = [(j, o) for j, o in usable if not blurry[j]]
            if not sharp and blurry[i] and len(window) < 15:
                # Blur itself destroys features (so overlap looks low); wait
                # for the next sharp frame instead of promoting a blurry one.
                i += 1
                continue
            pool = sharp or usable or window
            # Prefer the most recent part of the window so each keyframe adds
            # new viewpoint, then the sharpest frame within it.
            recent = pool[-max(3, len(pool) // 3):]
            best = max(recent, key=lambda jo: metrics[jo[0]].sharpness)[0]
            keys.append(best)
            cands[best].selected = True
            cands[best].reason = "sharpest view once the scene had moved"
            ref = baseline(best)
            window = [(j, pair_metrics(feats[best], feats[j]).overlap / ref) for j, _ in window if j > best]
        i += 1

    # Always keep a closing view of the capture if it is sharp and distinct.
    last = n - 1
    if keys[-1] != last and not blurry[last]:
        pm = pair_metrics(feats[keys[-1]], feats[last])
        if pm.overlap < 0.8:
            keys.append(last)
            cands[last].selected, cands[last].reason = True, "end of capture"

    # Too few: fill with the sharpest unselected candidates spread over time.
    if len(keys) < params.min_frames:
        rest = sorted((c for c in cands if not c.selected and not c.blurry), key=lambda c: -c.metrics.sharpness)
        bins = np.array_split(np.arange(n), params.min_frames)
        for b in bins:
            if len(keys) >= params.min_frames:
                break
            if any(k in b for k in keys):
                continue
            opts = [c for c in rest if c.index in set(b.tolist())]
            if opts:
                keys.append(opts[0].index)
                opts[0].selected, opts[0].reason = True, "added for coverage"
    keys = sorted(set(keys))

    # Too many: thin uniformly in time, keeping the sharpest per bin.
    if len(keys) > params.max_frames:
        bins = np.array_split(np.array(keys), params.max_frames)
        thinned = [max(b.tolist(), key=lambda k: metrics[k].sharpness) for b in bins if len(b)]
        for k in set(keys) - set(thinned):
            cands[k].selected, cands[k].reason = False, "thinned to frame budget"
        keys = thinned

    pairs = [pair_metrics(feats[a], feats[b]) for a, b in zip(keys, keys[1:])]
    return SelectionResult(cands, keys, pairs)


def order_photos(images: list[np.ndarray], timestamps: list[float | None]) -> tuple[list[int], str]:
    """Return a capture order for an unordered photo set and how it was found.

    Uses EXIF capture times when every photo has a distinct one.  Otherwise
    chains photos by visual similarity (greedy nearest-neighbour walk starting
    from the most isolated image).  File names are never used.
    """
    n = len(images)
    if n <= 2:
        return list(range(n)), "as uploaded"
    if all(t is not None for t in timestamps) and len(set(timestamps)) == n:
        return sorted(range(n), key=lambda i: timestamps[i]), "exif-time"

    import cv2

    descs = []
    for img in images:
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        small = cv2.resize(g, (24, 16), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
        small -= small.mean()
        small /= np.linalg.norm(small) + 1e-6
        hsv = cv2.cvtColor(cv2.resize(img, (64, 64)), cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256]).ravel()
        hist /= np.linalg.norm(hist) + 1e-6
        descs.append(np.concatenate([small, 0.5 * hist]))
    D = np.array(descs)
    S = D @ D.T
    np.fill_diagonal(S, -np.inf)
    # Start from the image whose best neighbour is weakest (likely an end).
    start = int(np.argmin(S.max(axis=1)))
    order, used = [start], {start}
    while len(order) < n:
        row = S[order[-1]].copy()
        row[list(used)] = -np.inf
        nxt = int(np.argmax(row))
        order.append(nxt)
        used.add(nxt)
    return order, "visual-similarity"
