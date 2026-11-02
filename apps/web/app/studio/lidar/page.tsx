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

function Cloud({ points }: { points: Point3D[] }) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(points.length * 3);
    const colors = new Float32Array(points.length * 3);
    const color = new THREE.Color();

    points.forEach(([x, y, z], index) => {
      const offset = index * 3;

      // Three.js uses Y as its vertical axis.
      positions[offset] = x;
      positions[offset + 1] = z;
      positions[offset + 2] = -y;

      const normalizedHeight = THREE.MathUtils.clamp(
        (z + 2) / 4,
        0,
        1
      );

      color.setHSL(
        0.65 - normalizedHeight * 0.55,
        1,
        0.55
      );

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

export default function LidarPage() {
  const [data, setData] = useState<LidarData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let busy = false;

    async function fetchPoints() {
      if (!active || busy) return;

      busy = true;

      try {
        const response = await fetch(LIDAR_URL, {
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error(`Bridge HTTP ${response.status}`);
        }

        const result: LidarData = await response.json();

        if (active) {
          setData(result);
          setError(null);
        }
      } catch (reason) {
        if (active) {
          setData(null);
          setError(
            reason instanceof Error
              ? reason.message
              : "LiDAR bridge unavailable"
          );
        }
      } finally {
        busy = false;
      }
    }

    void fetchPoints();

    const timer = window.setInterval(fetchPoints, 200);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const online = data?.connected === true;
  const points = online ? data.points : [];

  return (
    <main className="min-h-screen bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto max-w-7xl space-y-5">
        <header>
          <p className="text-sm font-semibold tracking-widest text-slate-500">
            HFU · G1 STUDIO · ROBOT PERCEPTION
          </p>

          <h1 className="mt-2 text-3xl font-bold">
            Live LiDAR Visualization
          </h1>

          <p className="mt-2 text-slate-600">
            Livox MID-360 · ROS 2 · PointCloud2
          </p>
        </header>

        <div className="grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border bg-white p-4">
            <p className="text-sm text-slate-500">Sensor</p>
            <p className="mt-1 font-semibold">
              {online ? "Connected" : "Offline"}
            </p>
          </div>

          <div className="rounded-xl border bg-white p-4">
            <p className="text-sm text-slate-500">
              Displayed points
            </p>
            <p className="mt-1 text-xl font-semibold">
              {points.length.toLocaleString()}
            </p>
          </div>

          <div className="rounded-xl border bg-white p-4">
            <p className="text-sm text-slate-500">
              Reference frame
            </p>
            <p className="mt-1 font-semibold">
              {data?.frame_id ?? "Unavailable"}
            </p>
          </div>
        </div>

        <div className="h-[65vh] overflow-hidden rounded-xl border bg-slate-950">
          <Canvas
            camera={{
              position: [5, 4, 6],
              fov: 60,
              near: 0.05,
              far: 200,
            }}
          >
            <color attach="background" args={["#080e1b"]} />

            <Grid
              position={[0, -1.5, 0]}
              args={[20, 20]}
              cellColor="#263348"
              sectionColor="#516680"
              fadeDistance={35}
              infiniteGrid
            />

            <axesHelper args={[1]} />

            <Cloud points={points} />

            <OrbitControls
              makeDefault
              target={[0, 0, 0]}
              enableDamping
            />
          </Canvas>
        </div>

        <div className="flex flex-wrap justify-between gap-3 text-sm text-slate-600">
          <span>
            Drag to rotate · Scroll to zoom · Right-drag to pan
          </span>

          <span>
            {error ??
              (online
                ? `Live data · ${data?.age_seconds ?? 0}s old`
                : "Waiting for LiDAR data")}
          </span>
        </div>

        <p className="text-xs text-slate-500">
          Visualization only. No robot movement or navigation
          commands are sent by this page.
        </p>
      </div>
    </main>
  );
}