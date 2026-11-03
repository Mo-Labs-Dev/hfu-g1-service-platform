"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type SlamMap = {
  connected: boolean;
  frame_id?: string;
  width?: number;
  height?: number;
  resolution_m?: number;
  origin?: {
    position: { x: number; y: number; z?: number };
    orientation: { x: number; y: number; z: number; w: number };
  };
  data?: number[];
  message?: string;
};

type SlamPose = {
  connected: boolean;
  age_seconds?: number | null;
  pose?: {
    frame_id: string;
    position: { x: number; y: number };
    yaw: number;
    yaw_degrees?: number;
  } | null;
};

type Destination = {
  id: string;
  name: string;
  category: string;
  x: number;
  y: number;
  frameId: string;
  createdAt: string;
};

type SelectedPoint = {
  x: number;
  y: number;
  occupancy: number;
};

const STORAGE_KEY = "hfu-g1-navigation-destinations-v1";
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 8;

const CATEGORIES = [
  "Room",
  "Equipment",
  "Laboratory",
  "Entrance",
  "Facility",
  "Other",
];

function bridgeUrl() {
  const configured = process.env.NEXT_PUBLIC_MAP_BRIDGE_URL;

  if (configured) return configured.replace(/\/$/, "");

  return `${window.location.protocol}//${window.location.hostname}:8769`;
}

function originYaw(map: SlamMap): number {
  const q = map.origin?.orientation;

  if (!q) return 0;

  return Math.atan2(
    2 * (q.w * q.z + q.x * q.y),
    1 - 2 * (q.y * q.y + q.z * q.z)
  );
}

function worldToGrid(map: SlamMap, x: number, y: number) {
  const origin = map.origin;
  const resolution = map.resolution_m;

  if (!origin || !resolution || resolution <= 0) return null;

  const yaw = originYaw(map);
  const dx = x - origin.position.x;
  const dy = y - origin.position.y;

  return {
    x: (Math.cos(yaw) * dx + Math.sin(yaw) * dy) / resolution,
    y: (-Math.sin(yaw) * dx + Math.cos(yaw) * dy) / resolution,
  };
}

function gridToWorld(map: SlamMap, x: number, y: number) {
  const origin = map.origin;
  const resolution = map.resolution_m;

  if (!origin || !resolution || resolution <= 0) return null;

  const yaw = originYaw(map);
  const localX = x * resolution;
  const localY = y * resolution;

  return {
    x:
      origin.position.x +
      Math.cos(yaw) * localX -
      Math.sin(yaw) * localY,
    y:
      origin.position.y +
      Math.sin(yaw) * localX +
      Math.cos(yaw) * localY,
  };
}

function cellOccupancy(map: SlamMap, x: number, y: number) {
  const width = map.width ?? 0;
  const height = map.height ?? 0;

  const col = Math.floor(x);
  const row = Math.floor(y);

  if (
    !map.data ||
    col < 0 ||
    row < 0 ||
    col >= width ||
    row >= height
  ) {
    return -1;
  }

  return map.data[row * width + col];
}

function occupancyLabel(value: number) {
  if (value < 0) return "Unknown area";
  if (value === 0) return "Free cell";
  if (value >= 65) return "Occupied cell";
  return "Partially occupied / uncertain";
}

