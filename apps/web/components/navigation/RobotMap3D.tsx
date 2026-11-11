"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { Canvas, ThreeEvent, useThree } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import * as THREE from "three";

type Point3D = [number, number, number];

type MapData = {
  connected: boolean;
  source: string;
  frame_id: string | null;
  total_points: number;
  displayed_points: number;
  age_seconds: number | null;
  points: Point3D[];
  message?: string;
};

type RobotPose = {
  frame_id: string;
  child_frame_id: string;
  position: { x: number; y: number; z: number };
  orientation: { x: number; y: number; z: number; w: number };
  yaw: number;
};

type PoseData = {
  connected: boolean;
  source: string;
  age_seconds: number | null;
  pose: RobotPose | null;
};

type Destination = {
  name: string;
  frame_id: string;
  x: number;
  y: number;
  z: number;
};

type FloorCandidate = {
  id: number;
  normal: [number, number, number];
  plane_offset: number;
  tilt_degrees: number;
  inlier_count: number;
  inlier_ratio: number;
  z_at_robot_xy: number | null;
  robot_z_minus_plane_z: number | null;
  near_robot_inlier_count: number;
  support_grid_cells: number;
  classification: string;
  approved_for_navigation: boolean;
};

type FloorDiagnostics = {
  success: boolean;
  method?: string;
  diagnostic_only?: boolean;
  point_count?: number;
  candidate_count?: number;
  frame_id?: string;
  map_age_seconds?: number | null;
  map_version?: number;
  parameters?: {
    distance_threshold_m?: number;
  };
  candidates: FloorCandidate[];
  reason?: string;
  warnings?: string[];
  approved_for_navigation?: boolean;
};

type OccupancyGridData = {
  success: boolean;
  mode?: string;
  frame_id?: string;
  map_age_seconds?: number | null;
  map_fresh?: boolean;
  resolution_m?: number;
  origin?: [number, number];
  width?: number;
  height?: number;
  cell_encoding?: string;
  observed_geometry_cells?: [number, number, number][];
  observed_geometry_count?: number;
  unknown_count?: number;
  observed_free_count?: number;
  occupied_count?: number;
  floor_verified?: boolean;
  approved_for_navigation?: boolean;
  warnings?: string[];
  reason?: string;
};

const BASE_URL = "http://127.0.0.1:8769";
const STORAGE_KEY = "g1-studio-coffee-destination-v1";

const PLANE_COLORS = [
  "#ef4444",
  "#f59e0b",
  "#22d3ee",
  "#c084fc",
];

function format(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(3)
    : "—";
}

function StatCard({
  title,
  value,
  subtitle,
}: {
  title: string;
  value: string;
  subtitle: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </p>
      <p className="text-lg font-bold">{value}</p>
      <p className="text-[11px] text-slate-500">{subtitle}</p>
    </div>
  );
}

function PointLayer({
  points,
  pointSize,
  colorMode,
  color,
}: {
  points: Point3D[];
  pointSize: number;
  colorMode: "height" | "solid";
  color?: string;
}) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(points.length * 3);
    const colors = new Float32Array(points.length * 3);
    const pointColor = new THREE.Color();
    const solidColor = new THREE.Color(color ?? "#ffffff");

    points.forEach(([x, y, z], index) => {
      const offset = index * 3;

      positions[offset] = x;
      positions[offset + 1] = z;
      positions[offset + 2] = -y;

      if (colorMode === "height") {
        const height = THREE.MathUtils.clamp((z + 2) / 4, 0, 1);
        pointColor.setHSL(0.65 - height * 0.55, 0.9, 0.6);
      } else {
        pointColor.copy(solidColor);
      }

      colors[offset] = pointColor.r;
      colors[offset + 1] = pointColor.g;
      colors[offset + 2] = pointColor.b;
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
  }, [points, colorMode, color]);

  useEffect(() => {
    return () => geometry.dispose();
  }, [geometry]);

  return (
    <points geometry={geometry} frustumCulled={false}>
      <pointsMaterial
        size={pointSize}
        sizeAttenuation
        vertexColors
        depthWrite={false}
      />
    </points>
  );
}

function RobotMarker({ pose }: { pose: RobotPose }) {
  return (
    <group
      position={[
        pose.position.x,
        pose.position.z,
        -pose.position.y,
      ]}
      rotation={[0, -pose.yaw, 0]}
    >
      <mesh>
        <sphereGeometry args={[0.14, 16, 16]} />
        <meshStandardMaterial
          color="#22c55e"
          emissive="#14532d"
        />
      </mesh>
      <mesh position={[0.3, 0, 0]}>
        <coneGeometry args={[0.1, 0.25, 12]} />
        <meshStandardMaterial color="#22c55e" />
      </mesh>
    </group>
  );
}

function DestinationMarker({
  destination,
}: {
  destination: Destination;
}) {
  return (
    <group
      position={[
        destination.x,
        destination.z,
        -destination.y,
      ]}
    >
      <mesh>
        <sphereGeometry args={[0.18, 20, 20]} />
        <meshStandardMaterial
          color="#2563eb"
          emissive="#1e40af"
          emissiveIntensity={0.5}
        />
      </mesh>
      <mesh position={[0, 0.45, 0]}>
        <coneGeometry args={[0.17, 0.35, 16]} />
        <meshStandardMaterial color="#38bdf8" />
      </mesh>
    </group>
  );
}

