import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { CameraControls, GizmoHelper, GizmoViewport, Grid, Html, OrthographicCamera, PerformanceMonitor, PerspectiveCamera } from "@react-three/drei";
import gsap from "gsap";
import PointCloudLayer from "./PointCloudLayer.jsx";
import { lazy, Suspense } from "react";
const SplatLayer = lazy(() => import("./SplatLayer.jsx"));
import MeshLayer from "./MeshLayer.jsx";
import CameraFrustums from "./CameraFrustums.jsx";
import { useStore } from "../state/store.js";

const HELPER_LAYER = 1;
const DPR = { performance: [1, 1], balanced: [1, 1.5], quality: [1, 2] };

function cssVar(name, fallback) {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function OnHelperLayer({ children }) {
  const ref = useRef();
  useEffect(() => {
    ref.current?.traverse((o) => o.layers.set(HELPER_LAYER));
  });
  return <group ref={ref}>{children}</group>;
}

function EnableHelperLayer() {
  const { camera } = useThree();
  useEffect(() => {
    camera.layers.enable(HELPER_LAYER);
  }, [camera]);
  return null;
}

function Measurement({ points, unitsLabel, scaleFactor }) {
  if (!points.length) return null;
  const [a, b] = points;
  const dist = b ? new THREE.Vector3(...a).distanceTo(new THREE.Vector3(...b)) : null;
  const mid = b ? new THREE.Vector3(...a).add(new THREE.Vector3(...b)).multiplyScalar(0.5) : null;
  const accent = cssVar("--accent", "#1f4e8c");
  return (
    <group>
      {points.map((p, i) => (
        <mesh key={i} position={p} renderOrder={10}>
          <sphereGeometry args={[scaleFactor * 0.012, 16, 12]} />
          <meshBasicMaterial color={accent} depthTest={false} />
        </mesh>
      ))}
      {b && (
        <>
          <line renderOrder={10}>
            <bufferGeometry onUpdate={(g) => g.setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...b)])} />
            <lineBasicMaterial color={accent} depthTest={false} />
          </line>
          <Html position={mid} center zIndexRange={[20, 0]}>
            <div className="chip tabular" style={{ background: "var(--ink)", color: "var(--bg)", border: 0 }}>
              {dist.toFixed(3)} {unitsLabel}
            </div>
          </Html>
        </>
      )}
    </group>
  );
}

const keys = new Set();
function FlyKeys({ controls, enabled, speed }) {
  useEffect(() => {
    if (!enabled) return;
    const down = (e) => {
      if (e.target.closest("input,textarea,select")) return;
      keys.add(e.key.toLowerCase());
    };
    const up = (e) => keys.delete(e.key.toLowerCase());
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      keys.clear();
    };
  }, [enabled]);
  useFrame((_, dt) => {
    const c = controls.current;
    if (!enabled || !c) return;
    const s = speed * dt * (keys.has("shift") ? 3 : 1);
    if (keys.has("w") || keys.has("arrowup")) c.forward(s, false);
    if (keys.has("s") || keys.has("arrowdown")) c.forward(-s, false);
    if (keys.has("a") || keys.has("arrowleft")) c.truck(-s, 0, false);
    if (keys.has("d") || keys.has("arrowright")) c.truck(s, 0, false);
    if (keys.has("e")) c.elevate(s, false);
    if (keys.has("q")) c.elevate(-s, false);
  });
  return null;
}

