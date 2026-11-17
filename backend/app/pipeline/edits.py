"""Non-destructive edit operations, mirrored by ``frontend/src/editing``.

The original reconstruction is never modified.  An edit stack is a list of
operations; geometry exports replay it.  Semantics:

* ``rotate``      {axis:[x,y,z], degrees}          – about the origin
* ``recenter``    {center:[x,y,z]}                 – translate by -center
* ``alignGround`` {normal:[x,y,z], point:[x,y,z]}  – rotate normal → +Y, put point at y=0
* ``scale``       {factor} | {measured, actual, unit} – uniform scale; a scale
                  reference also records the unit so measurements can be
                  labelled "scale-estimated"
* ``crop``        {min:[...], max:[...]}           – keep points inside the box
                  (box expressed in the edited frame at that point of the stack)
* ``removePoints``{indices:[...]}                  – drop by original index
* ``hideRegion``, ``display``, ``cameraPreset``     – viewer only, ignored here
"""

from __future__ import annotations

import numpy as np

from ..geometry.transforms import rotation_between, so3_exp


def _affine(R=np.eye(3), t=np.zeros(3), s=1.0) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = s * np.asarray(R)
    T[:3, 3] = t
    return T


def op_matrix(op: dict) -> np.ndarray | None:
    t, p = op.get("type"), op.get("params", {})
    if t == "rotate":
        axis = np.asarray(p.get("axis", [0, 1, 0]), float)
        axis /= np.linalg.norm(axis) + 1e-12
        return _affine(so3_exp(axis * np.radians(float(p.get("degrees", 0)))))
    if t == "recenter":
        return _affine(t=-np.asarray(p.get("center", [0, 0, 0]), float))
    if t == "alignGround":
        n = np.asarray(p["normal"], float)
        R = rotation_between(n, [0.0, 1.0, 0.0])
        q = R @ np.asarray(p.get("point", [0, 0, 0]), float)
        return _affine(R, t=np.array([0.0, -q[1], 0.0]))
    if t in ("scale", "scaleReference"):
        if "factor" in p:
            f = float(p["factor"])
        else:
            f = float(p["actual"]) / max(float(p["measured"]), 1e-12)
        if not np.isfinite(f) or f <= 0:
            raise ValueError("scale factor must be positive")
        return _affine(s=f)
    return None


def apply_edits(points: np.ndarray, ops: list[dict]) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return (edited points, keep-mask over the input, unit info)."""
    P = np.asarray(points, np.float64).copy()
    keep = np.ones(len(P), bool)
    unit = {"kind": "relative", "unit": None}
    for op in ops:
        M = op_matrix(op)
        if M is not None:
            P = P @ M[:3, :3].T + M[:3, 3]
            if op["type"] == "scaleReference":
                unit = {"kind": "scale-estimated", "unit": op["params"].get("unit", "m")}
            continue
        t, p = op.get("type"), op.get("params", {})
        if t == "crop":
            mn, mx = np.asarray(p["min"], float), np.asarray(p["max"], float)
            keep &= np.all((P >= mn) & (P <= mx), axis=1)
        elif t == "removePoints":
            idx = np.asarray(p.get("indices", []), np.int64)
            idx = idx[(idx >= 0) & (idx < len(P))]
            keep[idx] = False
    return P, keep, unit


def total_transform(ops: list[dict]) -> np.ndarray:
    T = np.eye(4)
    for op in ops:
        M = op_matrix(op)
        if M is not None:
            T = M @ T
    return T