function OccupancyOverlay({
  grid,
  elevation,
  opacity,
}: {
  grid: OccupancyGridData;
  elevation: number;
  opacity: number;
}) {
  const cells = grid.observed_geometry_cells ?? [];
  const resolution = grid.resolution_m ?? 0.2;
  const origin = grid.origin ?? [0, 0];
  const width = grid.width ?? 0;
  const height = grid.height ?? 0;

  const geometry = useMemo(() => new THREE.PlaneGeometry(1, 1), []);
  const material = useMemo(
    () => new THREE.MeshBasicMaterial({
      color: "#94a3b8",
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
    }),
    [opacity]
  );
  const meshRef = useRef<THREE.InstancedMesh>(null);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const transform = new THREE.Object3D();
    cells.forEach(([row, column], index) => {
      transform.position.set(
        origin[0] + (column + 0.5) * resolution,
        elevation,
        -(origin[1] + (row + 0.5) * resolution)
      );
      transform.rotation.set(-Math.PI / 2, 0, 0);
      transform.scale.set(resolution * 0.94, resolution * 0.94, 1);
      transform.updateMatrix();
      mesh.setMatrixAt(index, transform.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [cells, origin, resolution, elevation]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);

  if (!cells.length || !width || !height) return null;

  return (
    <instancedMesh
      ref={meshRef}
      args={[geometry, material, cells.length]}
      frustumCulled={false}
      raycast={() => null}
    />
  );
}

function RoutePreview({
  pose,
  destination,
}: {
  pose: RobotPose;
  destination: Destination;
}) {
  const line = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(
        pose.position.x,
        pose.position.z + 0.08,
        -pose.position.y
      ),
      new THREE.Vector3(
        destination.x,
        destination.z + 0.08,
        -destination.y
      ),
    ]);
    const material = new THREE.LineBasicMaterial({
      color: "#facc15",
      depthTest: false,
    });
    return new THREE.Line(geometry, material);
  }, [
    pose.position.x,
    pose.position.y,
    pose.position.z,
    destination.x,
    destination.y,
    destination.z,
  ]);

  useEffect(() => () => {
    line.geometry.dispose();
    (line.material as THREE.Material).dispose();
  }, [line]);

  return <primitive object={line} />;
}

