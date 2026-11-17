import { useEffect, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

export default function MeshLayer({ url, wireframe = false, onLoad, onError }) {
  const [obj, setObj] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let loaded = null;
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (cancelled) return;
        gltf.scene.traverse((o) => {
          if (o.isMesh) {
            o.material = new THREE.MeshStandardMaterial({
              vertexColors: !!o.geometry.getAttribute("color"),
              roughness: 0.85,
              metalness: 0,
              side: THREE.DoubleSide,
            });
            o.geometry.computeVertexNormals();
          }
        });
        loaded = gltf.scene;
        setObj(gltf.scene);
        onLoad?.(gltf.scene);
      },
      undefined,
      (err) => !cancelled && onError?.(err),
    );
    return () => {
      cancelled = true;
      loaded?.traverse((o) => {
        if (o.isMesh) {
          o.geometry.dispose();
          o.material.dispose();
        }
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    obj?.traverse((o) => o.isMesh && (o.material.wireframe = wireframe));
  }, [obj, wireframe]);

  if (!obj) return null;
  return (
    <>
      <hemisphereLight args={[0xffffff, 0x666666, 1.6]} />
      <directionalLight position={[3, 5, 2]} intensity={1.4} />
      <primitive object={obj} />
    </>
  );
}