const Inner = forwardRef(function Inner(props, ref) {
  const {
    manifest, cameras, points, sparse, keepMask, transform, view, tool, splatUrl, meshUrl, frameUrl,
    selectedCamera, onSelectCamera, measurePoints, onPick, onHover, onLayerStatus, unitsLabel, sync, syncId,
    scaleBar, scaleText,
  } = props;
  const { camera, gl, scene, size, invalidate } = useThree();
  const controls = useRef();
  const editGroup = useRef();
  const replayTween = useRef(null);
  const radius = Math.max(manifest.bounds.radius, 1e-3);
  const center = useMemo(() => new THREE.Vector3(...manifest.bounds.center), [manifest]);
  const accent = cssVar("--accent", "#1f4e8c");
  const frustumSize = radius * 0.06;
  const replaying = useStore((s) => s.replaying);
  const setReplaying = useStore((s) => s.setReplaying);

  const editMatrix = useMemo(() => {
    const m = new THREE.Matrix4();
    if (transform) m.fromArray(Array.from(transform));
    return m;
  }, [transform]);

  useEffect(() => {
    if (!editGroup.current) return;
    editGroup.current.matrix.copy(editMatrix);
    editGroup.current.matrixWorldNeedsUpdate = true;
  }, [editMatrix]);

  const worldCamPose = useCallback(
    (cam) => {
      const pos = new THREE.Vector3(...cam.threejs.position).applyMatrix4(editMatrix);
      const rot = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().extractRotation(editMatrix));
      const q = rot.multiply(new THREE.Quaternion(...cam.threejs.quaternion));
      return { pos, q };
    },
    [editMatrix],
  );

  const homeView = useCallback(
    (animate = true) => {
      const c = controls.current;
      if (!c) return;
      const first = cameras?.cameras?.[0];
      let dir = new THREE.Vector3(0.35, 0.45, 1).normalize();
      if (first) {
        const p = new THREE.Vector3(...first.center).sub(center);
        p.y = Math.max(p.y, radius * 0.4);
        if (p.length() > 1e-6) dir = p.normalize();
      }
      const d = radius * 2.6;
      const target = center.clone().applyMatrix4(editMatrix);
      c.setLookAt(target.x + dir.x * d, target.y + dir.y * d, target.z + dir.z * d, target.x, target.y, target.z, animate);
    },
    [cameras, center, radius, editMatrix],
  );

  useEffect(() => {
    if (import.meta.env.DEV) window.__sf = { camera, controls, scene };
  });

  useEffect(() => {
    homeView(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manifest.id, camera]);

  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    if (tool === "fly") {
      const dir = new THREE.Vector3();
      camera.getWorldDirection(dir);
      const p = camera.position.clone();
      const t = p.clone().add(dir.multiplyScalar(radius * 0.02));
      c.setLookAt(p.x, p.y, p.z, t.x, t.y, t.z, false);
      c.minDistance = radius * 0.01;
      c.maxDistance = radius * 0.03;
    } else {
      c.minDistance = radius * 0.02;
      c.maxDistance = radius * 40;
    }
  }, [tool, camera, radius]);

  // Scale bar: world length that spans ~80–160 px at the orbit target,
  // rounded to 1/2/5×10^k. Written straight to the DOM (no re-render).
  const lastScale = useRef("");
  useFrame(() => {
    if (!scaleBar?.current || !controls.current) return;
    let perPx;
    if (camera.isPerspectiveCamera) {
      const d = camera.position.distanceTo(controls.current.getTarget(new THREE.Vector3()));
      perPx = (2 * d * Math.tan((camera.fov * Math.PI) / 360)) / size.height;
    } else perPx = (camera.top - camera.bottom) / camera.zoom / size.height;
    const target = perPx * 110;
    const k = Math.pow(10, Math.floor(Math.log10(target)));
    const nice = [1, 2, 5, 10].map((m) => m * k).reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
    const px = Math.round(nice / perPx);
    const label = `${nice >= 1 ? nice.toFixed(nice % 1 ? 1 : 0) : nice.toPrecision(1)} ${unitsLabel || "units"}`;
    const key = `${px}|${label}`;
    if (key !== lastScale.current) {
      lastScale.current = key;
      scaleBar.current.style.width = `${px}px`;
      if (scaleText?.current) scaleText.current.textContent = label;
    }
  });

  // Synchronised cameras (comparison view): whichever viewer the user is
  // driving publishes its pose; the others follow without animation.
  const driving = useRef(false);
  const seen = useRef(-1);
  useEffect(() => {
    const c = controls.current;
    if (!c || !sync) return;
    const on = () => (driving.current = true);
    const off = () => (driving.current = false);
    c.addEventListener("controlstart", on);
    c.addEventListener("controlend", off);
    return () => {
      c.removeEventListener("controlstart", on);
      c.removeEventListener("controlend", off);
    };
  }, [sync]);
  useFrame(() => {
    const c = controls.current;
    if (!sync || !c) return;
    const s = sync.current;
    if (driving.current || (c.active && s.owner === syncId)) {
      const pos = c.getPosition(new THREE.Vector3());
      const tgt = c.getTarget(new THREE.Vector3());
      s.pos = pos.toArray();
      s.target = tgt.toArray();
      s.owner = syncId;
      s.ver = (s.ver || 0) + 1;
      seen.current = s.ver;
    } else if (s.ver && s.ver !== seen.current && s.owner !== syncId) {
      seen.current = s.ver;
      c.setLookAt(...s.pos, ...s.target, false);
    }
  });

  useImperativeHandle(ref, () => ({
    home: () => homeView(true),
    fit: () => {
      const s = new THREE.Sphere(center.clone().applyMatrix4(editMatrix), radius * 1.05);
      controls.current?.fitToSphere(s, true);
    },
    preset(name) {
      const c = controls.current;
      const t = center.clone().applyMatrix4(editMatrix);
      const d = radius * 2.8;
      if (name === "top") c.setLookAt(t.x, t.y + d, t.z + 1e-4, t.x, t.y, t.z, true);
      else if (name === "front") c.setLookAt(t.x, t.y, t.z + d, t.x, t.y, t.z, true);
      else if (name === "side") c.setLookAt(t.x + d, t.y, t.z, t.x, t.y, t.z, true);
      else homeView(true);
    },
    goToCamera(i) {
      const cam = cameras.cameras[i];
      if (!cam) return;
      const { pos, q } = worldCamPose(cam);
      const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
      const t = pos.clone().add(fwd.multiplyScalar(radius * 0.8));
      if (camera.isPerspectiveCamera) {
        gsap.to(camera, { fov: cam.threejs.fovY, duration: 0.6, onUpdate: () => camera.updateProjectionMatrix() });
      }
      controls.current.setLookAt(pos.x, pos.y, pos.z, t.x, t.y, t.z, true);
    },
    replay() {
      const list = [...cameras.cameras].sort((a, b) => (a.captureIndex ?? a.index) - (b.captureIndex ?? b.index));
      if (list.length < 2) return;
      const poses = list.map(worldCamPose);
      const curve = new THREE.CatmullRomCurve3(poses.map((p) => p.pos));
      const state = { t: 0 };
      controls.current.enabled = false;
      setReplaying(true);
      const tmp = new THREE.Quaternion();
      replayTween.current = gsap.to(state, {
        t: 1,
        duration: Math.min(30, 4 + list.length * 0.18),
        ease: "none",
        onUpdate: () => {
          camera.position.copy(curve.getPointAt(state.t));
          const f = state.t * (poses.length - 1);
          const i = Math.min(poses.length - 2, Math.floor(f));
          tmp.copy(poses[i].q).slerp(poses[i + 1].q, f - i);
          camera.quaternion.copy(tmp);
          invalidate();
        },
        onComplete: () => this.stopReplay(),
      });
    },
    stopReplay() {
      replayTween.current?.kill();
      replayTween.current = null;
      const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
      const p = camera.position;
      const t = p.clone().add(fwd.multiplyScalar(radius));
      controls.current.enabled = true;
      controls.current.setLookAt(p.x, p.y, p.z, t.x, t.y, t.z, false);
      setReplaying(false);
    },
    screenshot(scale = 2) {
      const prev = gl.getPixelRatio();
      gl.setPixelRatio(prev * scale);
      gl.render(scene, camera);
      const url = gl.domElement.toDataURL("image/png");
      gl.setPixelRatio(prev);
      gl.render(scene, camera);
      return url;
    },
    /** Render the scene from source camera i at w×h. Returns ImageData whose
     *  alpha marks pixels the reconstruction actually covers. */
    capture(i, w, h) {
      const cam = cameras.cameras[i];
      const { pos, q } = worldCamPose(cam);
      const pc = new THREE.PerspectiveCamera(cam.threejs.fovY, w / h, radius * 0.002, radius * 200);
      pc.position.copy(pos);
      pc.quaternion.copy(q);
      pc.updateMatrixWorld();
      pc.layers.set(0);
      const rt = new THREE.WebGLRenderTarget(w, h, { samples: 4, colorSpace: THREE.SRGBColorSpace });
      const prevTarget = gl.getRenderTarget();
      const prevClear = gl.getClearAlpha();
      const prevBg = scene.background;
      const scales = [];
      scene.traverse((o) => {
        const u = o.material?.uniforms?.uScale;
        if (u) {
          scales.push([u, u.value]);
          u.value = h / (2 * Math.tan((cam.threejs.fovY * Math.PI) / 360));
        }
      });
      scene.background = null;
      gl.setClearAlpha(0);
      gl.setRenderTarget(rt);
      gl.clear();
      gl.render(scene, pc);
      const buf = new Uint8Array(w * h * 4);
      gl.readRenderTargetPixels(rt, 0, 0, w, h, buf);
      gl.setRenderTarget(prevTarget);
      gl.setClearAlpha(prevClear);
      scene.background = prevBg;
      scales.forEach(([u, v]) => (u.value = v));
      rt.dispose();
      const img = new ImageData(w, h);
      for (let y = 0; y < h; y++) img.data.set(buf.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);
      return img;
    },
  }));

  const pickable = tool === "measure";
  const showPoints = view.layer === "points" || !splatUrl && view.layer === "splat" || !meshUrl && view.layer === "mesh";
  const pointData = view.pointSet === "sparse" && sparse ? sparse : points;

  return (
    <>
      <EnableHelperLayer />
      <CameraControls
        ref={controls}
        makeDefault
        smoothTime={0.18}
        draggingSmoothTime={0.08}
        dollySpeed={0.6}
        infinityDolly={tool === "fly"}
        enabled={!replaying}
      />
      <FlyKeys controls={controls} enabled={tool === "fly"} speed={radius * 0.6} />
      <group ref={editGroup} matrixAutoUpdate={false}>
        {showPoints && pointData && (
          <PointCloudLayer
            data={pointData}
            keepMask={pointData === points ? keepMask : null}
            view={view}
            radius={radius}
            highlightSource={selectedCamera}
            pickable={pickable}
            onPick={onPick}
            onHover={tool === "measure" ? onHover : null}
          />
        )}
        {view.layer === "splat" && splatUrl && (
          <Suspense fallback={null}>
          <SplatLayer
            url={splatUrl}
            transform={manifest.splat.transform}
            onProgress={(p) => onLayerStatus?.({ layer: "splat", progress: p })}
            onLoad={() => onLayerStatus?.({ layer: "splat", ready: true })}
            onError={(e) => onLayerStatus?.({ layer: "splat", error: String(e?.message || e) })}
          />
          </Suspense>
        )}
        {view.layer === "mesh" && meshUrl && (
          <MeshLayer
            url={meshUrl}
            onLoad={() => onLayerStatus?.({ layer: "mesh", ready: true })}
            onError={(e) => onLayerStatus?.({ layer: "mesh", error: String(e?.message || e) })}
          />
        )}
        <OnHelperLayer>
          {view.showCameras && cameras && (
            <CameraFrustums
              cameras={cameras.cameras}
              size={frustumSize}
              selected={selectedCamera}
              onSelect={onSelectCamera}
              showPath={view.showPath}
              frameUrl={frameUrl}
              accent={accent}
            />
          )}
          {view.showBounds && (
            <box3Helper args={[new THREE.Box3(new THREE.Vector3(...manifest.bounds.min), new THREE.Vector3(...manifest.bounds.max)), accent]} />
          )}
        </OnHelperLayer>
      </group>
      <OnHelperLayer>
        <Measurement points={measurePoints} unitsLabel={unitsLabel} scaleFactor={radius} />
        {view.showGrid && view.layer !== "splat" && (
          <Grid
            position={[0, 0, 0]}
            args={[radius * 8, radius * 8]}
            cellSize={radius / 10}
            sectionSize={radius / 2}
            cellColor={cssVar("--line", "#dedcd6")}
            sectionColor={cssVar("--line-strong", "#c9c6bf")}
            fadeDistance={radius * 9}
            fadeStrength={1.5}
            infiniteGrid
            followCamera={false}
          />
        )}
      </OnHelperLayer>
      {view.showAxes && (
        <GizmoHelper alignment="bottom-right" margin={[56, 76]}>
          <GizmoViewport axisColors={[cssVar("--axis-x", "#c0392b"), cssVar("--axis-y", "#2e7d32"), cssVar("--axis-z", "#1f4e8c")]} labelColor="#fff" axisHeadScale={0.9} />
        </GizmoHelper>
      )}
    </>
  );
});

