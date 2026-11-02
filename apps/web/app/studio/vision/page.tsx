"use client";

import { useEffect, useState } from "react";

type Detection = {
  label: string;
  class_id: number;
  confidence: number;
  bbox: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  };
};

type DetectionResponse = {
  status: string;
  model: string;
  image: { width: number; height: number };
  count: number;
  detections: Detection[];
};

type CameraStatus = {
  camera_connected: boolean;
  frames_received: number;
  frame_age_seconds: number | null;
  error: string | null;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const DETECTION_INTERVAL_MS = 1200;
const MIN_CONFIDENCE = 0.45;

function cameraBase() {
  const configured = process.env.NEXT_PUBLIC_G1_CAMERA_URL;

  if (configured) {
    return configured.replace(/\/(stream|snapshot|status)\/?$/, "").replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8770`;
  }

  return "http://127.0.0.1:8770";
}

export default function VisionPage() {
  const [camera, setCamera] =
    useState<CameraStatus | null>(null);

  const [frame, setFrame] =
    useState<string | null>(null);

  const [detections, setDetections] =
    useState<Detection[]>([]);

  const [dimensions, setDimensions] = useState({
    width: 1920,
    height: 1080,
  });

  const [model, setModel] = useState("YOLO");
  const [analysisCount, setAnalysisCount] = useState(0);
  const [lastAnalysis, setLastAnalysis] =
    useState<number | null>(null);

  const [error, setError] =
    useState<string | null>(null);

  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    let active = true;
    let currentFrame: string | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const controller = new AbortController();

    async function checkCamera() {
      try {
        const response = await fetch(
          `${cameraBase()}/status`,
          { cache: "no-store" }
        );

        if (!response.ok) throw new Error();

        const data: CameraStatus = await response.json();

        if (active) setCamera(data);
      } catch {
        if (active) setCamera(null);
      }
    }

    async function analyze() {
      if (!active) return;

      let nextFrame: string | null = null;

      try {
        setAnalyzing(true);

        const snapshot = await fetch(
          `${cameraBase()}/snapshot`,
          {
            cache: "no-store",
            signal: controller.signal,
          }
        );

        if (!snapshot.ok) {
          throw new Error("Waiting for camera frames");
        }

        const blob = await snapshot.blob();

        if (!blob.type.includes("jpeg")) {
          throw new Error("Invalid camera image");
        }

        nextFrame = URL.createObjectURL(blob);

        const file = new File(
          [blob],
          "g1-frame.jpg",
          { type: "image/jpeg" }
        );

        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch(
          `${API_BASE}/api/vision/detect`,
          {
            method: "POST",
            body: formData,
            signal: controller.signal,
          }
        );

        if (!response.ok) {
          throw new Error(
            `AI detection unavailable (HTTP ${response.status})`
          );
        }

        const result: DetectionResponse =
          await response.json();

        if (!active) return;

        const previous = currentFrame;
        currentFrame = nextFrame;
        nextFrame = null;

        setFrame(currentFrame);
        setDetections(result.detections);
        setDimensions(result.image);
        setModel(result.model);
        setAnalysisCount((count) => count + 1);
        setLastAnalysis(Date.now());
        setError(null);

        if (previous) {
          URL.revokeObjectURL(previous);
        }
      } catch (err) {
        if (active && !controller.signal.aborted) {
          setError(
            err instanceof Error
              ? err.message
              : "AI detection unavailable"
          );
        }
      } finally {
        if (nextFrame) {
          URL.revokeObjectURL(nextFrame);
        }

        if (active) {
          setAnalyzing(false);

          timer = setTimeout(
            analyze,
            DETECTION_INTERVAL_MS
          );
        }
      }
    }

    void checkCamera();
    void analyze();

    const statusTimer = setInterval(
      checkCamera,
      3000
    );

    return () => {
      active = false;
      controller.abort();
      clearInterval(statusTimer);

      if (timer) clearTimeout(timer);

      if (currentFrame) {
        URL.revokeObjectURL(currentFrame);
      }
    };
  }, []);

  const connected = camera?.camera_connected === true;

  const visible = detections.filter(
    (item) => item.confidence >= MIN_CONFIDENCE
  );

  const counts = visible.reduce<Record<string, number>>(
    (acc, item) => {
      acc[item.label] = (acc[item.label] || 0) + 1;
      return acc;
    },
    {}
  );

  const people = visible.filter(
    (item) => item.label.toLowerCase() === "person"
  ).length;

  const perceptionStatus = !connected
    ? "Waiting for camera"
    : error
      ? "Retrying AI"
      : frame
        ? "Live"
        : "Initializing";

  return (
    <div className="min-h-screen bg-slate-50 px-5 py-5 text-slate-900">
      <div className="mx-auto max-w-[1600px] space-y-4">

        {/* Page header */}
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              HFU · IPSE · G1 Studio
            </p>

            <h1 className="mt-1 text-2xl font-semibold tracking-tight">
              Vision
            </h1>

            <p className="text-xs text-slate-500">
              Physical camera · Automatic object recognition
            </p>
          </div>

          <span
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              connected && !error
                ? "bg-emerald-50 text-emerald-700"
                : "bg-amber-50 text-amber-700"
            }`}
          >
            ● {perceptionStatus}
          </span>
        </header>

        {/* Summary cards */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Summary
            label="CAMERA"
            value={connected ? "Connected" : "Offline"}
            detail="Unitree SDK2"
          />

          <Summary
            label="PERCEPTION"
            value={error ? "Retrying" : "Automatic"}
            detail="Continuous AI analysis"
          />

          <Summary
            label="DETECTED OBJECTS"
            value={String(visible.length)}
            detail={`${people} person(s)`}
          />

          <Summary
            label="AI ANALYSES"
            value={String(analysisCount)}
            detail={model}
          />
        </div>

        {/* Main grid */}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">

          {/* Camera panel */}
          <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">

            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">
                  G1 Head Camera
                </h2>

                <p className="mt-0.5 text-[11px] text-slate-500">
                  Unitree SDK2 · Automatic visual perception
                </p>
              </div>

              <span className="rounded-md bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600">
                1920 × 1080
              </span>
            </div>

            <div className="relative aspect-video w-full overflow-hidden bg-slate-950">

              {frame ? (
                <div className="absolute inset-0">
                  <img
                    src={frame}
                    alt="G1 AI camera"
                    className="h-full w-full object-contain"
                  />

                  <svg
                    className="pointer-events-none absolute inset-0 h-full w-full"
                    viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
                    preserveAspectRatio="xMidYMid meet"
                  >
                    {visible.map((item, index) => {
                      const { x1, y1, x2, y2 } = item.bbox;

                      const isPerson =
                        item.label.toLowerCase() === "person";

                      const color = isPerson
                        ? "#22c55e"
                        : "#f59e0b";

                      const labelY =
                        y1 >= 29 ? y1 - 28 : y1 + 2;

                      const labelWidth = Math.min(
                        260,
                        Math.max(
                          110,
                          item.label.length * 14 + 70
                        )
                      );

                      return (
                        <g key={`${item.label}-${index}`}>
                          <rect
                            x={x1}
                            y={y1}
                            width={Math.max(0, x2 - x1)}
                            height={Math.max(0, y2 - y1)}
                            fill="none"
                            stroke={color}
                            strokeWidth="3"
                          />

                          <rect
                            x={x1}
                            y={labelY}
                            width={labelWidth}
                            height="27"
                            rx="3"
                            fill={color}
                          />

                          <text
                            x={x1 + 6}
                            y={labelY + 19}
                            fill="#0f172a"
                            fontSize="18"
                            fontWeight="600"
                          >
                            {item.label}{" "}
                            {Math.round(item.confidence * 100)}%
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>
              ) : connected ? (
                <img
                  src={`${cameraBase()}/stream`}
                  alt="G1 live camera starting"
                  className="absolute inset-0 h-full w-full object-contain"
                />
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-400">
                  <span className="text-4xl">📷</span>
                  <p className="mt-3 text-sm">
                    Waiting for G1 Camera
                  </p>
                </div>
              )}

              {/* Camera overlays */}
              <div className="pointer-events-none absolute left-4 top-4 flex items-center gap-2 rounded-md bg-black/65 px-3 py-1.5 text-[11px] font-semibold text-white">
                <span
                  className={`h-2 w-2 rounded-full ${
                    connected
                      ? "bg-red-500"
                      : "bg-slate-400"
                  }`}
                />
                {connected ? "G1 CAMERA" : "OFFLINE"}
              </div>

              <div className="pointer-events-none absolute right-4 top-4 rounded-md bg-black/65 px-3 py-1.5 text-[11px] text-white">
                {analyzing
                  ? "Analyzing..."
                  : error
                    ? "AI reconnecting"
                    : "AI recognition"}
              </div>

              {frame && (
                <div className="pointer-events-none absolute bottom-4 left-4 rounded-md bg-black/70 px-3 py-2 text-xs text-white">
                  <span className="font-semibold text-emerald-400">
                    {people}
                  </span>{" "}
                  People
                  <span className="mx-2 text-slate-400">|</span>
                  <span className="font-semibold text-amber-300">
                    {visible.length}
                  </span>{" "}
                  Objects
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
              <span>
                Automatic detection · No manual operation
              </span>

              <span>
                {lastAnalysis
                  ? `Last analysis ${new Date(lastAnalysis).toLocaleTimeString()}`
                  : "Waiting for first analysis"}
              </span>
            </div>
          </section>

          {/* Right-side information */}
          <aside className="space-y-4">

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold">
                Vision Status
              </h2>

              <div className="mt-4 space-y-3">
                <StatusRow
                  label="Camera"
                  value={connected ? "Connected" : "Offline"}
                />

                <StatusRow
                  label="AI Detection"
                  value={error ? "Retrying" : "Automatic"}
                />

                <StatusRow
                  label="Model"
                  value={model}
                />

                <StatusRow
                  label="Frames Received"
                  value={String(camera?.frames_received ?? 0)}
                />

                <StatusRow
                  label="AI Analyses"
                  value={String(analysisCount)}
                />
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">
                  Detected Objects
                </h2>

                <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                  {visible.length}
                </span>
              </div>

              <p className="mt-1 text-[11px] text-slate-500">
                Latest analyzed camera frame
              </p>

              {Object.keys(counts).length === 0 ? (
                <div className="mt-4 rounded-lg bg-slate-50 px-3 py-6 text-center text-xs text-slate-500">
                  No objects detected
                </div>
              ) : (
                <div className="mt-4 space-y-2">
                  {Object.entries(counts).map(
                    ([label, count]) => (
                      <div
                        key={label}
                        className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2.5"
                      >
                        <span className="text-xs font-medium capitalize">
                          {label}
                        </span>

                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold">
                          {count}
                        </span>
                      </div>
                    )
                  )}
                </div>
              )}
            </section>

            {error && (
              <section className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <p className="text-xs font-medium text-amber-800">
                  Vision service
                </p>
                <p className="mt-1 text-xs text-amber-700">
                  {error}. Retrying automatically.
                </p>
              </section>
            )}
          </aside>
        </div>

        <p className="text-center text-[11px] text-slate-400">
          Institute for Product and Service Engineering ·
          Hochschule Furtwangen University
        </p>
      </div>
    </div>
  );
}

function Summary({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <p className="text-[10px] font-semibold tracking-wide text-slate-500">
        {label}
      </p>

      <p className="mt-2 text-base font-semibold text-slate-900">
        {value}
      </p>

      <p className="mt-1 text-[11px] text-slate-500">
        {detail}
      </p>
    </div>
  );
}

function StatusRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">
        {value}
      </span>
    </div>
  );
}