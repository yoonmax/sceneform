"""Serialisation of reconstruction outputs, with matching readers.

Every writer here has a reader used by the test-suite to round-trip files,
so exported files are verified rather than assumed valid.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..geometry.cameras import PinholeCamera, fov_from_focal, rotation_to_quaternion_xyzw

# ----------------------------------------------------------------- PLY
_PLY_TYPES = {
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
    "uchar": "u1", "uint8": "u1", "char": "i1", "int8": "i1",
    "ushort": "u2", "uint16": "u2", "short": "i2", "int16": "i2",
    "uint": "u4", "uint32": "u4", "int": "i4", "int32": "i4",
}


def write_point_ply(path: Path, points, colors=None, confidence=None, normals=None, comments=()) -> None:
    """Binary little-endian PLY readable by MeshLab, CloudCompare, Blender."""
    n = len(points)
    fields = [("x", "f4"), ("y", "f4"), ("z", "f4")]
    if normals is not None:
        fields += [("nx", "f4"), ("ny", "f4"), ("nz", "f4")]
    if colors is not None:
        fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
    if confidence is not None:
        fields += [("confidence", "f4")]
    arr = np.empty(n, dtype=[(k, "<" + t) for k, t in fields])
    arr["x"], arr["y"], arr["z"] = np.asarray(points, np.float32).T
    if normals is not None:
        arr["nx"], arr["ny"], arr["nz"] = np.asarray(normals, np.float32).T
    if colors is not None:
        arr["red"], arr["green"], arr["blue"] = np.asarray(colors, np.uint8).T
    if confidence is not None:
        arr["confidence"] = np.asarray(confidence, np.float32)
    inv = {"f4": "float", "u1": "uchar"}
    header = ["ply", "format binary_little_endian 1.0"]
    header += [f"comment {c}" for c in comments]
    header += [f"element vertex {n}"] + [f"property {inv[t]} {k}" for k, t in fields] + ["end_header"]
    with open(path, "wb") as fh:
        fh.write(("\n".join(header) + "\n").encode("ascii"))
        fh.write(arr.tobytes())


def read_ply(path: Path) -> dict[str, np.ndarray]:
    """Read the vertex element of a binary-LE or ASCII PLY file."""
    with open(path, "rb") as fh:
        if fh.readline().strip() != b"ply":
            raise ValueError("not a PLY file")
        fmt, n, props, in_vertex = None, 0, [], False
        while True:
            line = fh.readline().decode("ascii", "replace").strip()
            if line.startswith("format"):
                fmt = line.split()[1]
            elif line.startswith("element"):
                _, name, count = line.split()
                in_vertex = name == "vertex"
                if in_vertex:
                    n = int(count)
            elif line.startswith("property") and in_vertex:
                parts = line.split()
                if parts[1] == "list":
                    raise ValueError("list properties in the vertex element are not supported")
                props.append((parts[2], _PLY_TYPES[parts[1]]))
            elif line == "end_header":
                break
        if fmt == "binary_little_endian":
            dt = np.dtype([(k, "<" + t) for k, t in props])
            data = np.frombuffer(fh.read(n * dt.itemsize), dtype=dt, count=n)
        elif fmt == "ascii":
            rows = np.loadtxt(fh, max_rows=n, ndmin=2)
            data = {k: rows[:, i].astype(t) for i, (k, t) in enumerate(props)}
        else:
            raise ValueError(f"unsupported PLY format {fmt}")
    return {k: np.asarray(data[k]) for k, _ in props}


# ----------------------------------------------------------------- PCD
def write_pcd(path: Path, points, colors=None) -> None:
    """PCL point cloud (binary) with packed RGB."""
    n = len(points)
    pts = np.asarray(points, np.float32)
    fields, sizes, types, counts = ["x", "y", "z"], ["4"] * 3, ["F"] * 3, ["1"] * 3
    dt = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if colors is not None:
        fields.append("rgb"); sizes.append("4"); types.append("U"); counts.append("1")
        dt.append(("rgb", "<u4"))
    arr = np.empty(n, dtype=dt)
    arr["x"], arr["y"], arr["z"] = pts.T
    if colors is not None:
        c = np.asarray(colors, np.uint32)
        arr["rgb"] = (c[:, 0] << 16) | (c[:, 1] << 8) | c[:, 2]
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\n"
        f"FIELDS {' '.join(fields)}\nSIZE {' '.join(sizes)}\nTYPE {' '.join(types)}\nCOUNT {' '.join(counts)}\n"
        f"WIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {n}\nDATA binary\n"
    )
    with open(path, "wb") as fh:
        fh.write(header.encode("ascii"))
        fh.write(arr.tobytes())


def read_pcd(path: Path) -> dict[str, np.ndarray]:
    with open(path, "rb") as fh:
        meta = {}
        while True:
            line = fh.readline().decode("ascii").strip()
            if not line or line.startswith("#"):
                continue
            k, *v = line.split()
            meta[k] = v
            if k == "DATA":
                break
        if meta["DATA"][0] != "binary":
            raise ValueError("only binary PCD supported")
        tmap = {("F", "4"): "<f4", ("U", "4"): "<u4", ("F", "8"): "<f8"}
        dt = np.dtype([(f, tmap[(t, s)]) for f, t, s in zip(meta["FIELDS"], meta["TYPE"], meta["SIZE"])])
        n = int(meta["POINTS"][0])
        data = np.frombuffer(fh.read(n * dt.itemsize), dtype=dt, count=n)
    out = {"points": np.stack([data["x"], data["y"], data["z"]], 1)}
    if "rgb" in data.dtype.names:
        rgb = data["rgb"]
        out["colors"] = np.stack([(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255], 1).astype(np.uint8)
    return out


# ---------------------------------------------------------------- mesh
def write_mesh(path: Path, vertices, faces, colors=None) -> None:
    """GLB/GLTF/OBJ/PLY through trimesh (format from the extension)."""
    import trimesh

    m = trimesh.Trimesh(vertices, faces, vertex_colors=colors, process=False)
    m.export(path)


def read_mesh(path: Path):
    import trimesh

    return trimesh.load(path, force="mesh", process=False)


# ------------------------------------------------------------- cameras
def camera_record(name: str, cam: PinholeCamera, index: int, timestamp=None) -> dict:
    return {
        "index": index,
        "image": name,
        "timestamp": timestamp,
        "width": cam.width,
        "height": cam.height,
        "intrinsics": {
            "fx": float(cam.K[0, 0]), "fy": float(cam.K[1, 1]),
            "cx": float(cam.K[0, 2]), "cy": float(cam.K[1, 2]),
            "fovYDeg": fov_from_focal(cam.K[1, 1], cam.height) if cam.height else None,
            "model": "PINHOLE",
            "pixelConvention": "corner",
        },
        "extrinsics": {
            "convention": "opencv world-to-camera (x right, y down, z forward)",
            "R": cam.R.tolist(),
            "t": cam.t.tolist(),
            "quaternionXYZW": rotation_to_quaternion_xyzw(cam.R).tolist(),
        },
        "center": cam.center.tolist(),
        "threejs": cam.to_threejs(),
    }


def write_cameras_json(path: Path, records: list[dict], world: dict) -> None:
    path.write_text(json.dumps({"schema": "sceneform.cameras/1", "world": world, "cameras": records}, indent=1))


def write_colmap_text(directory: Path, names: list[str], cams: list[PinholeCamera], points=None, colors=None) -> None:
    """COLMAP text model (PINHOLE cameras) – loadable by COLMAP, Nerfstudio,
    gsplat and most splat trainers."""
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "cameras.txt", "w") as fh:
        fh.write("# CAMERA_ID MODEL WIDTH HEIGHT PARAMS[]\n")
        for i, c in enumerate(cams, 1):
            fh.write(f"{i} PINHOLE {c.width} {c.height} {c.K[0,0]:.6f} {c.K[1,1]:.6f} {c.K[0,2]:.6f} {c.K[1,2]:.6f}\n")
    with open(directory / "images.txt", "w") as fh:
        fh.write("# IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME\n# POINTS2D[] as (X, Y, POINT3D_ID)\n")
        for i, (n, c) in enumerate(zip(names, cams), 1):
            qx, qy, qz, qw = rotation_to_quaternion_xyzw(c.R)
            fh.write(f"{i} {qw:.9f} {qx:.9f} {qy:.9f} {qz:.9f} {c.t[0]:.9f} {c.t[1]:.9f} {c.t[2]:.9f} {i} {n}\n\n")
    with open(directory / "points3D.txt", "w") as fh:
        fh.write("# POINT3D_ID X Y Z R G B ERROR TRACK[]\n")
        if points is not None:
            for k, (p, col) in enumerate(zip(points, colors), 1):
                fh.write(f"{k} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {int(col[0])} {int(col[1])} {int(col[2])} 0\n")


# ------------------------------------------------------- web formats
def write_points_bin(path: Path, points, colors, confidence=None, source=None) -> dict:
    """Compact viewer format: interleaved-free arrays, little-endian.

    Layout: float32[N*3] positions | uint8[N*3] colors | uint8[N] confidence
    (0–255) | uint16[N] source view (65535 = none).  Offsets are returned
    for the manifest so the browser can create typed-array views directly.
    """
    n = len(points)
    pos = np.asarray(points, "<f4").tobytes()
    col = np.asarray(colors, np.uint8).tobytes()
    conf = (np.clip(np.asarray(confidence), 0, 1) * 255).astype(np.uint8).tobytes() if confidence is not None else b""
    src = np.asarray(source, "<u2").tobytes() if source is not None else b""
    pad = (-(len(pos) + len(col) + len(conf))) % 2
    with open(path, "wb") as fh:
        fh.write(pos + col + conf + b"\0" * pad + src)
    off_col = len(pos)
    off_conf = off_col + len(col)
    off_src = off_conf + len(conf) + pad
    return {
        "count": n,
        "position": {"offset": 0, "type": "float32", "components": 3},
        "color": {"offset": off_col, "type": "uint8", "components": 3},
        "confidence": {"offset": off_conf, "type": "uint8", "components": 1} if conf else None,
        "source": {"offset": off_src, "type": "uint16", "components": 1} if src else None,
        "bytes": off_src + len(src),
    }


def read_points_bin(path: Path, layout: dict) -> dict:
    raw = Path(path).read_bytes()
    n = layout["count"]
    out = {
        "points": np.frombuffer(raw, "<f4", n * 3, layout["position"]["offset"]).reshape(n, 3),
        "colors": np.frombuffer(raw, np.uint8, n * 3, layout["color"]["offset"]).reshape(n, 3),
    }
    if layout.get("confidence"):
        out["confidence"] = np.frombuffer(raw, np.uint8, n, layout["confidence"]["offset"]) / 255.0
    if layout.get("source"):
        out["source"] = np.frombuffer(raw, "<u2", n, layout["source"]["offset"])
    return out


def write_depth_u16(path: Path, depth: np.ndarray) -> dict:
    """Quantise a depth map linearly between its valid min and max.

    ``depth = near + v / 65534 * (far - near)``; v = 65535 marks invalid.
    """
    valid = depth > 0
    if not valid.any():
        near, far = 0.0, 1.0
    else:
        near, far = float(depth[valid].min()), float(depth[valid].max())
    q = np.full(depth.shape, 65535, np.uint16)
    q[valid] = np.round((depth[valid] - near) / max(far - near, 1e-12) * 65534).astype(np.uint16)
    path.write_bytes(q.astype("<u2").tobytes())
    return {"width": depth.shape[1], "height": depth.shape[0], "near": near, "far": far, "invalid": 65535, "scale": 65534}
