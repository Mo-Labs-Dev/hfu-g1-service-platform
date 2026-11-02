"use client";

import { useCallback, useEffect, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type MotionStatus = {
  connected?: boolean;
  fsm_id?: number;
  locomotion_mode?: boolean;
  armed?: boolean;
  physical_motion_enabled?: boolean;
  fault_latched?: boolean;
  watchdog_triggered?: boolean;
  stop_verified?: boolean;
  velocity?: number[];
  feedback?: {
    feedback_fresh?: boolean;
    measured_velocity?: number[] | null;
  };
};

type Direction = "forward" | "backward" | "left" | "right";

export default function ControlPage() {
  const [status, setStatus] = useState<MotionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [selectedDirection, setSelectedDirection] =
    useState<Direction | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/physical-motion/status`,
        { cache: "no-store" }
      );

      if (!response.ok) {
        throw new Error(`Status request failed: ${response.status}`);
      }

      const data: MotionStatus = await response.json();
      setStatus(data);
      setError("");
    } catch (err) {
      setStatus(null);
      setError(
        err instanceof Error ? err.message : "Unable to reach robot API"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshStatus();

    const interval = window.setInterval(() => {
      void refreshStatus();
    }, 1000);

    return () => window.clearInterval(interval);
  }, [refreshStatus]);

  const requestStop = async () => {
    if (busy) return;

    setBusy(true);
    setMessage("");
    setError("");
    setSelectedDirection(null);

    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/physical-motion/stop`,
        { method: "POST" }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "Stop request failed");
      }

      setMessage(
        "Zero-velocity stop request acknowledged. Physical stopping is not verified."
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Stop request failed"
      );
    } finally {
      setBusy(false);
      void refreshStatus();
    }
  };

  const chooseDirection = (direction: Direction) => {
    setSelectedDirection(direction);
    setMessage(
      `${direction.toUpperCase()} selected. Physical velocity output is not enabled yet. No movement command was sent.`
    );
  };

  const buttonStyle: React.CSSProperties = {
    padding: "14px 20px",
    borderRadius: 12,
    border: "1px solid #475569",
    background: "#1e293b",
    color: "#f8fafc",
    cursor: "pointer",
    fontWeight: 600,
    minWidth: 120,
  };

  const available = Boolean(
    status?.connected &&
      status?.fsm_id === 500 &&
      status?.feedback?.feedback_fresh
  );

  return (
    <main
      style={{
        padding: 32,
        maxWidth: 1100,
        margin: "0 auto",
        color: "#e2e8f0",
      }}
    >
      <h1 style={{ fontSize: 30, fontWeight: 700 }}>
        G1 Walking Control
      </h1>

      <p style={{ marginTop: 8, color: "#94a3b8" }}>
        Physical Unitree G1 EDU — G1 Studio
      </p>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 16,
          marginTop: 28,
        }}
      >
        <StatusCard
          label="Robot Connection"
          value={
            loading
              ? "Loading"
              : status?.connected
                ? "Connected"
                : "Disconnected"
          }
        />
        <StatusCard
          label="FSM Mode"
          value={status?.fsm_id?.toString() ?? "Unknown"}
        />
        <StatusCard
          label="LowState"
          value={
            status?.feedback?.feedback_fresh
              ? "Fresh"
              : "Unavailable"
          }
        />
        <StatusCard
          label="Motion Controller"
          value={status?.armed ? "Armed" : "Disarmed"}
        />
      </section>

      <section
        style={{
          marginTop: 30,
          padding: 24,
          borderRadius: 16,
          background: "#0f172a",
          border: "1px solid #334155",
        }}
      >
        <h2 style={{ fontSize: 22, fontWeight: 700 }}>
          Walking Controls
        </h2>

        <p style={{ color: "#94a3b8", marginTop: 8 }}>
          Direction selection is currently preview-only.
          It does not send nonzero physical velocity commands.
        </p>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 14,
            marginTop: 28,
          }}
        >
          <button
            style={buttonStyle}
            onClick={() => chooseDirection("forward")}
          >
            ↑ Forward
          </button>

          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", justifyContent: "center" }}>
            <button
              style={buttonStyle}
              onClick={() => chooseDirection("left")}
            >
              ↶ Turn Left
            </button>

            <button
              style={{
                ...buttonStyle,
                background: "#b91c1c",
                borderColor: "#ef4444",
              }}
              onClick={() => void requestStop()}
              disabled={busy}
            >
              {busy ? "Stopping..." : "■ STOP"}
            </button>

            <button
              style={buttonStyle}
              onClick={() => chooseDirection("right")}
            >
              ↷ Turn Right
            </button>
          </div>

          <button
            style={buttonStyle}
            onClick={() => chooseDirection("backward")}
          >
            ↓ Backward
          </button>
        </div>

        {selectedDirection && (
          <p style={{ marginTop: 18, textAlign: "center" }}>
            Selected: <strong>{selectedDirection}</strong>
          </p>
        )}

        <p
          style={{
            marginTop: 22,
            color: available ? "#86efac" : "#fbbf24",
            textAlign: "center",
          }}
        >
          {available
            ? "Robot feedback and FSM ready — physical velocity commands remain disabled."
            : "Robot is not ready for physical motion."}
        </p>
      </section>

      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 20, fontWeight: 600 }}>
          Safety & Motion Status
        </h2>

        <div style={{ marginTop: 12, lineHeight: 2 }}>
          <div>
            Physical velocity output:{" "}
            <strong>
              {status?.physical_motion_enabled ? "Enabled" : "Disabled"}
            </strong>
          </div>
          <div>
            Fault latched:{" "}
            <strong>{status?.fault_latched ? "Yes" : "No"}</strong>
          </div>
          <div>
            Watchdog triggered:{" "}
            <strong>{status?.watchdog_triggered ? "Yes" : "No"}</strong>
          </div>
          <div>
            Physical stop verified:{" "}
            <strong>{status?.stop_verified ? "Yes" : "No"}</strong>
          </div>
          <div>
            Requested velocity:{" "}
            <strong>
              {status?.velocity?.join(", ") ?? "Unavailable"}
            </strong>
          </div>
        </div>
      </section>

      {message && (
        <p style={{ marginTop: 20, color: "#86efac" }}>
          {message}
        </p>
      )}

      {error && (
        <p style={{ marginTop: 20, color: "#fca5a5" }}>
          {error}
        </p>
      )}
    </main>
  );
}

function StatusCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div
      style={{
        padding: 18,
        borderRadius: 12,
        background: "#0f172a",
        border: "1px solid #334155",
      }}
    >
      <p style={{ color: "#94a3b8", fontSize: 13 }}>
        {label}
      </p>

      <p
        style={{
          fontSize: 21,
          fontWeight: 700,
          marginTop: 8,
        }}
      >
        {value}
      </p>
    </div>
  );
}
