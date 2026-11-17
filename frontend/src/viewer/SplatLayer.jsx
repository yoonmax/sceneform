import { useEffect, useRef } from "react";
import * as THREE from "three";
import { useThree } from "@react-three/fiber";
import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";

/**
 * Real 3D Gaussian splat rendering via Spark (World Labs, MIT).
 * The splat file stays in the trainer's frame (so its spherical harmonics
 * remain valid); the manifest's transform places it in the scene frame.
 */
export default function SplatLayer({ url, transform, onProgress, onLoad, onError }) {
  const { gl, scene } = useThree();
  const group = useRef();

  useEffect(() => {
    let spark = scene.userData.spark;
    if (!spark) {
      spark = new SparkRenderer({ renderer: gl });
      scene.add(spark);
      scene.userData.spark = spark;
    }
    return () => {
      if (scene.userData.spark === spark && !scene.userData.keepSpark) {
        scene.remove(spark);
        spark.dispose?.();
        delete scene.userData.spark;
      }
    };
  }, [gl, scene]);

  useEffect(() => {
    let disposed = false;
    const mesh = new SplatMesh({
      url,
      onProgress: (e) => e.lengthComputable && onProgress?.(e.loaded / e.total),
    });
    if (transform) {
      mesh.matrixAutoUpdate = false;
      mesh.matrix.fromArray(transform);
      mesh.matrixWorldNeedsUpdate = true;
    }
    group.current?.add(mesh);
    mesh.initialized
      .then(() => !disposed && onLoad?.(mesh))
      .catch((err) => !disposed && onError?.(err));
    return () => {
      disposed = true;
      group.current?.remove(mesh);
      mesh.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  return <group ref={group} />;
}

export function splatSupported() {
  try {
    const c = document.createElement("canvas");
    return !!c.getContext("webgl2");
  } catch {
    return false;
  }
}

export const _THREE = THREE;
