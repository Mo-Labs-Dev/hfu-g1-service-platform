"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

export type Point = { x: number; y: number };

export type Destination = {
  id: string;
  name: string;
  position: Point;
};

type Props = {
  showTrajectory?: boolean;
  compact?: boolean;
  selectedDestination?: Destination | null;
  onSelectDestination?: (destination: Destination | null) => void;
  onDestinationsChange?: (destinations: Destination[]) => void;
};

const BASE = "/maps/hfu-session-03";
const STORAGE_KEY = "hfu-g1-session03-destinations-v1";

const MAP = {
  width: 535,
  height: 921,
  resolution: 0.05,
  originX: -13.398484,
  originY: -34.842046,
};

const START: Point = {
  x: 0.09661859376713032,
  y: 0.019047420192766763,
};

const DEFAULT_DESTINATIONS: Destination[] = [
  {
    id: "coffee",
    name: "Coffee Machine",
    position: { x: 0.6, y: 8.0 },
  },
];

function worldToPixel(point: Point): Point {
  return {
    x: (point.x - MAP.originX) / MAP.resolution,
    y: MAP.height - (point.y - MAP.originY) / MAP.resolution,
  };
}

function pixelToWorld(point: Point): Point {
  return {
    x: MAP.originX + point.x * MAP.resolution,
    y: MAP.originY + (MAP.height - point.y) * MAP.resolution,
  };
}

function validPoint(point: Point): boolean {
  return Number.isFinite(point.x) && Number.isFinite(point.y);
}

export default function HfuLabMap2D({
  showTrajectory = false,
  compact = false,
  selectedDestination,
  onSelectDestination,
  onDestinationsChange,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  const dragRef = useRef<{
    x: number;
    y: number;
    moved: boolean;
  } | null>(null);

  const [imageReady, setImageReady] = useState(false);
  const [route, setRoute] = useState<Point[]>([]);
  const [destinations, setDestinations] = useState<Destination[]>(DEFAULT_DESTINATIONS);
  const [selectedId, setSelectedId] = useState("coffee");

  function selectDestination(id: string, list = destinations) {
    setSelectedId(id);
    onSelectDestination?.(list.find((destination) => destination.id === id) ?? null);
  }

  const [adding, setAdding] = useState(false);
  const [pendingPoint, setPendingPoint] = useState<Point | null>(null);
  const [newName, setNewName] = useState("");
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState<Point>({ x: 0, y: 0 });
  const [viewport, setViewport] = useState({ width: 535, height: 600 });
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored) {
        onDestinationsChange?.(DEFAULT_DESTINATIONS);
        onSelectDestination?.(DEFAULT_DESTINATIONS[0]);
      }
      if (stored) {
        const parsed: unknown = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          const valid = parsed.filter(
            (item): item is Destination =>
              typeof item?.id === "string" &&
              typeof item?.name === "string" &&
              typeof item?.position?.x === "number" &&
              typeof item?.position?.y === "number" &&
              validPoint(item.position)
          );

          setDestinations(valid);
          onDestinationsChange?.(valid);
          selectDestination(valid[0]?.id ?? "", valid);
        }
      }
    } catch {
      setError("Could not load saved destinations.");
    }
  }, []);

  useEffect(() => {
    const image = new Image();

    image.onload = () => {
      imageRef.current = image;
      setImageReady(true);
    };

    image.onerror = () => {
      setError("Unable to load the laboratory map PNG.");
    };

    image.src = `${BASE}/hfu_lab_map.png`;

    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, []);

  useEffect(() => {
    fetch(`${BASE}/coffee_historical_route.csv`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Historical route unavailable");
        }
        return response.text();
      })
      .then((csv) => {
        const lines = csv.trim().split(/\r?\n/);
        const header = lines[0].split(",");
        const xIndex = header.indexOf("x");
        const yIndex = header.indexOf("y");

        if (xIndex < 0 || yIndex < 0) {
          throw new Error("CSV requires x,y columns");
        }

        const points = lines
          .slice(1)
          .map((line) => {
            const values = line.split(",");
            return {
              x: Number(values[xIndex]),
              y: Number(values[yIndex]),
            };
          })
          .filter(validPoint);

        setRoute(points);
      })
      .catch((err) => {
        setError(String(err));
      });
  }, []);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;

      setViewport({
        width: rect.width,
        height: rect.height,
      });
    });

    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  const scale = Math.min(
    viewport.width / MAP.height,
    viewport.height / MAP.width
  ) * zoom;

  const imageX =
    (viewport.width - MAP.height * scale) / 2 +
    offset.x;

  const imageY =
    (viewport.height - MAP.width * scale) / 2 +
    offset.y;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const image = imageRef.current;

    if (!canvas) return;

    const context = canvas.getContext("2d");
