"use client";

import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { Html } from "@react-three/drei";
import { destinationToThree } from "../../lib/navigation/mapTransform";
import type { Destination } from "./HfuLabMap2D";

type Point3D = [number, number, number];

type CloudData = {
  frame_id: string;
  source: string;
  points: Point3D[];
};

type CameraMode = "perspective" | "top";

const CLOUD_URL =
  "/maps/hfu-session-03/hfu_lab_3d.json";

function PointCloud({
  points,
  center,
  size,
}: {
  points: Point3D[];
  center: [number, number, number];
  size: number;
}) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(
      points.length * 3
    );

    const colors = new Float32Array(
      points.length * 3
    );

    const color = new THREE.Color();

    points.forEach((point, index) => {
      const [x, y, z] = point;

      // FAST-LIO Z is vertical.
      // Three.js Y is vertical.
      positions[index * 3] = x - center[0];
      positions[index * 3 + 1] = z - center[2];
      positions[index * 3 + 2] = -(y - center[1]);

      // Neutral point cloud, not rainbow height coloring.
      color.setRGB(0.84, 0.88, 0.91);

      colors[index * 3] = color.r;
      colors[index * 3 + 1] = color.g;
      colors[index * 3 + 2] = color.b;
    });

    const result = new THREE.BufferGeometry();

    result.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3)
    );

    result.setAttribute(
      "color",
      new THREE.BufferAttribute(colors, 3)
    );

    result.computeBoundingSphere();

    return result;
  }, [points, center]);

  useEffect(() => {
    return () => geometry.dispose();
  }, [geometry]);

  const material = useMemo(
    () =>
      new THREE.PointsMaterial({
        size,
        vertexColors: true,
        sizeAttenuation: true,
      }),
    [size]
  );

  useEffect(() => {
    return () => material.dispose();
  }, [material]);

  return (
    <points
      geometry={geometry}
      material={material}
      frustumCulled={false}
    />
  );
}

