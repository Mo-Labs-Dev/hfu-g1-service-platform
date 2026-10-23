"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";

import type {
  GuidanceStatus,
  GuidanceStep,
} from "@/types/navigation";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

const ENDPOINT = `${API_URL}/api/visitor-guidance`;

async function readResponse(
  response: Response
): Promise<GuidanceStatus> {
  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Guidance request failed."
    );
  }

  return data as GuidanceStatus;
}

function stepStatusLabel(
  status: GuidanceStep["status"]
): string {
  switch (status) {
    case "running":
      return "In progress";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Pending";
  }
}

export default function NavigationPanel() {
  const [guidance, setGuidance] =
    useState<GuidanceStatus | null>(null);

  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] =
    useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(
        `${ENDPOINT}/status`,
        { cache: "no-store" }
      );

      const data = await readResponse(response);

      setGuidance(data);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    void refresh();

    const interval = window.setInterval(() => {
      void refresh();
    }, 1000);

    return () => {
      window.clearInterval(interval);
    };
  }, [refresh]);

  async function startGuidance() {
    setBusy(true);
    setError(null);

    try {
      const response = await fetch(
        `${ENDPOINT}/start`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            destination: "coffee_machine",
          }),
        }
      );

      const data = await readResponse(response);

      setGuidance(data);
      setOnline(true);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to start guidance."
      );

      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function cancelGuidance() {
    setBusy(true);
    setError(null);

    try {
      const response = await fetch(
        `${ENDPOINT}/cancel`,
        { method: "POST" }
      );

      const data = await readResponse(response);

      setGuidance(data);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to cancel guidance."
      );

      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const active = guidance?.active ?? false;

  const progress = Math.min(
    100,
    Math.max(0, guidance?.progress ?? 0)
  );

  const state = guidance?.state ?? "idle";

  const stateLabel = state.replaceAll("_", " ");

  const steps = guidance?.steps ?? [];

  return (
    <div className="space-y-7">
      <section className="border border-[#dfe3e1] bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e5e8e6] px-7 py-5">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
              Destination
            </p>

            <h2 className="mt-2 text-[20px] font-bold text-[#2d3337]">
              Coffee Machine
            </h2>
          </div>

          <span className="border border-[#c8e6dc] bg-[#eef8f4] px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-[#008567]">
            Hybrid Demo
          </span>
        </div>

        <div className="px-7 py-7">
          <p className="text-[13px] leading-6 text-[#707b81]">
            Execute the saved Coffee Machine workflow
            using the G1 Studio Task Engine. The
            physical G1 speaks the announcements,
            while navigation remains simulated.
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void startGuidance()}
              disabled={!online || active || busy}
              className="bg-[#009b77] px-6 py-3 text-[12px] font-bold text-white transition-colors hover:bg-[#008567] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy
                ? "Please wait..."
                : active
                  ? "Guidance Running"
                  : "Start Guidance"}
            </button>

            <button
              type="button"
              onClick={() => void cancelGuidance()}
              disabled={!online || !active || busy}
              className="border border-[#d8ddda] bg-white px-6 py-3 text-[12px] font-bold text-[#505a60] transition-colors hover:bg-[#f4f6f5] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Cancel Guidance
            </button>
          </div>

          {error && (
            <div
              role="alert"
              className="mt-5 border border-red-200 bg-red-50 px-4 py-3 text-[12px] text-red-700"
            >
              {error}
            </div>
          )}
        </div>
      </section>

      <section className="border border-[#dfe3e1] bg-white">
        <div className="flex items-center justify-between border-b border-[#e5e8e6] px-7 py-5">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
              Workflow Execution
            </p>

            <p className="mt-2 text-[11px] text-[#9aa2a6]">
              Live Task Engine progress
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                online
                  ? "bg-[#009b77]"
                  : "bg-red-400"
              }`}
            />

            <span className="text-[10px] font-bold uppercase text-[#657078]">
              {online ? "Connected" : "Offline"}
            </span>
          </div>
        </div>

        <div className="px-7 py-7">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8b959a]">
                Current State
              </p>

              <p className="mt-2 text-[20px] font-semibold capitalize text-[#2d3337]">
                {stateLabel}
              </p>
            </div>

            <p className="text-[28px] font-bold tabular-nums text-[#009b77]">
              {progress}%
            </p>
          </div>

          <div
            className="mt-6 h-2 w-full overflow-hidden bg-[#e9eeeb]"
            role="progressbar"
            aria-label="Workflow execution progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
          >
            <div
              className="h-full bg-[#009b77] transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>

          <p
            className="mt-5 text-[13px] text-[#657078]"
            aria-live="polite"
          >
            {online
              ? guidance?.message ??
                "Waiting for workflow status."
              : "Unable to connect to the backend."}
          </p>

          <div className="mt-8 grid gap-3 md:grid-cols-3">
            {steps.map((step, index) => {
              const completed =
                step.status === "completed";

              const running =
                step.status === "running";

              const failed =
                step.status === "failed";

              return (
                <div
                  key={step.id}
                  className={`border px-4 py-4 ${
                    completed
                      ? "border-[#b8ded1] bg-[#f1f9f5]"
                      : running
                        ? "border-[#9bc9ba] bg-[#f4faf7]"
                        : failed
                          ? "border-red-200 bg-red-50"
                          : "border-[#e5e8e6] bg-[#fafbfa]"
                  }`}
                >
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[10px] font-bold text-[#8b959a]">
                      STEP {index + 1}
                    </span>

                    <span
                      className={`h-2 w-2 rounded-full ${
                        completed
                          ? "bg-[#009b77]"
                          : running
                            ? "bg-amber-500"
                            : failed
                              ? "bg-red-500"
                              : "bg-[#c6ccca]"
                      }`}
                    />
                  </div>

                  <p className="text-[12px] font-semibold text-[#2d3337]">
                    {step.name}
                  </p>

                  <p className="mt-2 text-[10px] uppercase tracking-wide text-[#8b959a]">
                    {step.action}
                  </p>

                  <p className="mt-3 text-[11px] font-medium text-[#657078]">
                    {stepStatusLabel(step.status)}
                  </p>
                </div>
              );
            })}
          </div>

          {steps.length === 0 && (
            <p className="mt-7 text-[12px] text-[#9aa2a6]">
              Start guidance to view workflow steps.
            </p>
          )}

          {guidance?.session_id && (
            <div className="mt-7 border-t border-[#eceeed] pt-5">
              <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8b959a]">
                Execution ID
              </p>

              <p className="mt-2 break-all font-mono text-[11px] text-[#657078]">
                {guidance.session_id}
              </p>
            </div>
          )}

          <p className="mt-6 text-[11px] leading-5 text-[#9aa2a6]">
            Progress is calculated from completed
            workflow steps. Navigation is simulated;
            the percentage does not represent measured
            physical movement. Speech completion is
            based on bridge request acceptance.
          </p>
        </div>
      </section>
    </div>
  );
}