// Non-destructive edit operations. Mirrors backend/app/pipeline/edits.py so
// client-side exports (examples) and server exports (projects) agree.
//
// Matrices are plain column-major Float64Array(16) to keep this module free of
// three.js and unit-testable in Node.

export const GEOMETRY_OPS = new Set(["rotate", "recenter", "alignGround", "scale", "scaleReference"]);

export function identity() {
  const m = new Float64Array(16);
  m[0] = m[5] = m[10] = m[15] = 1;
  return m;
}

export function multiply(a, b) {
  // a * b, column-major
  const o = new Float64Array(16);
  for (let c = 0; c < 4; c++)
    for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
  return o;
}

function fromRotation(R, t = [0, 0, 0], s = 1) {
  const m = identity();
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) m[c * 4 + r] = s * R[r][c];
  m[12] = t[0];
  m[13] = t[1];
  m[14] = t[2];
  return m;
}

function axisAngle(axis, rad) {
  const n = Math.hypot(...axis) || 1;
  const [x, y, z] = axis.map((v) => v / n);
  const c = Math.cos(rad),
    s = Math.sin(rad),
    C = 1 - c;
  return [
    [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
    [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
    [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
  ];
}

export function rotationBetween(a, b) {
  const na = Math.hypot(...a),
    nb = Math.hypot(...b);
  const u = a.map((v) => v / na),
    w = b.map((v) => v / nb);
  const v = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
  const c = u[0] * w[0] + u[1] * w[1] + u[2] * w[2];
  if (c < -1 + 1e-10) {
    let ax = [0, -u[2], u[1]];
    if (Math.hypot(...ax) < 1e-6) ax = [u[2], 0, -u[0]];
    return axisAngle(ax, Math.PI);
  }
  const K = [
    [0, -v[2], v[1]],
    [v[2], 0, -v[0]],
    [-v[1], v[0], 0],
  ];
  const K2 = K.map((row, i) => row.map((_, j) => K[i][0] * K[0][j] + K[i][1] * K[1][j] + K[i][2] * K[2][j]));
  const f = 1 / (1 + c);
  return [0, 1, 2].map((i) => [0, 1, 2].map((j) => (i === j ? 1 : 0) + K[i][j] + K2[i][j] * f));
}

export function opMatrix(op) {
  const p = op.params || {};
  switch (op.type) {
    case "rotate":
      return fromRotation(axisAngle(p.axis || [0, 1, 0], ((p.degrees || 0) * Math.PI) / 180));
    case "recenter": {
      const c = p.center || [0, 0, 0];
      return fromRotation(
        [
          [1, 0, 0],
          [0, 1, 0],
          [0, 0, 1],
        ],
        [-c[0], -c[1], -c[2]],
      );
    }
    case "alignGround": {
      const R = rotationBetween(p.normal, [0, 1, 0]);
      const pt = p.point || [0, 0, 0];
      const qy = R[1][0] * pt[0] + R[1][1] * pt[1] + R[1][2] * pt[2];
      return fromRotation(R, [0, -qy, 0]);
    }
    case "scale":
    case "scaleReference": {
      const f = p.factor != null ? p.factor : p.actual / Math.max(p.measured, 1e-12);
      if (!(f > 0) || !Number.isFinite(f)) throw new Error("Scale factor must be positive");
      return fromRotation(
        [
          [1, 0, 0],
          [0, 1, 0],
          [0, 0, 1],
        ],
        [0, 0, 0],
        f,
      );
    }
    default:
      return null;
  }
}

/** Product of all geometric ops (applied in order). */
export function totalTransform(ops) {
  let T = identity();
  for (const op of ops) {
    const M = opMatrix(op);
    if (M) T = multiply(M, T);
  }
  return T;
}

export function unitsFor(ops) {
  let u = { kind: "relative", unit: null };
  for (const op of ops) if (op.type === "scaleReference") u = { kind: "scale-estimated", unit: op.params.unit || "m" };
  return u;
}

/**
 * Replay the stack over positions. Returns { positions (Float32Array, edited),
 * keep (Uint8Array mask over the original points) }. Crop boxes are evaluated
 * in the frame current at that point of the stack, as on the server.
 */
export function applyEdits(positions, ops) {
  const n = positions.length / 3;
  const P = new Float32Array(positions);
  const keep = new Uint8Array(n).fill(1);
  for (const op of ops) {
    const M = opMatrix(op);
    if (M) {
      for (let i = 0; i < n; i++) {
        const x = P[i * 3],
          y = P[i * 3 + 1],
          z = P[i * 3 + 2];
        P[i * 3] = M[0] * x + M[4] * y + M[8] * z + M[12];
        P[i * 3 + 1] = M[1] * x + M[5] * y + M[9] * z + M[13];
        P[i * 3 + 2] = M[2] * x + M[6] * y + M[10] * z + M[14];
      }
    } else if (op.type === "crop") {
      const { min, max } = op.params;
      for (let i = 0; i < n; i++) {
        if (!keep[i]) continue;
        for (let k = 0; k < 3; k++) {
          const v = P[i * 3 + k];
          if (v < min[k] || v > max[k]) {
            keep[i] = 0;
            break;
          }
        }
      }
    } else if (op.type === "removePoints") {
      for (const idx of op.params.indices || []) if (idx >= 0 && idx < n) keep[idx] = 0;
    }
  }
  return { positions: P, keep };
}

/** Undo/redo stack over an immutable list of ops. */
export class EditHistory {
  constructor(ops = []) {
    this.past = [];
    this.present = ops;
    this.future = [];
  }
  push(op) {
    this.past.push(this.present);
    this.present = [...this.present, { ...op, id: op.id || Math.random().toString(36).slice(2, 10) }];
    this.future = [];
    return this.present;
  }
  undo() {
    if (!this.past.length) return this.present;
    this.future.push(this.present);
    this.present = this.past.pop();
    return this.present;
  }
  redo() {
    if (!this.future.length) return this.present;
    this.past.push(this.present);
    this.present = this.future.pop();
    return this.present;
  }
  reset() {
    if (!this.present.length) return this.present;
    this.past.push(this.present);
    this.present = [];
    this.future = [];
    return this.present;
  }
  get canUndo() {
    return this.past.length > 0;
  }
  get canRedo() {
    return this.future.length > 0;
  }
}
