"use client";

import {
  ChangeEvent,
  useEffect,
  useRef,
  useState,
} from "react";

type VisionSource = "offline" | "test-image";

type BoundingBox = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

type Detection = {
  label: string;
  class_id: number;
  confidence: number;
  bbox: BoundingBox;
};

type DetectionResponse = {
  status: string;
  model: string;
  image: {
    width: number;
    height: number;
  };
  count: number;
  detections: Detection[];
};

type VisionStatus = {
  status: string;
  model: string;
  camera_connected: boolean;
  object_detection: string;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

export default function VisionPage() {
  const [source, setSource] =
    useState<VisionSource>("offline");

  const [imageUrl, setImageUrl] =
    useState<string | null>(null);

  const [selectedFile, setSelectedFile] =
    useState<File | null>(null);

  const [detections, setDetections] =
    useState<Detection[]>([]);

  const [imageDimensions, setImageDimensions] =
    useState<{ width: number; height: number } | null>(null);

  const [visionStatus, setVisionStatus] =
    useState<VisionStatus | null>(null);

  const [detecting, setDetecting] =
    useState(false);

  const [modelName, setModelName] =
    useState<string>("Not loaded");

  const [message, setMessage] = useState(
    "G1 camera authentication is pending. Load a test image to begin."
  );

  const fileInputRef =
    useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;

    async function loadVisionStatus() {
      try {
        const response = await fetch(
          `${API_BASE}/api/vision/status`,
          { cache: "no-store" }
        );

        if (!response.ok) {
          throw new Error(
            `Vision API returned HTTP ${response.status}`
          );
        }

        const data: VisionStatus =
          await response.json();

        if (active) {
          setVisionStatus(data);
          setModelName(data.model);
        }
      } catch {
        if (active) {
          setVisionStatus(null);
        }
      }
    }

    loadVisionStatus();

    return () => {
      active = false;
    };
  }, []);

  function handleImageUpload(
    event: ChangeEvent<HTMLInputElement>
  ) {
    const file = event.target.files?.[0];

    if (!file) return;

    if (
      !["image/jpeg", "image/png", "image/webp"].includes(
        file.type
      )
    ) {
      setMessage(
        "Please select a JPEG, PNG or WebP image."
      );
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setMessage(
        "The image must be smaller than 10 MB."
      );
      return;
    }

    const reader = new FileReader();

    reader.onload = () => {
      setImageUrl(String(reader.result));
      setSelectedFile(file);
      setSource("test-image");
      setDetections([]);
      setImageDimensions(null);

      setMessage(
        "Test image loaded. Click Detect Objects to run YOLO."
      );
    };

    reader.onerror = () => {
      setMessage("Failed to load the image.");
    };

    reader.readAsDataURL(file);

    event.target.value = "";
  }

  async function detectObjects() {
    if (!selectedFile || detecting) {
      return;
    }

    setDetecting(true);
    setDetections([]);
    setMessage("Running YOLO object detection...");

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await fetch(
        `${API_BASE}/api/vision/detect`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;

        try {
          const errorData = await response.json();
          if (typeof errorData.detail === "string") {
            detail = errorData.detail;
          }
        } catch {
          // Keep HTTP error message.
        }

        throw new Error(detail);
      }

      const data: DetectionResponse =
        await response.json();

      setDetections(data.detections);
      setImageDimensions(data.image);
      setModelName(data.model);

      setMessage(
        `Detection completed: ${data.count} object(s) found.`
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? `Detection failed: ${error.message}`
          : "Detection failed."
      );
    } finally {
      setDetecting(false);
    }
  }

  function captureSnapshot() {
    if (!imageUrl) {
      setMessage("No image is available.");
      return;
    }

    const link = document.createElement("a");
    link.href = imageUrl;
    link.download = `g1-vision-${Date.now()}.png`;
    link.click();

    setMessage("Snapshot downloaded.");
  }

  function clearPreview() {
    setImageUrl(null);
    setSelectedFile(null);
    setSource("offline");
    setDetections([]);
    setImageDimensions(null);
    setMessage("Preview cleared.");
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto max-w-7xl space-y-6">
        <header>
          <h1 className="text-3xl font-semibold">
            G1 Vision
          </h1>

          <p className="mt-1 text-sm text-slate-500">
            IPSE · Visual Perception &amp; Object Recognition
          </p>
        </header>

        <div className="grid gap-6 lg:grid-cols-3">
          <section className="space-y-4 lg:col-span-2">
            <div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
              <div className="flex items-center justify-between border-b p-4">
                <h2 className="font-semibold">
                  G1 Head Camera
                </h2>

                <span
                  className={`rounded-full px-3 py-1 text-xs font-medium ${
                    source === "test-image"
                      ? "bg-blue-100 text-blue-800"
                      : "bg-amber-100 text-amber-800"
                  }`}
                >
                  {source === "test-image"
                    ? "Test Image"
                    : "Camera Offline"}
                </span>
              </div>

              <div className="relative flex aspect-video items-center justify-center overflow-hidden bg-slate-950">
                {imageUrl ? (
                  <div className="relative h-full w-full">
                    <img
                      src={imageUrl}
                      alt="G1 Vision preview"
                      className="h-full w-full object-contain"
                    />

                    {imageDimensions && (
                      <svg
                        className="pointer-events-none absolute inset-0 h-full w-full"
                        viewBox={`0 0 ${imageDimensions.width} ${imageDimensions.height}`}
                        preserveAspectRatio="xMidYMid meet"
                      >
                        {detections.map((item, index) => {
                          const {
                            x1,
                            y1,
                            x2,
                            y2,
                          } = item.bbox;

                          return (
                            <g key={`${item.label}-${index}`}>
                              <rect
                                x={x1}
                                y={y1}
                                width={Math.max(0, x2 - x1)}
                                height={Math.max(0, y2 - y1)}
                                fill="none"
                                stroke="#22c55e"
                                strokeWidth="3"
                              />

                              <text
                                x={x1}
                                y={Math.max(18, y1 - 8)}
                                fill="#22c55e"
                                fontSize="20"
                                fontWeight="bold"
                              >
                                {item.label}{" "}
                                {Math.round(
                                  item.confidence * 100
                                )}
                                %
                              </text>
                            </g>
                          );
                        })}
                      </svg>
                    )}
                  </div>
                ) : (
                  <div className="text-center text-slate-400">
                    <div className="text-5xl">📷</div>

                    <p className="mt-4 font-medium">
                      G1 Camera Not Connected
                    </p>

                    <p className="mt-2 text-sm">
                      Waiting for authenticated WebRTC video
                    </p>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-3 p-4">
                <button
                  type="button"
                  onClick={() =>
                    fileInputRef.current?.click()
                  }
                  disabled={detecting}
                  className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800 disabled:opacity-40"
                >
                  Load Test Image
                </button>

                <button
                  type="button"
                  onClick={detectObjects}
                  disabled={!selectedFile || detecting}
                  className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {detecting
                    ? "Detecting..."
                    : "Detect Objects"}
                </button>

                <button
                  type="button"
                  onClick={captureSnapshot}
                  disabled={!imageUrl || detecting}
                  className="rounded-lg border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Save Snapshot
                </button>

                <button
                  type="button"
                  onClick={clearPreview}
                  disabled={detecting}
                  className="rounded-lg border px-4 py-2 text-sm font-medium disabled:opacity-40"
                >
                  Clear
                </button>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleImageUpload}
                  className="hidden"
                />
              </div>
            </div>

            <div className="rounded-xl border bg-white p-4 text-sm text-slate-600">
              {message}
            </div>
          </section>

          <aside className="space-y-6">
            <section className="rounded-2xl border bg-white p-5 shadow-sm">
              <h2 className="font-semibold">
                Vision Status
              </h2>

              <div className="mt-5 space-y-4 text-sm">
                <StatusRow
                  label="Camera"
                  value={
                    source === "test-image"
                      ? "Test Mode"
                      : "Offline"
                  }
                />

                <StatusRow
                  label="Vision API"
                  value={
                    visionStatus
                      ? "Connected"
                      : "Unavailable"
                  }
                />

                <StatusRow
                  label="Detection Model"
                  value={modelName}
                />

                <StatusRow
                  label="Detected Objects"
                  value={String(detections.length)}
                />

                <StatusRow
                  label="Physical Walking"
                  value="Locked"
                />
              </div>
            </section>

            <section className="rounded-2xl border bg-white p-5 shadow-sm">
              <h2 className="font-semibold">
                Object Detection
              </h2>

              <p className="mt-2 text-sm text-slate-500">
                Results from the YOLO detection model.
              </p>

              {detections.length === 0 ? (
                <div className="mt-5 rounded-xl bg-slate-50 p-5 text-center text-sm text-slate-500">
                  {detecting
                    ? "Analyzing image..."
                    : "No detections available"}
                </div>
              ) : (
                <div className="mt-4 max-h-80 space-y-3 overflow-y-auto">
                  {detections.map((item, index) => (
                    <div
                      key={`${item.label}-${index}`}
                      className="rounded-lg border p-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium capitalize">
                          {item.label}
                        </span>

                        <span className="text-sm font-semibold text-emerald-700">
                          {Math.round(
                            item.confidence * 100
                          )}
                          %
                        </span>
                      </div>

                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full bg-emerald-600"
                          style={{
                            width: `${
                              item.confidence * 100
                            }%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded-2xl border bg-white p-5 shadow-sm">
              <h2 className="font-semibold">
                Thesis Use Cases
              </h2>

              <div className="mt-4 space-y-3 text-sm text-slate-600">
                <p>☕ Coffee machine recognition</p>
                <p>🖨️ 3D printer identification</p>
                <p>📦 Object and component detection</p>
                <p>🤖 Visual perception for demonstrations</p>
              </div>

              <p className="mt-4 text-xs text-slate-400">
                Specialized lab-object recognition will
                require model validation or custom training.
              </p>
            </section>
          </aside>
        </div>
      </div>
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
    <div className="flex items-center justify-between gap-4">
      <span className="text-slate-500">
        {label}
      </span>

      <span className="font-medium">
        {value}
      </span>
    </div>
  );
}