function DestinationSelectionPlane({
  enabled,
  height,
  onSelect,
}: {
  enabled: boolean;
  height: number;
  onSelect: (x: number, y: number) => void;
}) {
  const handleClick = useCallback(
    (event: ThreeEvent<MouseEvent>) => {
      if (!enabled) return;
      event.stopPropagation();
      onSelect(event.point.x, -event.point.z);
    },
    [enabled, onSelect]
  );

  if (!enabled) return null;

  return (
    <mesh
      position={[0, height, 0]}
      rotation={[-Math.PI / 2, 0, 0]}
      onClick={handleClick}
    >
      <planeGeometry args={[200, 200]} />
      <meshBasicMaterial
        transparent
        opacity={0}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

function CameraController({
  topViewRequest,
  pose,
}: {
  topViewRequest: number;
  pose: RobotPose | null;
}) {
  const { camera, controls } = useThree();
  const previousRequest = useRef(topViewRequest);

  useEffect(() => {
    if (previousRequest.current === topViewRequest) return;
    previousRequest.current = topViewRequest;

    const x = pose?.position.x ?? 0;
    const y = pose?.position.z ?? 0;
    const z = -(pose?.position.y ?? 0);

    camera.position.set(x, y + 14, z + 0.001);
    camera.up.set(0, 0, -1);
    camera.lookAt(x, y, z);
    camera.updateProjectionMatrix();

    const orbit = controls as
      | (THREE.EventDispatcher & {
          target?: THREE.Vector3;
          update?: () => void;
        })
      | null;

    if (orbit?.target) {
      orbit.target.set(x, y, z);
      orbit.update?.();
    }
  }, [topViewRequest, pose, camera, controls]);

  return null;
}


function VerticalCrossSection({
  points,
  pose,
  candidates,
  selectedPlaneId,
}: {
  points: Point3D[];
  pose: RobotPose | null;
  candidates: FloorCandidate[];
  selectedPlaneId: number | null;
}) {
  const sample = useMemo(() => {
    if (!pose) return [] as Point3D[];
    const px = pose.position.x;
    const py = pose.position.y;
    // A narrow X/Z slice through the robot, not a projection of the whole room.
    const nearby = points.filter(([x, y]) =>
      Math.abs(x - px) <= 3 && Math.abs(y - py) <= 0.4
    );
    const stride = Math.max(1, Math.ceil(nearby.length / 900));
    return nearby.filter((_, i) => i % stride === 0);
  }, [points, pose]);

  const plot = useMemo(() => {
    if (!pose) return null;
    const x0 = pose.position.x;
    const y0 = pose.position.y;
    const z0 = pose.position.z;
    const elevations = sample.map((point) => point[2] - z0);
    for (const plane of candidates) {
      if (plane.z_at_robot_xy !== null) elevations.push(plane.z_at_robot_xy - z0);
    }
    elevations.push(0);
    const bottom = Math.min(-1, ...elevations) - 0.25;
    const top = Math.max(1, ...elevations) + 0.25;
    const left = 45;
    const right = 740;
    const topPx = 20;
    const bottomPx = 215;
    const sx = (x: number) => left + ((x - x0 + 3) / 6) * (right - left);
    const sy = (relativeZ: number) => bottomPx - ((relativeZ - bottom) / (top - bottom)) * (bottomPx - topPx);
    const planeSegments = candidates.flatMap((candidate) => {
      const [nx, ny, nz] = candidate.normal;
      if (Math.abs(nz) < 0.001) return [];
      const zAt = (x: number) => -(nx * x + ny * y0 + candidate.plane_offset) / nz;
      return [{
        id: candidate.id,
        x1: sx(x0 - 3),
        x2: sx(x0 + 3),
        y1: sy(zAt(x0 - 3) - z0),
        y2: sy(zAt(x0 + 3) - z0),
      }];
    });
    return { sx, sy, x0, z0, bottom, top, planeSegments };
  }, [sample, pose, candidates]);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-bold text-slate-900">Vertical Cross-Section</h3>
          <p className="mt-1 text-xs text-slate-500">
            X/Z slice within ±0.4 m of robot Y · heights relative to odometry origin
          </p>
        </div>
        <span className="rounded-full bg-amber-100 px-2 py-1 text-[11px] font-semibold text-amber-800">
          Unverified geometry
        </span>
      </div>
      {plot && pose ? (
        <>
          <svg viewBox="0 0 760 245" className="mt-3 w-full rounded-lg bg-[#101827]" role="img" aria-label="Robot-relative vertical cross-section of MOLA points and candidate planes">
            {[0, 1, 2, 3, 4].map((index) => {
              const z = plot.bottom + (index / 4) * (plot.top - plot.bottom);
              return (
                <g key={index}>
                  <line x1="45" x2="740" y1={plot.sy(z)} y2={plot.sy(z)} stroke="#334155" strokeWidth="1" />
                  <text x="39" y={plot.sy(z) + 4} fill="#94a3b8" fontSize="10" textAnchor="end">{z.toFixed(1)}</text>
                </g>
              );
            })}
            {[-3, -2, -1, 0, 1, 2, 3].map((dx) => (
              <g key={dx}>
                <line x1={plot.sx(plot.x0 + dx)} x2={plot.sx(plot.x0 + dx)} y1="20" y2="215" stroke="#263448" />
                <text x={plot.sx(plot.x0 + dx)} y="232" fill="#94a3b8" fontSize="10" textAnchor="middle">{dx > 0 ? `+${dx}` : dx} m</text>
              </g>
            ))}
            {sample.map(([x, , z], i) => (
              <circle key={i} cx={plot.sx(x)} cy={plot.sy(z - plot.z0)} r="1.6" fill="#cbd5e1" opacity="0.65" />
            ))}
            {plot.planeSegments.map((segment) => (
              <line key={segment.id} x1={segment.x1} y1={segment.y1} x2={segment.x2} y2={segment.y2}
                stroke={PLANE_COLORS[(segment.id - 1) % PLANE_COLORS.length]}
                strokeWidth={segment.id === selectedPlaneId ? 3 : 1.5}
                strokeDasharray={segment.id === selectedPlaneId ? undefined : "6 5"}
                opacity={segment.id === selectedPlaneId ? 1 : 0.65} />
            ))}
            <circle cx={plot.sx(plot.x0)} cy={plot.sy(0)} r="6" fill="#22c55e" stroke="#ffffff" strokeWidth="1.5" />
            <text x="54" y="15" fill="#cbd5e1" fontSize="10">Relative height (m)</text>
          </svg>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-600">
            <span><span className="font-semibold text-emerald-700">●</span> Robot odometry origin</span>
            <span>● MOLA slice points: {sample.length.toLocaleString()}</span>
            {candidates.map((candidate) => (
              <span key={candidate.id} className={candidate.id === selectedPlaneId ? "font-bold" : ""}>
                <span style={{ color: PLANE_COLORS[(candidate.id - 1) % PLANE_COLORS.length] }}>━</span>{" "}
                Plane {candidate.id}: {format(candidate.robot_z_minus_plane_z)} m below robot
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-amber-700">
            Odometry origin is not confirmed to be at foot level. Lines show mathematical plane extensions,
            not continuous measured floor or safe walking areas.
          </p>
        </>
      ) : (
        <p className="mt-4 text-sm text-slate-500">Waiting for robot pose and map points.</p>
      )}
    </section>
  );
}

function MapWorkspaceSummary({ occupancy, mapAge }: {
  occupancy: OccupancyGridData | null;
  mapAge: number | null | undefined;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="font-bold text-slate-900">Mapping Diagnostics</h3>
      <p className="mt-1 text-xs text-slate-500">Read-only MOLA map quality and occupancy evidence</p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        {[
          ["Observed geometry", (occupancy?.observed_geometry_count ?? 0).toLocaleString()],
          ["Unknown cells", (occupancy?.unknown_count ?? 0).toLocaleString()],
          ["Verified free", String(occupancy?.observed_free_count ?? 0)],
          ["Verified obstacles", String(occupancy?.occupied_count ?? 0)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg bg-slate-50 p-3">
            <p className="text-[11px] text-slate-500">{label}</p>
            <p className="mt-1 text-lg font-bold tabular-nums">{value}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-600">
        Snapshot: {format(mapAge)} s · Resolution: {format(occupancy?.resolution_m)} m
      </p>
      <p className="mt-2 text-xs font-semibold text-amber-700">Floor unverified · Physical navigation disabled</p>
    </section>
  );
}

export default function RobotMapPage() {
  const [map, setMap] = useState<MapData | null>(null);
  const [localization, setLocalization] = useState<PoseData | null>(null);
  const [floor, setFloor] = useState<FloorDiagnostics | null>(null);
  const [occupancy, setOccupancy] = useState<OccupancyGridData | null>(null);

  const [mapError, setMapError] = useState<string | null>(null);
  const [poseError, setPoseError] = useState<string | null>(null);
  const [floorError, setFloorError] = useState<string | null>(null);
  const [occupancyError, setOccupancyError] = useState<string | null>(null);

  const [showPoints, setShowPoints] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  const [showRoute, setShowRoute] = useState(true);
  const [showFloor, setShowFloor] = useState(false);
  const [showOccupancy, setShowOccupancy] = useState(false);
  const [occupancyOpacity, setOccupancyOpacity] = useState(0.65);

  const [pointSize, setPointSize] = useState(0.055);
  const [selectedPlaneId, setSelectedPlaneId] = useState<number | null>(null);
  const [topViewRequest, setTopViewRequest] = useState(0);

  const [selectionMode, setSelectionMode] = useState(false);
  const [destination, setDestination] = useState<Destination | null>(null);
  const [destinationSaved, setDestinationSaved] = useState(false);
  const [destinationError, setDestinationError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (!stored) return;

      const parsed: unknown = JSON.parse(stored);

      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "frame_id" in parsed &&
        "x" in parsed &&
        "y" in parsed &&
        "z" in parsed &&
        typeof parsed.frame_id === "string" &&
        typeof parsed.x === "number" &&
        typeof parsed.y === "number" &&
        typeof parsed.z === "number" &&
        [parsed.x, parsed.y, parsed.z].every(Number.isFinite)
      ) {
        setDestination({
          name: "Coffee Machine",
          frame_id: parsed.frame_id,
          x: parsed.x,
          y: parsed.y,
          z: parsed.z,
        });
        setDestinationSaved(true);
      }
    } catch {
      setDestinationError("Saved destination could not be loaded.");
    }
  }, []);

  useEffect(() => {
    let active = true;
    let mapBusy = false;
    let poseBusy = false;
    let floorBusy = false;
    let occupancyBusy = false;

    async function fetchMap() {
      if (!active || mapBusy) return;
      mapBusy = true;

      try {
        const response = await fetch(`${BASE_URL}/map`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const result: MapData = await response.json();

        if (active) {
          setMap(result);
          setMapError(null);
        }
      } catch (error) {
        if (active) {
          setMap(null);
          setMapError(
            error instanceof Error ? error.message : "Map unavailable"
          );
        }
      } finally {
        mapBusy = false;
      }
    }

    async function fetchPose() {
      if (!active || poseBusy) return;
      poseBusy = true;

      try {
        const response = await fetch(`${BASE_URL}/pose`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const result: PoseData = await response.json();

        if (active) {
          setLocalization(result);
          setPoseError(null);
        }
      } catch (error) {
        if (active) {
          setLocalization(null);
          setPoseError(
            error instanceof Error ? error.message : "Pose unavailable"
          );
        }
      } finally {
        poseBusy = false;
      }
    }

    async function fetchFloor() {
      if (!active || floorBusy) return;
      floorBusy = true;

      try {
        const response = await fetch(
          `${BASE_URL}/floor-diagnostics`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const result: FloorDiagnostics = await response.json();

        if (active) {
          setFloor(result);
          setFloorError(null);
        }
      } catch (error) {
        if (active) {
          setFloor(null);
          setFloorError(
            error instanceof Error
              ? error.message
              : "Floor diagnostics unavailable"
          );
        }
      } finally {
        floorBusy = false;
      }
    }

    async function fetchOccupancy() {
      if (!active || occupancyBusy) return;
      occupancyBusy = true;
      try {
        const response = await fetch(`${BASE_URL}/occupancy-grid`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result: OccupancyGridData = await response.json();
        if (active) {
          setOccupancy(result);
          setOccupancyError(result.success ? null : result.reason ?? "Grid unavailable");
        }
      } catch (error) {
        if (active) {
          setOccupancy(null);
          setOccupancyError(error instanceof Error ? error.message : "Grid unavailable");
        }
      } finally {
        occupancyBusy = false;
      }
    }

    void fetchMap();
    void fetchPose();
    void fetchFloor();
    void fetchOccupancy();

    const mapTimer = window.setInterval(fetchMap, 2000);
    const poseTimer = window.setInterval(fetchPose, 500);
    const floorTimer = window.setInterval(fetchFloor, 10000);
    const occupancyTimer = window.setInterval(fetchOccupancy, 5000);

    return () => {
      active = false;
      window.clearInterval(mapTimer);
      window.clearInterval(poseTimer);
      window.clearInterval(floorTimer);
      window.clearInterval(occupancyTimer);
    };
  }, []);

  const mapAvailable = map?.connected === true;
  const poseOnline = localization?.connected === true;

  const points = useMemo(
    () => (mapAvailable ? map?.points ?? [] : []),
    [mapAvailable, map?.points]
  );

  const pose = poseOnline ? localization?.pose ?? null : null;

  const framesAligned =
    mapAvailable &&
    poseOnline &&
    !!map?.frame_id &&
    map.frame_id === pose?.frame_id;

  const destinationFrameAligned =
    !!destination &&
    !!map?.frame_id &&
    destination.frame_id === map.frame_id;

  const routeAvailable =
    !!pose &&
    !!destination &&
    framesAligned &&
    destinationFrameAligned;

  const distance =
    routeAvailable && pose && destination
      ? Math.hypot(
          destination.x - pose.position.x,
          destination.y - pose.position.y
        )
      : null;

  const floorFrameAligned =
    !!floor?.frame_id &&
    !!map?.frame_id &&
    floor.frame_id === map.frame_id;

  const occupancyAligned =
    occupancy?.success === true &&
    !!occupancy.frame_id &&
    !!map?.frame_id &&
    occupancy.frame_id === map.frame_id;

  const selectedPlane =
    floor?.candidates?.find((candidate) => candidate.id === selectedPlaneId)
    ?? null;

  const planeColor = selectedPlane
    ? PLANE_COLORS[(selectedPlane.id - 1) % PLANE_COLORS.length]
    : "#22d3ee";

  const highlightedPoints = useMemo(() => {
    if (!showFloor || !selectedPlane || !floorFrameAligned) return [];

    const [nx, ny, nz] = selectedPlane.normal;
    const offset = selectedPlane.plane_offset;
    const threshold = floor?.parameters?.distance_threshold_m ?? 0.08;

    return points.filter(([x, y, z]) => {
      return Math.abs(nx * x + ny * y + nz * z + offset) <= threshold;
    });
  }, [points, selectedPlane, showFloor, floorFrameAligned, floor]);

  const handleSelectDestination = useCallback(
    (x: number, y: number) => {
      if (!mapAvailable || !map?.frame_id) return;

      setDestination({
        name: "Coffee Machine",
        frame_id: map.frame_id,
        x,
        y,
        z: pose?.position.z ?? 0,
      });

      setDestinationSaved(false);
      setDestinationError(null);
      setSelectionMode(false);
    },
    [mapAvailable, map?.frame_id, pose?.position.z]
  );

  function saveDestination() {
    if (!destination) return;

    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(destination)
      );
      setDestinationSaved(true);
      setDestinationError(null);
    } catch {
      setDestinationSaved(false);
      setDestinationError("Unable to save destination.");
    }
  }

  function clearDestination() {
    setDestination(null);
    setDestinationSaved(false);
    setSelectionMode(false);
    setDestinationError(null);

    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      setDestinationError("Unable to clear browser storage.");
    }
  }

  return (
    <main className="h-[calc(100dvh-104px)] min-h-[540px] overflow-hidden bg-[#f5f7f8] p-2 text-slate-900 sm:p-3">
      <div className="mx-auto flex h-full max-w-[1900px] min-h-0 flex-col gap-2">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-emerald-700">
              HFU · IPSE · G1 STUDIO
            </p>
            <h1 className="text-xl font-bold">Robot Map</h1>
            <p className="text-xs text-slate-600">
              Building H · 1. Stock · MOLA 3D Mapping
            </p>
          </div>
          <div className="rounded-lg bg-amber-100 px-4 py-2 text-sm font-semibold text-amber-800">
            Physical navigation disabled
          </div>
        </header>

        <div className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4">
          <StatCard
            title="Mapping"
            value={mapAvailable ? "Available" : "Waiting"}
            subtitle="MOLA local map"
          />
          <StatCard
            title="Localization"
            value={poseOnline ? "Live" : "Unavailable"}
            subtitle="MOLA odometry"
          />
          <StatCard
            title="Map points"
            value={points.length.toLocaleString()}
            subtitle="MOLA point cloud"
          />
          <StatCard
            title="Floor candidates"
            value={String(floor?.candidate_count ?? "—")}
            subtitle="RANSAC · unverified"
          />
        </div>

        {/* Three-column mapping workspace: independently sized, no stretched grid rows. */}
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] gap-2 overflow-y-auto xl:grid-cols-[minmax(220px,250px)_minmax(0,1fr)_minmax(245px,280px)] xl:overflow-hidden">
          <aside className="min-h-0 min-w-0 space-y-2 overflow-y-auto overscroll-contain pr-1 [scrollbar-width:thin]">
            <section className="rounded-xl border bg-white p-3">
              <h2 className="font-bold">Map Layers</h2>

              <label className="mt-4 flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={showPoints}
                  onChange={(event) => setShowPoints(event.target.checked)}
                />
                MOLA point cloud
              </label>

              <label className="mt-3 flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={showGrid}
                  onChange={(event) => setShowGrid(event.target.checked)}
                />
                Reference grid
              </label>

              <label className="mt-3 flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={showOccupancy}
                  onChange={(event) => setShowOccupancy(event.target.checked)}
                />
                2D observed geometry overlay
              </label>

              <label className="mt-5 block text-xs font-semibold">
                Point size: {pointSize.toFixed(3)}
              </label>

              <input
                type="range"
                min="0.01"
                max="0.15"
                step="0.005"
                value={pointSize}
                onChange={(event) =>
                  setPointSize(Number(event.target.value))
                }
                className="mt-2 w-full accent-emerald-700"
              />
            </section>
            <section className="rounded-xl border bg-white p-3">
              <h2 className="font-bold">Floor Analysis</h2>
              <p className="mt-2 text-xs text-slate-500">
                Inspect horizontal surfaces detected by RANSAC.
                Highlighting does not establish a walkable floor.
              </p>

              <label className="mt-4 flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={showFloor}
                  onChange={(event) => setShowFloor(event.target.checked)}
                />
                Show candidate plane points
              </label>

              {floorError && (
                <p className="mt-3 text-xs text-red-600">{floorError}</p>
              )}

              {!floorError && !floor && (
                <p className="mt-3 text-xs text-slate-500">
                  Waiting for floor diagnostics...
                </p>
              )}

              {floor && !floor.success && (
                <p className="mt-3 text-xs text-amber-700">
                  {floor.reason ?? "No candidate planes detected."}
                </p>
              )}

              {floor?.success && (
                <div className="mt-4 space-y-2">
                  {floor.candidates.map((candidate) => {
                    const color =
                      PLANE_COLORS[
                        (candidate.id - 1) % PLANE_COLORS.length
                      ];

                    const selected = selectedPlaneId === candidate.id;

                    return (
                      <button
                        key={candidate.id}
                        type="button"
                        onClick={() => {
                          setSelectedPlaneId(candidate.id);
                          setShowFloor(true);
                        }}
                        className={`w-full rounded-lg border p-3 text-left text-xs ${
                          selected
                            ? "border-blue-500 bg-blue-50"
                            : "border-slate-200 hover:bg-slate-50"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="flex items-center gap-2 font-bold">
                            <span
                              className="h-3 w-3 rounded-full"
                              style={{ backgroundColor: color }}
                            />
                            Plane {candidate.id}
                          </span>
                          <span>{candidate.tilt_degrees.toFixed(2)}°</span>
                        </div>

                        <div className="mt-2 grid grid-cols-2 gap-2 text-slate-600">
                          <span>
                            Support: {candidate.inlier_count.toLocaleString()}
                          </span>
                          <span>
                            Nearby: {candidate.near_robot_inlier_count}
                          </span>
                          <span>
                            Height: {format(candidate.z_at_robot_xy)} m
                          </span>
                          <span>
                            Coverage: {candidate.support_grid_cells} bins
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}

              {showFloor && selectedPlane && (
                <div className="mt-4 rounded-lg bg-slate-100 p-3 text-xs">
                  <p className="font-semibold">Selected plane</p>
                  <p className="mt-2">
                    Robot Z − plane Z:{" "}
                    {format(selectedPlane.robot_z_minus_plane_z)} m
                  </p>
                  <p className="mt-1">
                    Browser-matched points: {highlightedPoints.length}
                  </p>
                  <p className="mt-1 text-slate-500">
                    Matching uses the reported plane equation and
                    distance threshold. Counts may differ from RANSAC
                    because its candidates were extracted sequentially.
                  </p>
                </div>
              )}

              <p className="mt-4 text-xs font-semibold text-amber-700">
                No floor candidate approved for navigation.
              </p>
            </section>
            <section className="rounded-xl border bg-white p-3">
              <h2 className="font-bold">Occupancy Grid Diagnostics</h2>
              <p className="mt-2 text-xs text-slate-500">
                Read-only 2D projection of observed MOLA geometry.
                Grey cells are unclassified, not safe walking space.
              </p>

              <label className="mt-4 flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={showOccupancy}
                  onChange={(event) => setShowOccupancy(event.target.checked)}
                />
                Show observed geometry overlay
              </label>

              <label className="mt-4 block text-xs font-semibold">
                Overlay opacity: {Math.round(occupancyOpacity * 100)}%
              </label>
              <input
                type="range"
                min="0.15"
                max="1"
                step="0.05"
                value={occupancyOpacity}
                onChange={(event) => setOccupancyOpacity(Number(event.target.value))}
                className="mt-2 w-full accent-emerald-700"
              />

              {occupancyError && (
                <p className="mt-3 text-xs text-red-600">{occupancyError}</p>
              )}
              {!occupancy && !occupancyError && (
                <p className="mt-3 text-xs text-slate-500">Waiting for grid...</p>
              )}
              {occupancy?.success && (
                <div className="mt-4 space-y-2 text-xs text-slate-600">
                  <p><strong>Grid:</strong> {occupancy.width} × {occupancy.height}</p>
                  <p><strong>Resolution:</strong> {format(occupancy.resolution_m)} m</p>
                  <p><strong>Observed cells:</strong> {(occupancy.observed_geometry_count ?? 0).toLocaleString()}</p>
                  <p><strong>Unknown cells:</strong> {(occupancy.unknown_count ?? 0).toLocaleString()}</p>
                  <p><strong>Verified free cells:</strong> {occupancy.observed_free_count ?? 0}</p>
                  <p><strong>Verified obstacles:</strong> {occupancy.occupied_count ?? 0}</p>
                  <p><strong>Map age:</strong> {format(occupancy.map_age_seconds)} s</p>
                  <p className={occupancy.map_fresh ? "text-emerald-700" : "text-amber-700"}>
                    {occupancy.map_fresh ? "Snapshot fresh" : "Snapshot stale"}
                  </p>
                  {!occupancyAligned && (
                    <p className="text-red-600">Map frames do not match. Overlay hidden.</p>
                  )}
                </div>
              )}
              <p className="mt-4 text-xs font-semibold text-amber-700">
                Floor unverified · navigation not approved · robot motion disabled
              </p>
            </section>
            <MapWorkspaceSummary occupancy={occupancyAligned ? occupancy : null} mapAge={map?.age_seconds} />
          </aside>

          <div className="flex min-h-0 min-w-0 flex-col gap-2">
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b p-4">
              <div>
                <h2 className="text-lg font-bold">MOLA 3D Map</h2>
                <p className="mt-1 text-xs text-slate-500">
                  /lidar_odometry/localmap_points
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setTopViewRequest((value) => value + 1)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold hover:bg-slate-100"
                >
                  Top View
                </button>
                <span
                  className={`rounded-full px-3 py-2 text-xs font-semibold ${
                    mapAvailable
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-amber-100 text-amber-800"
                  }`}
                >
                  {mapAvailable ? "MOLA map received" : "Waiting for map"}
                </span>
              </div>
            </div>

            <div className="relative min-h-[240px] flex-1 bg-[#080e1b]">
              <Canvas
                camera={{
                  position: [5, 5, 8],
                  fov: 60,
                  near: 0.05,
                  far: 500,
                }}
              >
                <color attach="background" args={["#080e1b"]} />

                {showGrid && (
                  <Grid
                    position={[0, -1, 0]}
                    args={[30, 30]}
                    cellColor="#263348"
                    sectionColor="#516680"
                    fadeDistance={50}
                    infiniteGrid
                  />
                )}

                <axesHelper args={[1]} />

                {showPoints && (
                  <PointLayer
                    points={points}
                    pointSize={pointSize}
                    colorMode="height"
                  />
                )}

                {showOccupancy && occupancyAligned && occupancy && (
                  <OccupancyOverlay
                    grid={occupancy}
                    elevation={(pose?.position.z ?? 0) - 0.10}
                    opacity={occupancyOpacity}
                  />
                )}

                {showFloor && highlightedPoints.length > 0 && (
                  <PointLayer
                    points={highlightedPoints}
                    pointSize={pointSize * 1.8}
                    colorMode="solid"
                    color={planeColor}
                  />
                )}

                {framesAligned && pose && (
                  <RobotMarker pose={pose} />
                )}

                {destination && destinationFrameAligned && (
                  <DestinationMarker destination={destination} />
                )}

                {showRoute &&
                  routeAvailable &&
                  pose &&
                  destination && (
                    <RoutePreview
                      pose={pose}
                      destination={destination}
                    />
                  )}

                <DestinationSelectionPlane
                  enabled={
                    selectionMode &&
                    mapAvailable &&
                    !!map?.frame_id
                  }
                  height={pose?.position.z ?? 0}
                  onSelect={handleSelectDestination}
                />

                <ambientLight intensity={1.5} />

                <OrbitControls
                  makeDefault
                  target={[0, 0, 0]}
                  enableDamping
                />

                <CameraController
                  topViewRequest={topViewRequest}
                  pose={pose}
                />
              </Canvas>

              {!mapAvailable && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                  <div className="rounded-xl bg-slate-900/90 px-6 py-4 text-center text-white">
                    <p className="font-semibold">Waiting for MOLA map</p>
                    <p className="mt-2 text-xs text-slate-300">
                      {mapError ?? map?.message ?? "No map snapshot"}
                    </p>
                  </div>
                </div>
              )}

              {showOccupancy && occupancyAligned && occupancy && (
                <div className="pointer-events-none absolute bottom-14 left-4 rounded bg-slate-900/85 px-3 py-2 text-xs text-white">
                  Grey = observed geometry, not verified free space
                  <span className="ml-2 text-amber-300">
                    {occupancy.map_fresh ? "Snapshot fresh" : "Snapshot stale"}
                  </span>
                </div>
              )}

              {selectionMode && (
                <div className="pointer-events-none absolute left-4 top-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white">
                  Click the coffee-machine location
                </div>
              )}

              {showFloor && selectedPlane && (
                <div className="pointer-events-none absolute right-4 top-4 rounded-lg bg-slate-900/90 px-4 py-3 text-xs text-white">
                  <p className="font-bold">
                    Plane {selectedPlane.id} · {highlightedPoints.length} matching points
                  </p>
                  <p className="mt-1">
                    Tilt: {selectedPlane.tilt_degrees.toFixed(2)}°
                  </p>
                  <p className="mt-1 text-amber-300">
                    Unverified surface · diagnostic only
                  </p>
                </div>
              )}

              <div className="pointer-events-none absolute bottom-4 left-4 rounded bg-slate-900/80 px-3 py-2 text-xs text-white">
                Drag: rotate · Scroll: zoom · Right-drag: pan
              </div>
            </div>

            <div className="flex flex-wrap justify-between gap-3 border-t p-4 text-xs text-slate-500">
              <span>Map frame: {map?.frame_id || "Unknown"}</span>
              <span>
                {mapAvailable
                  ? `Snapshot age: ${format(map?.age_seconds)} s`
                  : "No map data"}
              </span>
            </div>
          </section>
          <div className="h-[205px] shrink-0 overflow-y-auto rounded-xl [scrollbar-width:thin]">
          <VerticalCrossSection
            points={points}
            pose={framesAligned ? pose : null}
            candidates={floorFrameAligned ? floor?.candidates ?? [] : []}
            selectedPlaneId={selectedPlaneId}
          />
          </div>
          </div>

          <aside className="min-h-0 min-w-0 space-y-2 overflow-y-auto overscroll-contain pr-1 [scrollbar-width:thin]">
            <section className="rounded-xl border bg-white p-3">
              <h2 className="font-bold">Robot Localization</h2>

              <div className="mt-4 grid grid-cols-3 gap-2">
                {(["x", "y", "z"] as const).map((axis) => (
                  <div
                    key={axis}
                    className="rounded-lg bg-slate-100 p-3 text-center"
                  >
                    <p className="text-xs uppercase text-slate-500">
                      {axis}
                    </p>
                    <p className="mt-2 text-sm font-bold">
                      {format(pose?.position[axis])}
                    </p>
                    <p className="text-[10px] text-slate-500">metres</p>
                  </div>
                ))}
              </div>

              <div className="mt-4 space-y-2 text-xs text-slate-600">
                <p>
                  <strong>Yaw:</strong>{" "}
                  {pose
                    ? `${(pose.yaw * 180 / Math.PI).toFixed(2)}°`
                    : "—"}
                </p>
                <p>
                  <strong>Pose frame:</strong>{" "}
                  {pose?.frame_id ?? "Unknown"}
                </p>
                <p>
                  <strong>Map frame:</strong>{" "}
                  {map?.frame_id ?? "Unknown"}
                </p>
                <p>
                  <strong>Frame match:</strong>{" "}
                  {framesAligned ? "Yes" : "Not verified"}
                </p>
              </div>

              {poseError && (
                <p className="mt-3 text-xs text-red-600">{poseError}</p>
              )}
            </section>
            <section className="rounded-xl border bg-white p-3">
              <h2 className="font-bold">Coffee Machine Destination</h2>
              <p className="mt-2 text-xs text-slate-500">
                Select a candidate destination in the MOLA map frame.
              </p>

              <button
                type="button"
                disabled={!mapAvailable}
                onClick={() =>
                  setSelectionMode((previous) => !previous)
                }
                className={`mt-4 w-full rounded-lg px-4 py-3 text-sm font-semibold text-white disabled:opacity-50 ${
                  selectionMode
                    ? "bg-slate-700"
                    : "bg-blue-600 hover:bg-blue-700"
                }`}
              >
                {selectionMode
                  ? "Cancel Selection"
                  : "Select Coffee Machine"}
              </button>

              {destination && (
                <div className="mt-4 rounded-lg bg-slate-100 p-3">
                  <p className="text-xs font-semibold text-slate-500">
                    Candidate map coordinates
                  </p>

                  <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                    {(["x", "y", "z"] as const).map((axis) => (
                      <div key={axis}>
                        <p className="text-xs uppercase text-slate-500">
                          {axis}
                        </p>
                        <p className="font-bold">
                          {format(destination[axis])}
                        </p>
                      </div>
                    ))}
                  </div>

                  <p className="mt-3 text-xs text-slate-500">
                    Frame: {destination.frame_id}
                  </p>
                </div>
              )}

              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  disabled={!destination || destinationSaved}
                  onClick={saveDestination}
                  className="flex-1 rounded-lg bg-emerald-700 px-3 py-3 text-sm font-semibold text-white disabled:opacity-50"
                >
                  {destinationSaved ? "Saved" : "Save Candidate"}
                </button>
                <button
                  type="button"
                  disabled={!destination}
                  onClick={clearDestination}
                  className="rounded-lg border px-3 py-3 text-sm font-semibold disabled:opacity-50"
                >
                  Clear
                </button>
              </div>

              {destinationError && (
                <p className="mt-3 text-xs text-red-600">
                  {destinationError}
                </p>
              )}

              <p className="mt-3 text-xs text-amber-700">
                A selected point is not a verified collision-free goal.
              </p>
            </section>
            <section className="rounded-xl border bg-white p-3">
              <h2 className="font-bold">Route Preview</h2>
              <p className="mt-2 text-sm text-slate-600">
                {distance !== null
                  ? `${distance.toFixed(2)} m straight-line distance`
                  : "Select a destination to preview the route."}
              </p>

              <label className="mt-4 flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={showRoute}
                  onChange={(event) => setShowRoute(event.target.checked)}
                />
                Show straight-line preview
              </label>

              <p className="mt-3 text-xs text-amber-700">
                Not obstacle-aware. No route execution is available.
              </p>
            </section>
            <section className="rounded-xl border bg-white p-3">
              <h2 className="font-bold">Navigation</h2>
              <p className="mt-2 text-sm text-slate-600">
                The coffee-machine route must be validated against
                a traversability map before robot movement.
              </p>

              <Link
                href="/studio/locations"
                className="mt-4 block rounded-lg bg-emerald-700 px-4 py-3 text-center text-sm font-semibold text-white hover:bg-emerald-800"
              >
                Manage Destinations
              </Link>

              <p className="mt-3 text-xs font-semibold text-amber-700">
                Physical navigation disabled
              </p>
            </section>
          </aside>
        </div>


        <p className="shrink-0 truncate text-[10px] text-slate-500">
          Read-only MOLA visualization. Floor candidates are
          unverified. Destinations are stored only in this browser.
          No physical robot commands are sent.
        </p>
      </div>
    </main>
  );
}