const SceneViewer = forwardRef(function SceneViewer(props, ref) {
  const { manifest, view } = props;
  const renderQuality = useStore((s) => s.renderQuality);
  const [dpr, setDpr] = useState(DPR[renderQuality][1]);
  const [, setReady] = useState(0);
  const radius = Math.max(manifest.bounds.radius, 1e-3);
  const bg = view.background === "dark" ? "#111214" : view.background === "light" ? "#fafaf8" : null;

  useEffect(() => setDpr(DPR[renderQuality][1]), [renderQuality]);

  return (
    <div className="absolute inset-0" style={{ background: bg || "var(--canvas)" }}>
      <Canvas
        dpr={dpr}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance", preserveDrawingBuffer: false }}
        onCreated={({ gl }) => {
          gl.setClearColor(0x000000, 0);
          // R3F renders children only once the renderer is ready; if that
          // lands after the first layout effect, a re-render is needed.
          setReady((n) => n + 1);
        }}
        aria-label="Interactive 3D view of the reconstruction"
        role="img"
      >
        <PerformanceMonitor
          onDecline={() => setDpr((d) => Math.max(DPR[renderQuality][0], d - 0.25))}
          onIncline={() => setDpr((d) => Math.min(DPR[renderQuality][1], d + 0.25))}
        />
        {view.projection === "orthographic" && view.layer !== "splat" ? (
          <OrthographicCamera makeDefault position={[0, radius * 2, radius * 4]} zoom={120 / radius} near={-radius * 50} far={radius * 100} />
        ) : (
          <PerspectiveCamera makeDefault fov={50} position={[0, radius, radius * 3]} near={radius * 0.002} far={radius * 400} />
        )}
        <Suspense fallback={null}>
          <Inner ref={ref} {...props} />
        </Suspense>
      </Canvas>
    </div>
  );
});

export default SceneViewer;
