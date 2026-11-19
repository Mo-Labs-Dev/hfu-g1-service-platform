
"use client";

import { useEffect, useState } from "react";

type RobotStatus = {
  connected?: boolean;
  battery?: number;
  mode?: string;
  current_location?: string;
  current_action?: string;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const CAMERA_URL = process.env.NEXT_PUBLIC_G1_CAMERA_URL || "";

export default function StudioDashboardPage() {
  const [robotStatus, setRobotStatus] = useState<RobotStatus | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [cameraOnline, setCameraOnline] = useState(false);
  const [cameraFullscreen, setCameraFullscreen] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadStatus() {
      try {
        const response = await fetch(`${API_URL}/api/robot/status`, {
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error("Backend unavailable");
        }

        const data: RobotStatus = await response.json();

        if (active) {
          setRobotStatus(data);
          setBackendOnline(true);
        }
      } catch {
        if (active) {
          setBackendOnline(false);
          setRobotStatus(null);
        }
      }
    }

    void loadStatus();

    const interval = setInterval(() => {
      void loadStatus();
    }, 5000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const connected = backendOnline && robotStatus?.connected !== false;

  const mode =
    robotStatus?.mode?.toUpperCase() ||
    (backendOnline ? "SIMULATION" : "OFFLINE");

  const cameraConfigured = CAMERA_URL.trim().length > 0;

  const cameraPreview = (
    <div className="relative flex aspect-video items-center justify-center overflow-hidden bg-[#172126]">
      {cameraConfigured ? (
        <img
          src={CAMERA_URL}
          alt="G1 robot camera live preview"
          className="h-full w-full object-contain"
          onLoad={() => setCameraOnline(true)}
          onError={() => setCameraOnline(false)}
        />
      ) : null}

      {(!cameraConfigured || !cameraOnline) && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center bg-[#172126] text-center">
          <svg
            className="h-7 w-7 text-[#8a969b]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m15 10 5-3v10l-5-3" />
            <rect x="3" y="6" width="12" height="12" rx="2" />
            <path d="m3 3 18 18" />
          </svg>

          <p className="mt-3 text-[11px] font-semibold text-white">
            Camera Offline
          </p>

          <p className="mt-1 text-[9px] text-[#9aa6ab]">
            {cameraConfigured
              ? "Waiting for camera stream"
              : "No camera source configured"}
          </p>
        </div>
      )}
    </div>
  );

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {/* PAGE INTRO */}
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto max-w-[1600px] px-6 py-10 md:px-10 lg:px-16 lg:py-14">
          <div className="h-[3px] w-12 bg-[#009b77]" />

          <div className="mt-6 flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
            {/* DASHBOARD HEADING */}
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-[#8a9499]">
                G1 Engineering Environment
              </p>

              <h1 className="mt-5 text-[40px] font-bold tracking-[-0.04em] text-[#2d3337]">
                Dashboard
              </h1>

              <p className="mt-4 text-[14px] text-[#707b81]">
                Robot status, task activity and platform overview.
              </p>
            </div>

            {/* TOP-RIGHT CAMERA PREVIEW */}
            <div className="flex shrink-0 flex-col gap-3 sm:flex-row sm:items-end">
              <div className="w-full overflow-hidden border border-[#dfe3e1] bg-white sm:w-[260px]">
                <div className="flex items-center justify-between border-b border-[#e5e8e6] px-3 py-2">
                  <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#657078]">
                    G1 Head Camera
                  </span>

                  <span className="flex items-center gap-1.5">
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        cameraOnline ? "bg-[#009b77]" : "bg-[#b7bdc0]"
                      }`}
                    />
                    <span className="text-[9px] font-semibold text-[#657078]">
                      {cameraOnline ? "LIVE" : "OFFLINE"}
                    </span>
                  </span>
                </div>

                {cameraPreview}

                <div className="flex items-center justify-between px-3 py-2">
                  <span className="text-[9px] text-[#8b959a]">
                    Robot Vision
                  </span>

                  <button
                    type="button"
                    onClick={() => setCameraFullscreen(true)}
                    className="text-[10px] font-semibold text-[#008567] transition-colors hover:text-[#006f55]"
                    aria-label="Expand camera preview"
                  >
                    Expand ↗
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-3 pb-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    connected ? "bg-[#009b77]" : "bg-[#b7bdc0]"
                  }`}
                />

                <span className="whitespace-nowrap text-[10px] font-bold uppercase tracking-[0.16em] text-[#657078]">
                  {connected ? "System Online" : "System Offline"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* DASHBOARD */}
      <section className="mx-auto max-w-[1600px] px-6 py-10 md:px-10 lg:px-16">
        <div className="grid grid-cols-1 gap-7 lg:grid-cols-[42%_minmax(0,1fr)]">
          {/* ROBOT STATUS */}
          <div className="border border-[#dfe3e1] bg-white">
            <div className="flex items-center justify-between border-b border-[#e5e8e6] px-7 py-6">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
                  Robot Status
                </p>

                <p className="mt-2 text-[9px] text-[#9aa2a6]">
                  Unitree G1
                </p>
              </div>

              <span
                className={`h-2 w-2 rounded-full ${
                  connected ? "bg-[#009b77]" : "bg-[#b7bdc0]"
                }`}
              />
            </div>

            <div className="px-7 py-7">
              {/* CONNECTION */}
              <div className="flex items-center justify-between border-b border-[#eceeed] py-4">
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8b959a]">
                  Connection
                </span>

                <span className="text-[11px] font-semibold text-[#505a60]">
                  {connected ? "Connected" : "Offline"}
                </span>
              </div>

              {/* MODE */}
              <div className="flex items-center justify-between border-b border-[#eceeed] py-4">
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8b959a]">
                  Operating Mode
                </span>

                <span className="text-[11px] font-semibold text-[#505a60]">
                  {mode}
                </span>
              </div>

              {/* MODEL */}
              <div className="flex items-center justify-between border-b border-[#eceeed] py-4">
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8b959a]">
                  Robot Model
                </span>

                <span className="text-[11px] font-semibold text-[#505a60]">
                  G1 29-DOF
                </span>
              </div>

              {/* LOCATION */}
              <div className="flex items-center justify-between border-b border-[#eceeed] py-4">
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8b959a]">
                  Location
                </span>

                <span className="text-[11px] font-semibold text-[#505a60]">
                  {robotStatus?.current_location || "Not available"}
                </span>
              </div>

              {/* BATTERY */}
              <div className="flex items-center justify-between py-4">
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8b959a]">
                  Battery
                </span>

                <span className="text-[11px] font-semibold text-[#505a60]">
                  {robotStatus?.battery !== undefined
                    ? `${robotStatus.battery}%`
                    : "Not available"}
                </span>
              </div>
            </div>
          </div>

          {/* CURRENT TASK */}
          <div className="min-h-[430px] border border-[#dfe3e1] bg-white">
            <div className="flex items-center justify-between border-b border-[#e5e8e6] px-7 py-6">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
                  Current Task
                </p>

                <p className="mt-2 text-[9px] text-[#9aa2a6]">
                  Task Engine
                </p>
              </div>

              <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#9aa2a6]">
                {robotStatus?.current_action ? "Running" : "Idle"}
              </span>
            </div>

            <div className="flex min-h-[330px] items-center justify-center">
              {robotStatus?.current_action ? (
                <div className="text-center">
                  <div className="mx-auto mb-5 h-2.5 w-2.5 rounded-full bg-[#009b77]" />

                  <p className="text-[17px] font-semibold text-[#454f54]">
                    {robotStatus.current_action}
                  </p>

                  <p className="mt-2 text-[11px] text-[#8c969b]">
                    Robot task currently running.
                  </p>
                </div>
              ) : (
                <div className="text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-[#dce0de]">
                    <span className="h-2 w-2 rounded-full bg-[#b7bdc0]" />
                  </div>

                  <p className="mt-6 text-[16px] font-semibold text-[#505a60]">
                    No active task
                  </p>

                  <p className="mt-2 text-[11px] text-[#90999e]">
                    The task engine is currently idle.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* CAMERA EXPANDED VIEW */}
      {cameraFullscreen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Expanded G1 camera preview"
          onClick={() => setCameraFullscreen(false)}
        >
          <div
            className="w-full max-w-5xl overflow-hidden bg-white"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-[#e5e8e6] px-5 py-4">
              <div>
                <p className="text-[13px] font-bold text-[#2d3337]">
                  G1 Head Camera
                </p>
                <p className="mt-1 text-[10px] text-[#8b959a]">
                  {cameraOnline ? "Live Preview" : "Camera Offline"}
                </p>
              </div>

              <button
                type="button"
                onClick={() => setCameraFullscreen(false)}
                className="text-[13px] font-semibold text-[#505a60] hover:text-black"
              >
                Close ✕
              </button>
            </div>

            {cameraPreview}
          </div>
        </div>
      )}
    </div>
  );
}