if (!context) return;

const ctx: CanvasRenderingContext2D = context;

    const dpr = window.devicePixelRatio || 1;

    const pixelWidth = Math.round(viewport.width * dpr);
    const pixelHeight = Math.round(viewport.height * dpr);

    if (
      canvas.width !== pixelWidth ||
      canvas.height !== pixelHeight
    ) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, viewport.width, viewport.height);

    ctx.fillStyle = "#e2e8f0";
    ctx.fillRect(0, 0, viewport.width, viewport.height);

    if (!image) return;

    ctx.save();
    ctx.translate(imageX + MAP.height * scale, imageY);
    ctx.rotate(Math.PI / 2);
    ctx.scale(scale, scale);

    ctx.drawImage(image, 0, 0, MAP.width, MAP.height);

    if (showTrajectory && route.length > 1) {
      ctx.beginPath();

      route.forEach((point, index) => {
        const p = worldToPixel(point);

        if (index === 0) {
          ctx.moveTo(p.x, p.y);
        } else {
          ctx.lineTo(p.x, p.y);
        }
      });

      ctx.strokeStyle = "#2563eb";
      ctx.lineWidth = 2 / scale;
      ctx.stroke();
    }

    function marker(
      point: Point,
      color: string,
      label: string,
      selected = false
    ) {
      const p = worldToPixel(point);
      const radius = (selected ? 9 : 7) / scale;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(-Math.PI / 2);

      ctx.beginPath();
      ctx.arc(0, 0, radius, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();

      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2 / scale;
      ctx.stroke();

      ctx.font = `${12 / scale}px sans-serif`;
      ctx.fillStyle = "#0f172a";
      ctx.fillText(
        label,
        12 / scale,
        -10 / scale
      );
      ctx.restore();
    }

    marker(START, "#16a34a", "Recorded start");

    destinations.forEach((destination) => {
      marker(
        destination.position,
        "#f59e0b",
        destination.name,
        destination.id === (selectedDestination === undefined ? selectedId : selectedDestination?.id)
      );
    });

    if (pendingPoint) {
      marker(pendingPoint, "#a855f7", "New destination");
    }

    ctx.restore();
  }, [
    viewport,
    imageX,
    imageY,
    scale,
    route,
    showTrajectory,
    destinations,
    selectedId,
    pendingPoint,
    selectedDestination,
  ]);

  useEffect(() => {
    if (imageReady) draw();
  }, [draw, imageReady]);

  function screenToWorld(clientX: number, clientY: number) {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;

    // Inverse of the clockwise 90-degree canvas rotation.
    // Screen X = imageX + (MAP.height - originalY) * scale
    // Screen Y = imageY + originalX * scale
    const px = (clientY - rect.top - imageY) / scale;
    const py = MAP.height - (clientX - rect.left - imageX) / scale;

    if (
      px < 0 ||
      py < 0 ||
      px >= MAP.width ||
      py >= MAP.height
    ) {
      return null;
    }

    return pixelToWorld({ x: px, y: py });
  }

  function handlePointerDown(
    event: ReactPointerEvent<HTMLCanvasElement>
  ) {
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      moved: false,
    };

    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(
    event: ReactPointerEvent<HTMLCanvasElement>
  ) {
    const drag = dragRef.current;
    if (!drag) return;

    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;

    if (Math.abs(dx) + Math.abs(dy) > 2) {
      drag.moved = true;
    }

    if (!adding) {
      setOffset((previous) => ({
        x: previous.x + dx,
        y: previous.y + dy,
      }));
    }

    drag.x = event.clientX;
    drag.y = event.clientY;
  }

  function handlePointerUp(
    event: ReactPointerEvent<HTMLCanvasElement>
  ) {
    const drag = dragRef.current;
    dragRef.current = null;

    if (!drag || drag.moved) return;

    const point = screenToWorld(
      event.clientX,
      event.clientY
    );

    if (!point) return;

    if (adding) {
      setPendingPoint(point);
      return;
    }

    const nearest = destinations.find((destination) => {
      const dx = destination.position.x - point.x;
      const dy = destination.position.y - point.y;

      return Math.hypot(dx, dy) < 0.5;
    });

    if (nearest) selectDestination(nearest.id);
  }

  function saveDestinations(next: Destination[]) {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(next)
      );
      setDestinations(next);
      onDestinationsChange?.(next);
      setError("");
    } catch {
      setError("Could not save destinations locally.");
    }
  }

  function addDestination() {
    if (!pendingPoint || !newName.trim()) return;

    const destination: Destination = {
      id: crypto.randomUUID(),
      name: newName.trim(),
      position: pendingPoint,
    };

    saveDestinations([...destinations, destination]);
    selectDestination(destination.id, [...destinations, destination]);
    setAdding(false);
    setPendingPoint(null);
    setNewName("");
  }

  function deleteDestination() {
    const next = destinations.filter(
      (destination) => destination.id !== selectedId
    );

    saveDestinations(next);
    selectDestination(next[0]?.id ?? "", next);
  }

  const selected = destinations.find(
    (destination) => destination.id === (selectedDestination === undefined ? selectedId : selectedDestination?.id)
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">2D Map</h2>
          {!compact && <p className="text-xs text-slate-500">Saved occupancy map</p>}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              setAdding(!adding);
              setPendingPoint(null);
            }}
            className="rounded bg-blue-600 px-3 py-2 text-sm text-white"
          >
            {adding ? "Cancel" : "+ Add Destination"}
          </button>

          <button
            type="button"
            onClick={() =>
              setZoom((z) => Math.min(z * 1.25, 10))
            }
            className="rounded border px-3 py-2"
          >
            +
          </button>

          <button
            type="button"
            onClick={() =>
              setZoom((z) => Math.max(z / 1.25, 0.5))
            }
            className="rounded border px-3 py-2"
          >
            −
          </button>

          <button
            type="button"
            onClick={() => {
              setZoom(1);
              setOffset({ x: 0, y: 0 });
            }}
            className="rounded border px-3 py-2 text-sm"
          >
            Fit
          </button>
        </div>
      </header>

      <div
        ref={containerRef}
        className="relative min-h-0 flex-1 overflow-hidden"
      >
        <canvas
          ref={canvasRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={() => {
            dragRef.current = null;
          }}
          className={
            "h-full w-full touch-none " +
            (adding ? "cursor-crosshair" : "cursor-grab")
          }
        />

        {adding && (
          <div className="absolute left-3 top-3 max-w-xs rounded-lg border bg-white p-3 shadow-lg">
            <p className="mb-2 text-sm font-semibold">
              Add destination
            </p>

            <p className="mb-3 text-xs text-slate-600">
              Click a location on the map.
              Choose the actual landmark position.
            </p>

            <input
              value={newName}
              onChange={(event) =>
                setNewName(event.target.value)
              }
              placeholder="e.g. 3D Printer"
              className="mb-2 w-full rounded border px-3 py-2 text-sm"
            />

            {pendingPoint && (
              <p className="mb-2 text-xs">
                X: {pendingPoint.x.toFixed(2)} m,
                Y: {pendingPoint.y.toFixed(2)} m
              </p>
            )}

            <button
              type="button"
              disabled={!pendingPoint || !newName.trim()}
              onClick={addDestination}
              className="rounded bg-green-600 px-3 py-2 text-sm text-white disabled:opacity-40"
            >
              Save Destination
            </button>
          </div>
        )}
      </div>

      {!compact && <footer className="space-y-2 border-t p-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-slate-500">
            Saved destinations:
          </span>

          <select
            value={selectedId}
            onChange={(event) =>
              selectDestination(event.target.value)
            }
            className="rounded border px-3 py-2 text-sm"
          >
            <option value="">Select destination</option>

            {destinations.map((destination) => (
              <option
                key={destination.id}
                value={destination.id}
              >
                {destination.name}
              </option>
            ))}
          </select>

          {selected && (
            <>
              <span className="text-xs text-slate-600">
                X: {selected.position.x.toFixed(2)},
                Y: {selected.position.y.toFixed(2)}
              </span>

              <button
                type="button"
                onClick={deleteDestination}
                className="rounded border border-red-300 px-3 py-2 text-xs text-red-700"
              >
                Delete
              </button>
            </>
          )}
        </div>

        <div className="flex flex-wrap gap-3 text-xs text-slate-600">
          <span>🟢 Recorded start</span>
          <span>🟠 Destination landmark</span>
          <span>🔵 Historical trajectory</span>
          <span className="font-semibold text-amber-700">
            Physical navigation locked
          </span>
        </div>

        {error && (
          <p className="text-xs text-red-600">{error}</p>
        )}
      </footer>}
    </div>
  );
}