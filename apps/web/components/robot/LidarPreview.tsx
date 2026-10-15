"use client";

import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import * as THREE from "three";

type Point3D = [number, number, number];

type LidarData = {
  connected: boolean;
  frame_id: string | null;
  received_at: number | null;
  age_seconds: number | null;
  total_points: number;
  points: Point3D[];
};

const LIDAR_URL = "http://127.0.0.1:8765/points";

function PointCloud({ points }: { points: Point3D[] }) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(points.length * 3);
    const colors = new Float32Array(points.length * 3);
    const color = new THREE.Color();

    points.forEach(([x, y, z], index) => {
      const offset = index * 3;

      positions[offset] = x;
      positions[offset + 1] = z;
      positions[offset + 2] = -y;

      const height = THREE.MathUtils.clamp(
        (z + 2) / 4,
        0,
        1
      );

      color.setHSL(0.65 - height * 0.55, 1, 0.55);

      colors[offset] = color.r;
      colors[offset + 1] = color.g;
      colors[offset + 2] = color.b;
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

    return result;
  }, [points]);

  useEffect(() => {
    return () => geometry.dispose();
  }, [geometry]);

  return (
    <points geometry={geometry} frustumCulled={false}>
      <pointsMaterial
        size={0.045}
        sizeAttenuation
        vertexColors
      />
    </points>
  );
}

export default function LidarPreview() {
  const [data, setData] = useState<LidarData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let busy = false;
    let controller: AbortController | null = null;

    async function fetchPoints() {
      if (!active || busy) return;

      busy = true;
      const currentController = new AbortController();
      controller = currentController;

      try {
        const response = await fetch(LIDAR_URL, {
          cache: "no-store",
          signal: currentController.signal,
        });

        if (!response.ok) {
          throw new Error(`LiDAR HTTP ${response.status}`);
        }

        const result: LidarData = await response.json();

        if (!active) return;

        setData(result);
        setError(null);
      } catch (reason) {
        if (!active) return;

        setData(null);
        setError(
          reason instanceof Error
            ? reason.message
            : "LiDAR bridge unavailable"
        );
      } finally {
        busy = false;

        if (controller === currentController) {
          controller = null;
        }
      }
    }

    void fetchPoints();

    const timer = window.setInterval(fetchPoints, 500);

    return () => {
      active = false;
      window.clearInterval(timer);
      controller?.abort();
    };
  }, []);

  const online =
    data?.connected === true &&
    Array.isArray(data.points) &&
    data.age_seconds !== null &&
    data.age_seconds <= 3;

  const points = online ? data?.points ?? [] : [];

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-[#d8dcda] bg-white">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div>
          <h3 className="font-semibold">G1 LiDAR</h3>
          <p className="text-xs text-[#738080]">
            Livox MID-360 · ROS 2
          </p>
        </div>

        <span
          className={`rounded-full px-2 py-1 text-xs font-semibold ${
            online
              ? "bg-emerald-50 text-emerald-700"
              : "bg-amber-50 text-amber-700"
          }`}
        >
          {online ? "Live" : "Offline"}
        </span>
      </div>

      <div className="relative h-[230px] bg-[#080e1b]">
        <Canvas
          camera={{
            position: [5, 4, 6],
            fov: 60,
            near: 0.05,
            far: 200,
          }}
        >
          <color
            attach="background"
            args={["#080e1b"]}
          />

          <Grid
            position={[0, -1.5, 0]}
            args={[20, 20]}
            cellColor="#263348"
            sectionColor="#516680"
            fadeDistance={35}
            infiniteGrid
          />

          <axesHelper args={[1]} />
          <PointCloud points={points} />

          <OrbitControls
            makeDefault
            target={[0, 0, 0]}
            enableDamping
          />
        </Canvas>

        {!online && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-[#080e1b]/70">
            <span className="rounded-lg bg-[#152638] px-4 py-2 text-xs font-medium text-white">
              Waiting for live LiDAR data
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 px-4 py-3 text-xs text-[#738080]">
        <div>
          <p>
            Points: {points.length.toLocaleString()}
          </p>
          <p className="mt-1">
            Frame: {online
              ? data?.frame_id ?? "Unknown"
              : "Unavailable"}
          </p>
          {error && (
            <p className="mt-1 text-amber-700">
              {error}
            </p>
          )}
        </div>

        <a
          href="/studio/lidar"
          className="shrink-0 font-semibold text-[#00866a] hover:underline"
        >
          Full View →
        </a>
      </div>
    </div>
  );
}