export default function HfuLabMap3D({ selectedDestination }: { selectedDestination?: Destination | null }) {
  const [cloud, setCloud] = useState<CloudData | null>(
    null
  );

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const [showCloud, setShowCloud] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  

  const [pointSize, setPointSize] = useState(0.055);

  const [cameraMode, setCameraMode] =
    useState<CameraMode>("perspective");

  useEffect(() => {
    const controller = new AbortController();

    async function loadCloud() {
      try {
        const response = await fetch(CLOUD_URL, {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(
            `Point cloud request failed: ${response.status}`
          );
        }

        const data: unknown = await response.json();

        if (
          typeof data !== "object" ||
          data === null ||
          !("points" in data) ||
          !Array.isArray(data.points)
        ) {
          throw new Error("Invalid point cloud data");
        }

        const parsed = data as CloudData;

        const validPoints = parsed.points.filter(
          (point): point is Point3D =>
            Array.isArray(point) &&
            point.length === 3 &&
            point.every(
              (value) =>
                typeof value === "number" &&
                Number.isFinite(value)
            )
        );

        if (validPoints.length === 0) {
          throw new Error("Point cloud is empty");
        }

        setCloud({
          frame_id: parsed.frame_id,
          source: parsed.source,
          points: validPoints,
        });

        setError("");
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(String(err));
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadCloud();

    return () => controller.abort();
  }, []);

  const bounds = useMemo(() => {
    if (!cloud) {
      return {
        center: [0, 0, 0] as [
          number,
          number,
          number
        ],
        radius: 20,
      };
    }

    const box = new THREE.Box3();

    for (const [x, y, z] of cloud.points) {
      box.expandByPoint(new THREE.Vector3(x, y, z));
    }

    const center = box.getCenter(new THREE.Vector3());
    const dimensions = box.getSize(new THREE.Vector3());

    return {
      center: [
        center.x,
        center.y,
        center.z,
      ] as [number, number, number],
      radius: Math.max(
        dimensions.x,
        dimensions.y,
        dimensions.z,
        10
      ),
    };
  }, [cloud]);

  const cameraPosition: [number, number, number] =
    cameraMode === "top"
      ? [0, bounds.radius * 1.2, 0.01]
      : [
          bounds.radius * 0.55,
          bounds.radius * 0.48,
          bounds.radius * 0.55,
        ];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">
            3D Point Cloud
          </h2>

          <p className="text-[11px] text-slate-500">
            Point cloud · Session 03
          </p>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() =>
              setCameraMode("perspective")
            }
            className={`rounded px-3 py-2 text-xs ${
              cameraMode === "perspective"
                ? "bg-blue-600 text-white"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            Perspective
          </button>

          <button
            type="button"
            onClick={() => setCameraMode("top")}
            className={`rounded px-3 py-2 text-xs ${
              cameraMode === "top"
                ? "bg-blue-600 text-white"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            Top View
          </button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#080e1b] text-sm text-white">
            Loading point cloud...
          </div>
        )}

        {error && (
          <div className="absolute left-4 top-4 z-10 rounded bg-red-950 p-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {cloud && (
          <Canvas
            key={`${cameraMode}-${bounds.radius}`}
            camera={{
              position: cameraPosition,
              fov: 55,
              near: 0.05,
              far: Math.max(500, bounds.radius * 10),
            }}
          >
            <color
              attach="background"
              args={["#080e1b"]}
            />

            <ambientLight intensity={0.8} />
            {showGrid && (
              <gridHelper
                args={[Math.max(30, Math.ceil(bounds.radius / 10) * 10), Math.max(15, Math.ceil(bounds.radius / 2)), "#52677e", "#2b3d52"]}
                position={[0, -1.1, 0]}
              />
            )}


            {showCloud && (
              <PointCloud
                points={cloud.points}
                center={bounds.center}
                size={pointSize}
              />
            )}

            {selectedDestination && (
              <group position={destinationToThree(selectedDestination.position, {
                x: bounds.center[0], y: bounds.center[1], z: bounds.center[2],
              })}>
                <mesh position={[0, 0.35, 0]}>
                  <sphereGeometry args={[0.22, 20, 16]} />
                  <meshBasicMaterial color="#f59e0b" depthTest={false} />
                </mesh>
                <mesh position={[0, 0.12, 0]}>
                  <cylinderGeometry args={[0.025, 0.025, 0.45, 10]} />
                  <meshBasicMaterial color="#f59e0b" depthTest={false} />
                </mesh>
                <Html position={[0, 0.8, 0]} center distanceFactor={12}>
                  <div className="pointer-events-none whitespace-nowrap rounded-md border border-amber-400 bg-slate-950/90 px-3 py-1 text-xs font-semibold text-amber-300 shadow-lg">
                    {selectedDestination.name} · estimated position
                  </div>
                </Html>
              </group>
            )}

            <OrbitControls
              makeDefault
              target={[0, 0, 0]}
              enableDamping
              dampingFactor={0.08}
              minDistance={0.2}
              maxDistance={500}
            />
          </Canvas>
        )}

        {cloud && (
          <div className="pointer-events-none absolute bottom-3 left-3 rounded bg-slate-950/75 px-2 py-1 text-[10px] text-slate-200">
            <p>
              Points: {cloud.points.length.toLocaleString()}
            </p>
            <p>Frame: {cloud.frame_id}</p>

          </div>
        )}
      </div>

      <footer className="flex shrink-0 flex-wrap items-center gap-3 border-t border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-600">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={showCloud}
            onChange={(event) =>
              setShowCloud(event.target.checked)
            }
          />
          Point cloud
        </label>

        <label className="flex items-center gap-2">
          <input type="checkbox" checked={showGrid} onChange={(event) => setShowGrid(event.target.checked)} />
          Metric grid
        </label>
        <label className="flex items-center gap-2">
          Point size
          <input
            type="range"
            min="0.01"
            max="0.2"
            step="0.005"
            value={pointSize}
            onChange={(event) =>
              setPointSize(Number(event.target.value))
            }
          />
        </label>

        <span className="text-amber-700">
          Visualization only
        </span>
      </footer>
    </div>
  );
}
