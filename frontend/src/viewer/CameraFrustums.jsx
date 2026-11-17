import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

/**
 * Estimated cameras as wireframe frustums, a capture-path line, and the
 * selected camera's photo on its image plane. All frustums share one
 * LineSegments geometry; picking uses one InstancedMesh.
 */
function frustumCorners(cam, depth) {
  const q = new THREE.Quaternion(...cam.threejs.quaternion);
  const pos = new THREE.Vector3(...cam.threejs.position);
  const fov = THREE.MathUtils.degToRad(cam.threejs.fovY);
  const h = Math.tan(fov / 2) * depth;
  const w = h * cam.threejs.aspect;
  const local = [
    [-w, h, -depth],
    [w, h, -depth],
    [w, -h, -depth],
    [-w, -h, -depth],
  ];
  return { pos, q, corners: local.map((c) => new THREE.Vector3(...c).applyQuaternion(q).add(pos)), w, h };
}

export default function CameraFrustums({ cameras, size, selected, onSelect, showPath, frameUrl, accent }) {
  const pickRef = useRef();
  const [tex, setTex] = useState(null);

  const lines = useMemo(() => {
    const pts = [];
    for (const cam of cameras) {
      const { pos, corners } = frustumCorners(cam, size);
      for (const c of corners) pts.push(pos, c);
      for (let i = 0; i < 4; i++) pts.push(corners[i], corners[(i + 1) % 4]);
      // small "up" tick so orientation is readable
      const up = corners[0].clone().lerp(corners[1], 0.5);
      const tip = up.clone().add(corners[0].clone().sub(corners[3]).multiplyScalar(0.25));
      pts.push(corners[0].clone().lerp(corners[1], 0.35), tip, tip, corners[0].clone().lerp(corners[1], 0.65));
    }
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    return g;
  }, [cameras, size]);
  useEffect(() => () => lines.dispose(), [lines]);

  const path = useMemo(() => {
    const ordered = [...cameras].sort((a, b) => (a.captureIndex ?? a.index) - (b.captureIndex ?? b.index));
    if (ordered.length < 2) return null;
    const curve = new THREE.CatmullRomCurve3(ordered.map((c) => new THREE.Vector3(...c.center)));
    return new THREE.BufferGeometry().setFromPoints(curve.getPoints(Math.min(1200, ordered.length * 12)));
  }, [cameras]);
  useEffect(() => () => path?.dispose(), [path]);

  useEffect(() => {
    const m = pickRef.current;
    if (!m) return;
    const d = new THREE.Object3D();
    cameras.forEach((c, i) => {
      d.position.set(...c.center);
      d.scale.setScalar(size * 0.45);
      d.updateMatrix();
      m.setMatrixAt(i, d.matrix);
    });
    m.instanceMatrix.needsUpdate = true;
    m.computeBoundingSphere();
  }, [cameras, size]);

  useEffect(() => {
    if (selected == null || !frameUrl) {
      setTex(null);
      return;
    }
    let live = true;
    new THREE.TextureLoader().load(frameUrl, (t) => {
      t.colorSpace = THREE.SRGBColorSpace;
      if (live) setTex(t);
      else t.dispose();
    });
    return () => {
      live = false;
    };
  }, [selected, frameUrl]);
  useEffect(() => () => tex?.dispose(), [tex]);

  const sel = selected != null ? cameras[selected] : null;
  const selGeom = useMemo(() => {
    if (!sel) return null;
    const { pos, corners } = frustumCorners(sel, size * 1.6);
    const pts = [];
    for (const c of corners) pts.push(pos, c);
    for (let i = 0; i < 4; i++) pts.push(corners[i], corners[(i + 1) % 4]);
    return new THREE.BufferGeometry().setFromPoints(pts);
  }, [sel, size]);
  useEffect(() => () => selGeom?.dispose(), [selGeom]);

  const plane = useMemo(() => {
    if (!sel) return null;
    const { pos, q, w, h } = frustumCorners(sel, size * 1.6);
    const center = new THREE.Vector3(0, 0, -size * 1.6).applyQuaternion(q).add(pos);
    return { center, q, w, h };
  }, [sel, size]);

  return (
    <group>
      <lineSegments geometry={lines}>
        <lineBasicMaterial color="#7d8188" transparent opacity={0.8} depthWrite={false} />
      </lineSegments>
      {showPath && path && (
        <line geometry={path}>
          <lineBasicMaterial color={accent} transparent opacity={0.9} />
        </line>
      )}
      {selGeom && (
        <lineSegments geometry={selGeom}>
          <lineBasicMaterial color={accent} linewidth={2} />
        </lineSegments>
      )}
      {plane && tex && (
        <mesh position={plane.center} quaternion={plane.q}>
          <planeGeometry args={[plane.w * 2, plane.h * 2]} />
          <meshBasicMaterial map={tex} side={THREE.DoubleSide} transparent opacity={0.92} toneMapped={false} />
        </mesh>
      )}
      <instancedMesh
        ref={pickRef}
        args={[undefined, undefined, cameras.length]}
        onClick={(e) => {
          e.stopPropagation();
          onSelect?.(e.instanceId);
        }}
        onPointerOver={(e) => {
          e.stopPropagation();
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => (document.body.style.cursor = "")}
      >
        <sphereGeometry args={[1, 10, 8]} />
        <meshBasicMaterial color={accent} transparent opacity={0.0} depthWrite={false} />
      </instancedMesh>
      {cameras.map((c, i) => (
        <mesh key={i} position={c.center} scale={size * (i === selected ? 0.12 : 0.07)}>
          <sphereGeometry args={[1, 8, 6]} />
          <meshBasicMaterial color={i === selected ? accent : "#7d8188"} />
        </mesh>
      ))}
    </group>
  );
}
