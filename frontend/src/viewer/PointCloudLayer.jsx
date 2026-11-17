import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { TURBO_GLSL } from "../lib/colormap.js";

const MODES = { rgb: 0, white: 1, confidence: 2, depth: 3, density: 4 };

const vertex = /* glsl */ `
attribute vec3 color;
attribute float confidence;
attribute float keep;
attribute float source;
attribute float density;
uniform float uSize;
uniform float uScale;
uniform float uMinConf;
uniform int uMode;
uniform float uHighlight;
uniform vec2 uDepthRange;
uniform float uExposure;
uniform bool uOrtho;
varying vec3 vColor;
varying float vAlpha;
${TURBO_GLSL}
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  bool visible = keep > 0.5 && confidence >= uMinConf;
  float dist = max(-mv.z, 1e-4);
  float size = uOrtho ? uSize * uScale : uSize * uScale / dist;
  gl_PointSize = visible ? clamp(size, 1.0, 64.0) : 0.0;
  if (!visible) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
  vec3 c = color;
  if (uMode == 1) c = vec3(0.86);
  else if (uMode == 2) c = turbo(confidence);
  else if (uMode == 3) c = turbo(1.0 - (dist - uDepthRange.x) / max(uDepthRange.y - uDepthRange.x, 1e-6));
  else if (uMode == 4) c = turbo(density);
  c *= uExposure;
  if (uHighlight >= 0.0 && abs(source - uHighlight) < 0.5) c = mix(c, vec3(0.12, 0.45, 0.95), 0.7);
  vColor = c;
  vAlpha = 1.0;
}`;

const fragment = /* glsl */ `
varying vec3 vColor;
void main() {
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  if (dot(p, p) > 1.0) discard;
  gl_FragColor = vec4(vColor, 1.0);
  #include <colorspace_fragment>
}`;

/** Lazily computed per-point density in [0,1] from a voxel hash (O(N)). */
export function computeDensity(positions, cell) {
  const n = positions.length / 3;
  const map = new Map();
  const k = new Array(n);
  for (let i = 0; i < n; i++) {
    const key = `${Math.floor(positions[i * 3] / cell)},${Math.floor(positions[i * 3 + 1] / cell)},${Math.floor(positions[i * 3 + 2] / cell)}`;
    k[i] = key;
    map.set(key, (map.get(key) || 0) + 1);
  }
  const counts = [...map.values()].sort((a, b) => a - b);
  const lo = counts[Math.floor(counts.length * 0.05)] || 1;
  const hi = counts[Math.floor(counts.length * 0.95)] || 1;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = Math.min(1, Math.max(0, (map.get(k[i]) - lo) / Math.max(1, hi - lo)));
  return out;
}

export default function PointCloudLayer({ data, keepMask, view, highlightSource = -1, radius = 1, onPick, onHover, pickable }) {
  const pointsRef = useRef();
  const { size, camera } = useThree();

  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(data.positions, 3));
    g.setAttribute("color", new THREE.BufferAttribute(data.colors, 3, true));
    const conf = data.confidence || new Uint8Array(data.count).fill(255);
    g.setAttribute("confidence", new THREE.BufferAttribute(conf, 1, true));
    g.setAttribute("source", new THREE.BufferAttribute(data.source ? new Float32Array(data.source) : new Float32Array(data.count).fill(-1), 1));
    g.setAttribute("keep", new THREE.BufferAttribute(new Uint8Array(data.count).fill(1), 1));
    g.setAttribute("density", new THREE.BufferAttribute(new Float32Array(data.count), 1));
    g.computeBoundingSphere();
    return g;
  }, [data]);

  useEffect(() => () => geometry.dispose(), [geometry]);

  useEffect(() => {
    const attr = geometry.getAttribute("keep");
    if (keepMask) attr.array.set(keepMask);
    else attr.array.fill(1);
    attr.needsUpdate = true;
  }, [geometry, keepMask]);

  useEffect(() => {
    if (view.colorMode !== "density" || geometry.userData.hasDensity) return;
    const d = computeDensity(data.positions, radius / 120);
    geometry.getAttribute("density").array.set(d);
    geometry.getAttribute("density").needsUpdate = true;
    geometry.userData.hasDensity = true;
  }, [view.colorMode, geometry, data, radius]);

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: vertex,
        fragmentShader: fragment,
        uniforms: {
          uSize: { value: 1 },
          uScale: { value: 1 },
          uMinConf: { value: 0 },
          uMode: { value: 0 },
          uHighlight: { value: -1 },
          uDepthRange: { value: new THREE.Vector2(0, 1) },
          uExposure: { value: 1 },
          uOrtho: { value: false },
        },
      }),
    [],
  );
  useEffect(() => () => material.dispose(), [material]);

  useFrame(() => {
    const u = material.uniforms;
    const ortho = camera.isOrthographicCamera;
    u.uOrtho.value = ortho;
    // World-space point size: radius-relative so scenes of any scale look alike.
    const worldSize = (view.pointSize * radius) / 900;
    if (ortho) u.uScale.value = (camera.zoom * size.height) / (camera.top - camera.bottom);
    else u.uScale.value = size.height / (2 * Math.tan((camera.fov * Math.PI) / 360));
    u.uSize.value = worldSize;
    u.uMinConf.value = data.confidence ? view.confidence : 0;
    u.uMode.value = MODES[view.colorMode] ?? 0;
    u.uHighlight.value = highlightSource ?? -1;
    u.uExposure.value = view.exposure;
    const d = camera.position.length();
    u.uDepthRange.value.set(Math.max(0.01, d - radius * 1.2), d + radius * 1.2);
  });

  const visibleHit = (hits) => {
    const keep = geometry.getAttribute("keep").array;
    const conf = geometry.getAttribute("confidence").array;
    const thr = data.confidence ? Math.round(view.confidence * 255) : 0;
    return hits.find((h) => keep[h.index] && conf[h.index] >= thr);
  };

  return (
    <points
      ref={pointsRef}
      geometry={geometry}
      material={material}
      frustumCulled={false}
      onClick={
        pickable
          ? (e) => {
              const h = visibleHit(e.intersections.filter((x) => x.object === pointsRef.current));
              if (h) {
                e.stopPropagation();
                onPick?.({ point: h.point.toArray(), index: h.index });
              }
            }
          : undefined
      }
      onPointerMove={
        onHover
          ? (e) => {
              const h = visibleHit(e.intersections.filter((x) => x.object === pointsRef.current));
              onHover(h ? { point: h.point.toArray(), index: h.index } : null);
            }
          : undefined
      }
    />
  );
}