export default function NavigationPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);

  const [map, setMap] = useState<SlamMap | null>(null);
  const [pose, setPose] = useState<SlamPose | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [zoom, setZoom] = useState(1);
  const [fitMode, setFitMode] = useState(true);
  const [viewport, setViewport] = useState({
    width: 900,
    height: 650,
  });

  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [storageLoaded, setStorageLoaded] = useState(false);

  const [selected, setSelected] = useState<SelectedPoint | null>(null);
  const [destinationName, setDestinationName] = useState("");
  const [category, setCategory] = useState("Room");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  const width = map?.width ?? 0;
  const height = map?.height ?? 0;

  const mapReady = Boolean(
    map?.connected &&
      map.data &&
      map.origin &&
      map.resolution_m &&
      width > 0 &&
      height > 0 &&
      map.data.length === width * height
  );

  const poseReady = Boolean(
    pose?.connected &&
      pose.pose &&
      pose.pose.frame_id === map?.frame_id &&
      (pose.age_seconds == null || pose.age_seconds <= 5)
  );

  // Load destinations from this browser.
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);

      if (saved) {
        const parsed: unknown = JSON.parse(saved);

        if (Array.isArray(parsed)) {
          const valid = parsed.filter(
            (item): item is Destination =>
              item !== null &&
              typeof item === "object" &&
              typeof item.id === "string" &&
              typeof item.name === "string" &&
              typeof item.category === "string" &&
              typeof item.x === "number" &&
              Number.isFinite(item.x) &&
              typeof item.y === "number" &&
              Number.isFinite(item.y) &&
              typeof item.frameId === "string" &&
              typeof item.createdAt === "string"
          );

          setDestinations(valid);
        }
      }
    } catch {
      setNotice("Could not load previously saved destinations.");
    } finally {
      setStorageLoaded(true);
    }
  }, []);

  // Persist changes only after initial loading.
  useEffect(() => {
    if (!storageLoaded) return;

    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(destinations)
      );
    } catch {
      setNotice("Browser storage is unavailable. Changes may not persist.");
    }
  }, [destinations, storageLoaded]);

  // Poll the existing map bridge.
  useEffect(() => {
    let disposed = false;
    let inFlight = false;
    const controller = new AbortController();

    async function poll() {
      if (inFlight) return;
      inFlight = true;

      try {
        const base = bridgeUrl();

        const [mapResponse, poseResponse] = await Promise.all([
          fetch(`${base}/slam/map`, {
            cache: "no-store",
            signal: controller.signal,
          }),
          fetch(`${base}/slam/pose`, {
            cache: "no-store",
            signal: controller.signal,
          }),
        ]);

        if (!mapResponse.ok || !poseResponse.ok) {
          throw new Error("SLAM map bridge returned an error");
        }

        const nextMap = (await mapResponse.json()) as SlamMap;
        const nextPose = (await poseResponse.json()) as SlamPose;

        if (!disposed) {
          setMap(nextMap);
          setPose(nextPose);
          setError(null);
        }
      } catch (err) {
        if (!disposed) {
          setError(
            err instanceof Error
              ? err.message
              : "Map bridge unavailable"
          );
        }
      } finally {
        inFlight = false;
      }
    }

    void poll();

    const timer = window.setInterval(() => void poll(), 2000);

    return () => {
      disposed = true;
      window.clearInterval(timer);
      controller.abort();
    };
  }, []);

  // Measure the map viewer.
  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;

    const update = () => {
      setViewport({
        width: element.clientWidth,
        height: element.clientHeight,
      });
    };

    update();

    const observer = new ResizeObserver(update);
    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  // Draw map, robot, selected point and saved destinations.
  useEffect(() => {
    const canvas = canvasRef.current;

    if (!canvas || !map || !mapReady || !map.data) return;

    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const image = ctx.createImageData(width, height);

    for (let row = 0; row < height; row++) {
      for (let col = 0; col < width; col++) {
        const occupancy = map.data[row * width + col];
        const index = ((height - 1 - row) * width + col) * 4;

        const value =
          occupancy < 0
            ? 190
            : occupancy >= 65
              ? 42
              : occupancy === 0
                ? 255
                : Math.max(0, Math.round(255 - occupancy * 1.8));

        image.data[index] = value;
        image.data[index + 1] = value;
        image.data[index + 2] = value;
        image.data[index + 3] = 255;
      }
    }

    ctx.putImageData(image, 0, 0);

    // Draw saved destinations.
    destinations.forEach((destination, index) => {
      if (destination.frameId !== (map.frame_id ?? "")) return;

      const grid = worldToGrid(map, destination.x, destination.y);
      if (!grid) return;

      const px = grid.x;
      const py = height - grid.y;

      if (px < 0 || py < 0 || px >= width || py >= height) return;

      const active = activeId === destination.id;

      ctx.beginPath();
      ctx.arc(px, py, active ? 10 : 8, 0, Math.PI * 2);
      ctx.fillStyle = active ? "#ea580c" : "#2563eb";
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 10px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(index + 1), px, py);
    });

    // Draw the temporary selected point.
    if (selected) {
      const grid = worldToGrid(map, selected.x, selected.y);

      if (grid) {
        const px = grid.x;
        const py = height - grid.y;

        if (px >= 0 && py >= 0 && px < width && py < height) {
          ctx.beginPath();
          ctx.arc(px, py, 10, 0, Math.PI * 2);
          ctx.strokeStyle = "#e58b28";
          ctx.lineWidth = 3;
          ctx.stroke();

          ctx.beginPath();
          ctx.arc(px, py, 3, 0, Math.PI * 2);
          ctx.fillStyle = "#e58b28";
          ctx.fill();
        }
      }
    }

    // Draw live G1 position and heading.
    if (
      poseReady &&
      pose?.pose &&
      map.origin &&
      map.resolution_m
    ) {
      const grid = worldToGrid(
        map,
        pose.pose.position.x,
        pose.pose.position.y
      );

      if (grid) {
        const px = grid.x;
        const py = height - grid.y;

        if (px >= 0 && py >= 0 && px < width && py < height) {
          const angle = pose.pose.yaw - originYaw(map);

          ctx.save();
          ctx.translate(px, py);
          ctx.rotate(-angle);

          ctx.fillStyle = "#009b77";
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 2;

          ctx.beginPath();
          ctx.arc(0, 0, 6, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();

          ctx.strokeStyle = "#006e55";
          ctx.lineWidth = 3;

          ctx.beginPath();
          ctx.moveTo(0, 0);
          ctx.lineTo(16, 0);
          ctx.stroke();

          ctx.restore();
        }
      }
    }
  }, [
    map,
    pose,
    mapReady,
    poseReady,
    width,
    height,
    destinations,
    selected,
    activeId,
  ]);

  const fitScale =
    width > 0 && height > 0
      ? Math.max(
          0.01,
          Math.min(
            Math.max(1, viewport.width - 40) / width,
            Math.max(1, viewport.height - 40) / height
          )
        )
      : 1;

  const scale = (fitMode ? fitScale : 1) * zoom;

  const displayedWidth = Math.max(1, Math.round(width * scale));
  const displayedHeight = Math.max(1, Math.round(height * scale));

  const zoomIn = useCallback(() => {
    setZoom((value) => Math.min(MAX_ZOOM, value * 1.25));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((value) => Math.max(MIN_ZOOM, value / 1.25));
  }, []);

  function handleMapClick(event: React.MouseEvent<HTMLCanvasElement>) {
    if (!map || !mapReady) return;

    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();

    if (rect.width <= 0 || rect.height <= 0) return;

    const canvasX =
      ((event.clientX - rect.left) / rect.width) * width;

    const canvasY =
      ((event.clientY - rect.top) / rect.height) * height;

    // Canvas Y increases downward; ROS occupancy grid Y increases upward.
    const gridX = canvasX;
    const gridY = height - canvasY;

    const world = gridToWorld(map, gridX, gridY);
    if (!world) return;

    const occupancy = cellOccupancy(map, gridX, gridY);

    setSelected({
      x: world.x,
      y: world.y,
      occupancy,
    });

    setActiveId(null);
    setNotice("");
  }

  function saveDestination() {
    if (!selected || !map || !mapReady) return;

    const name = destinationName.trim();

    if (!name) {
      setNotice("Please enter a destination name.");
      return;
    }

    // Recheck against the latest occupancy grid.
    const grid = worldToGrid(map, selected.x, selected.y);

    if (!grid || cellOccupancy(map, grid.x, grid.y) !== 0) {
      setNotice("Choose a known free cell before saving.");
      return;
    }

    const duplicate = destinations.some(
      (destination) =>
        destination.frameId === (map.frame_id ?? "") &&
        destination.name.toLowerCase() === name.toLowerCase()
    );

    if (duplicate) {
      setNotice("A destination with this name already exists.");
      return;
    }

    const destination: Destination = {
      id: crypto.randomUUID(),
      name,
      category,
      x: selected.x,
      y: selected.y,
      frameId: map.frame_id ?? "",
      createdAt: new Date().toISOString(),
    };

    setDestinations((current) => [...current, destination]);
    setActiveId(destination.id);
    setSelected(null);
    setDestinationName("");
    setNotice(`${name} saved in this browser.`);
  }

  function deleteDestination(id: string) {
    const destination = destinations.find((item) => item.id === id);
    if (!destination) return;

    if (!window.confirm(`Delete "${destination.name}"?`)) return;

    setDestinations((current) =>
      current.filter((item) => item.id !== id)
    );

    if (activeId === id) setActiveId(null);

    setNotice(`${destination.name} deleted.`);
  }

  const buttonClass =
    "rounded-md border border-[#d8ddda] bg-white px-3 py-2 text-[12px] font-semibold text-[#505a60] hover:bg-[#eef5f2] disabled:cursor-not-allowed disabled:opacity-40";

  const fieldClass =
    "w-full rounded-md border border-[#d8ddda] bg-white px-3 py-2.5 text-[13px] text-[#292f33] outline-none focus:border-[#009b77]";

  const activeDestination = destinations.find(
    (destination) => destination.id === activeId
  );

  return (
    <div className="mx-auto w-full max-w-[1750px] px-6 py-8">
      <div className="mb-7 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#008567]">
            HFU · IPSE · G1 Studio
          </p>

          <h1 className="mt-2 text-[30px] font-bold text-[#292f33]">
            Robot Navigation
          </h1>

          <p className="mt-2 text-[13px] text-[#657078]">
            Live SLAM mapping · Robot localization · Destination management
          </p>
        </div>

        <div className="flex flex-wrap gap-4 text-[12px] font-semibold">
          <span className={mapReady ? "text-[#008567]" : "text-amber-700"}>
            ● {mapReady ? "Map connected" : "Map unavailable"}
          </span>

          <span className={poseReady ? "text-[#008567]" : "text-amber-700"}>
            ● {poseReady ? "Robot localized" : "Pose unavailable"}
          </span>
        </div>
      </div>

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="border border-[#dfe3e1] bg-white p-5">
          <p className="text-[11px] text-[#657078]">Map dimensions</p>
          <p className="mt-2 text-[19px] font-bold text-[#292f33]">
            {mapReady
              ? `${(width * (map?.resolution_m ?? 0)).toFixed(2)} × ${(height * (map?.resolution_m ?? 0)).toFixed(2)} m`
              : "Unavailable"}
          </p>
        </div>

        <div className="border border-[#dfe3e1] bg-white p-5">
          <p className="text-[11px] text-[#657078]">Saved destinations</p>
          <p className="mt-2 text-[19px] font-bold text-[#292f33]">
            {destinations.length}
          </p>
        </div>

        <div className="border border-[#dfe3e1] bg-white p-5">
          <p className="text-[11px] text-[#657078]">Navigation mode</p>
          <p className="mt-2 text-[19px] font-bold text-amber-700">
            Visualization only
          </p>
        </div>
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="min-w-0 border border-[#dfe3e1] bg-white">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#e5e8e6] px-5 py-5">
            <div>
              <h2 className="text-[19px] font-bold text-[#292f33]">
                Laboratory SLAM Map
              </h2>

              <p className="mt-1 text-[11px] text-[#657078]">
                Click a known free cell to select a destination
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className={buttonClass}
                onClick={zoomOut}
                disabled={!mapReady || zoom <= MIN_ZOOM}
              >
                −
              </button>

              <span className="min-w-[52px] text-center text-[12px] font-semibold">
                {Math.round(zoom * 100)}%
              </span>

              <button
                type="button"
                className={buttonClass}
                onClick={zoomIn}
                disabled={!mapReady || zoom >= MAX_ZOOM}
              >
                +
              </button>

              <button
                type="button"
                className={buttonClass}
                onClick={() => {
                  setFitMode(true);
                  setZoom(1);
                }}
              >
                Fit Map
              </button>

              <button
                type="button"
                className={buttonClass}
                onClick={() => {
                  setFitMode(false);
                  setZoom(1);
                }}
              >
                Reset View
              </button>
            </div>
          </div>

          {error && (
            <p role="alert" className="px-5 pt-4 text-[12px] text-red-700">
              Map bridge: {error}
            </p>
          )}

          <div className="p-4">
            <div
              ref={viewportRef}
              className="relative h-[650px] w-full overflow-auto border border-[#dfe3e1] bg-[#f4f6f5]"
            >
              {mapReady ? (
                <div
                  className="flex min-h-full min-w-full items-center justify-center p-4"
                  style={{
                    width: "max-content",
                    height: "max-content",
                  }}
                >
                  <canvas
                    ref={canvasRef}
                    onClick={handleMapClick}
                    role="button"
                    tabIndex={0}
                    aria-label="Select a destination on the SLAM map"
                    className="shrink-0 cursor-crosshair border border-[#cbd3cf]"
                    style={{
                      width: displayedWidth,
                      height: displayedHeight,
                      imageRendering: "pixelated",
                    }}
                  />
                </div>
              ) : (
                <div className="flex h-full items-center justify-center p-6">
                  <p className="text-[13px] text-[#657078]">
                    {map?.message ?? "Waiting for live SLAM map…"}
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-5 px-5 pb-4 text-[12px] text-[#657078]">
            <span>□ Free space</span>
            <span>■ Occupied</span>
            <span>◼ Unknown</span>
            <span className="text-[#008567]">● G1 robot</span>
            <span className="text-blue-700">● Saved destination</span>
            <span className="text-orange-600">◎ Selected point</span>
          </div>

          <div className="border-t border-[#e5e8e6] px-5 py-4">
            <p className="text-[12px] text-[#505a60]">
              {poseReady && pose?.pose
                ? `G1 position: X ${pose.pose.position.x.toFixed(2)} m · Y ${pose.pose.position.y.toFixed(2)} m · Heading ${(pose.pose.yaw_degrees ?? (pose.pose.yaw * 180) / Math.PI).toFixed(1)}°`
                : "No verified live robot position"}
            </p>
          </div>
        </section>

        <aside className="space-y-5">
          <section className="border border-[#dfe3e1] bg-white p-5">
            <h2 className="text-[17px] font-bold text-[#292f33]">
              Add Destination
            </h2>

            <p className="mt-2 text-[12px] leading-5 text-[#657078]">
              Select a point on the map, then name the location.
            </p>

            <div className="mt-5 rounded-md bg-[#f3f6f4] p-4">
              {selected ? (
                <div className="space-y-2 text-[12px]">
                  <p className="font-semibold text-[#292f33]">
                    Selected map position
                  </p>

                  <p>X: {selected.x.toFixed(3)} m</p>
                  <p>Y: {selected.y.toFixed(3)} m</p>

                  <p
                    className={
                      selected.occupancy === 0
                        ? "font-semibold text-[#008567]"
                        : "font-semibold text-amber-700"
                    }
                  >
                    {occupancyLabel(selected.occupancy)}
                  </p>
                </div>
              ) : (
                <p className="text-[12px] text-[#657078]">
                  No position selected. Click the SLAM map.
                </p>
              )}
            </div>

            <div className="mt-5 space-y-4">
              <div>
                <label
                  htmlFor="destination-name"
                  className="mb-2 block text-[12px] font-semibold"
                >
                  Destination name
                </label>

                <input
                  id="destination-name"
                  type="text"
                  maxLength={80}
                  placeholder="e.g. 3D Printing Area"
                  className={fieldClass}
                  value={destinationName}
                  onChange={(event) =>
                    setDestinationName(event.target.value)
                  }
                />
              </div>

              <div>
                <label
                  htmlFor="destination-category"
                  className="mb-2 block text-[12px] font-semibold"
                >
                  Category
                </label>

                <select
                  id="destination-category"
                  className={fieldClass}
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  {CATEGORIES.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="button"
                onClick={saveDestination}
                disabled={
                  !mapReady ||
                  !selected ||
                  selected.occupancy !== 0 ||
                  !destinationName.trim()
                }
                className="w-full rounded-md bg-[#009b77] px-4 py-3 text-[13px] font-bold text-white hover:bg-[#008567] disabled:cursor-not-allowed disabled:opacity-40"
              >
                + Save Destination
              </button>

              <button
                type="button"
                onClick={() => {
                  setSelected(null);
                  setNotice("");
                }}
                className={buttonClass + " w-full"}
              >
                Clear Selection
              </button>
            </div>

            {notice && (
              <p role="status" className="mt-4 text-[12px] text-[#505a60]">
                {notice}
              </p>
            )}
          </section>

          <section className="border border-[#dfe3e1] bg-white p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-[17px] font-bold text-[#292f33]">
                Destinations
              </h2>

              <span className="rounded-md bg-[#edf3f0] px-2 py-1 text-[11px] font-bold text-[#008567]">
                {destinations.length}
              </span>
            </div>

            <p className="mt-2 text-[11px] text-[#657078]">
              Saved in this browser. Not yet synchronized with G1.
            </p>

            <div className="mt-4 max-h-[420px] space-y-3 overflow-y-auto">
              {destinations.length === 0 ? (
                <p className="rounded-md bg-[#f3f6f4] p-4 text-[12px] text-[#657078]">
                  No destinations saved yet.
                </p>
              ) : (
                destinations.map((destination, index) => {
                  const active = activeId === destination.id;
                  const sameFrame =
                    destination.frameId === (map?.frame_id ?? "");

                  return (
                    <div
                      key={destination.id}
                      className={`rounded-md border p-3 ${
                        active
                          ? "border-[#009b77] bg-[#f1f9f6]"
                          : "border-[#e1e6e3]"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
                          {index + 1}
                        </span>

                        <div className="min-w-0 flex-1">
                          <p className="break-words text-[13px] font-bold text-[#292f33]">
                            {destination.name}
                          </p>

                          <p className="mt-1 text-[11px] text-[#657078]">
                            {destination.category}
                          </p>

                          <p className="mt-2 text-[11px] text-[#657078]">
                            X {destination.x.toFixed(2)} · Y{" "}
                            {destination.y.toFixed(2)} m
                          </p>

                          {!sameFrame && (
                            <p className="mt-2 text-[11px] text-amber-700">
                              Different map frame — verify before use
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="mt-3 flex gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setActiveId(destination.id);
                            setSelected(null);
                          }}
                          className={buttonClass + " flex-1"}
                        >
                          Show on Map
                        </button>

                        <button
                          type="button"
                          onClick={() => deleteDestination(destination.id)}
                          className="rounded-md border border-red-200 px-3 py-2 text-[12px] font-semibold text-red-700 hover:bg-red-50"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {activeDestination && (
              <div className="mt-4 border-t border-[#e5e8e6] pt-4">
                <p className="text-[12px] font-semibold text-[#292f33]">
                  Selected destination
                </p>

                <p className="mt-1 text-[12px] text-[#657078]">
                  {activeDestination.name}
                </p>

                <p className="mt-2 text-[11px] text-amber-700">
                  Route planning and robot movement are not enabled.
                </p>
              </div>
            )}
          </section>
        </aside>
      </div>

      <p className="mt-6 text-[12px] leading-6 text-[#657078]">
        Safety: A free occupancy-grid cell is not proof of a safe humanoid
        destination. Saved locations are map annotations only. They must be
        revalidated after remapping, relocalization or changes to the map
        coordinate frame. No physical navigation commands are issued here.
      </p>
    </div>
  );
}