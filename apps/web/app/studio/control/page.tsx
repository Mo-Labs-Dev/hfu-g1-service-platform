"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Bot,
  CheckCircle2,
  Clock3,
  Download,
  Footprints,
  LockKeyhole,
  MapPin,
  Power,
  Radio,
  RefreshCw,
  RotateCcw,
  RotateCw,
  Save,
  ShieldCheck,
  Square,
} from "lucide-react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const STATUS_INTERVAL_MS = 3000;
const MAX_STATUS_AGE_MS = 15000;

type PhysicalStatus = {
  connected: boolean;
  source: string;
  fsm_id: number | null;
  locomotion_mode: boolean;
  motion_enabled: boolean;
  timestamp: string | null;
  error: string | null;
};

type MotionCommand =
  | "FORWARD"
  | "BACKWARD"
  | "TURN_LEFT"
  | "TURN_RIGHT"
  | "STOP";

type LogEntry = {
  id: number;
  action: string;
  result: string;
  timestamp: string;
};

type Snapshot = {
  id: number;
  name: string;
  fsm_id: number;
  fsm_name: string;
  source: string;
  robot_timestamp: string;
  recorded_at: string;
};

type MotionButtonProps = {
  label: string;
  command: MotionCommand;
  icon: React.ReactNode;
  onCommand: (command: MotionCommand) => void;
  stop?: boolean;
};

const FSM_NAMES: Record<number, string> = {
  0: "Initial / Idle",
  1: "Damp Mode",
  3: "Sit Mode",
  4: "Stand Mode",
  500: "Locomotion Mode",
};

const MODES = [
  {
    id: 1,
    name: "Damp Mode",
    description: "Joint damping mode",
    icon: Power,
  },
  {
    id: 4,
    name: "Stand Mode",
    description: "Standing posture",
    icon: Bot,
  },
  {
    id: 500,
    name: "Locomotion Mode",
    description: "Walking controller",
    icon: Footprints,
  },
  {
    id: 3,
    name: "Sit Mode",
    description: "Sitting posture",
    icon: ArrowDown,
  },
];

function getFsmName(value: number | null): string {
  if (value === null) {
    return "Unknown";
  }

  return FSM_NAMES[value] ?? `FSM ${value}`;
}

function MotionButton({
  label,
  command,
  icon,
  onCommand,
  stop = false,
}: MotionButtonProps) {
  return (
    <button
      type="button"
      onClick={() => onCommand(command)}
      className={`flex min-h-20 flex-col items-center justify-center gap-2 rounded-xl border px-3 py-3 text-sm font-semibold transition active:scale-[0.98] ${
        stop
          ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
          : "border-[#d8dfda] bg-white text-[#34413b] hover:border-[#00866a] hover:bg-[#eef7f3]"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

export default function RobotControlPage() {
  const [status, setStatus] = useState<PhysicalStatus | null>(
    null
  );

  const [statusError, setStatusError] = useState<string | null>(
    null
  );

  const [lastUpdate, setLastUpdate] = useState<string | null>(
    null
  );

  const [refreshing, setRefreshing] = useState(false);

  const [logs, setLogs] = useState<LogEntry[]>([]);

  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);

  const [lastCommand, setLastCommand] = useState("None");

  const [simulatedSteps, setSimulatedSteps] = useState(0);

  const [simulatedHeading, setSimulatedHeading] = useState(0);

  const requestInProgress = useRef(false);
  const mounted = useRef(true);
  const nextId = useRef(1);

  const addLog = useCallback(
    (action: string, result: string) => {
      const entry: LogEntry = {
        id: nextId.current++,
        action,
        result,
        timestamp: new Date().toISOString(),
      };

      setLogs((previous) =>
        [entry, ...previous].slice(0, 30)
      );
    },
    []
  );

  const refreshStatus = useCallback(async () => {
    if (requestInProgress.current) {
      return;
    }

    requestInProgress.current = true;
    setRefreshing(true);

    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/status`,
        {
          cache: "no-store",
          signal: AbortSignal.timeout(6000),
        }
      );

      if (!response.ok) {
        throw new Error(
          `Robot status request failed (${response.status})`
        );
      }

      const result: PhysicalStatus =
        await response.json();

      if (!mounted.current) {
        return;
      }

      setStatus(result);

      if (
        !result.connected ||
        result.source !== "physical_g1" ||
        result.fsm_id === null
      ) {
        setStatusError(
          result.error || "Physical robot unavailable"
        );
        setLastUpdate(null);
        return;
      }

      const timestamp = result.timestamp
        ? new Date(result.timestamp)
        : null;

      if (
        !timestamp ||
        !Number.isFinite(timestamp.getTime()) ||
        Math.abs(Date.now() - timestamp.getTime()) >
          MAX_STATUS_AGE_MS
      ) {
        setStatusError("Robot feedback is stale");
        setLastUpdate(null);
        return;
      }

      setStatusError(null);
      setLastUpdate(timestamp.toLocaleTimeString());
    } catch (error) {
      if (mounted.current) {
        setStatus(null);
        setLastUpdate(null);

        setStatusError(
          error instanceof Error
            ? error.message
            : "Unable to contact robot status API"
        );
      }
    } finally {
      requestInProgress.current = false;

      if (mounted.current) {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;

    void refreshStatus();

    const interval = window.setInterval(() => {
      void refreshStatus();
    }, STATUS_INTERVAL_MS);

    return () => {
      mounted.current = false;
      window.clearInterval(interval);
    };
  }, [refreshStatus]);

  const timestampMs = status?.timestamp
    ? new Date(status.timestamp).getTime()
    : NaN;

  const freshTimestamp =
    Number.isFinite(timestampMs) &&
    Math.abs(Date.now() - timestampMs) <=
      MAX_STATUS_AGE_MS;

  const live =
    status?.connected === true &&
    status.source === "physical_g1" &&
    status.fsm_id !== null &&
    freshTimestamp &&
    statusError === null;

  const currentFsm = live
    ? status?.fsm_id ?? null
    : null;

  function simulateMovement(command: MotionCommand) {
    setLastCommand(command);

    if (command === "FORWARD") {
      setSimulatedSteps((previous) => previous + 1);
    }

    if (command === "BACKWARD") {
      setSimulatedSteps((previous) => previous - 1);
    }

    if (command === "TURN_LEFT") {
      setSimulatedHeading((previous) => previous - 15);
    }

    if (command === "TURN_RIGHT") {
      setSimulatedHeading((previous) => previous + 15);
    }

    addLog(
      command,
      "Simulated only. No physical robot command issued."
    );
  }

  function recordSnapshot() {
    if (
      !live ||
      currentFsm === null ||
      !status?.timestamp
    ) {
      return;
    }

    const now = new Date();

    const snapshot: Snapshot = {
      id: nextId.current++,
      name: `Robot State ${snapshots.length + 1}`,
      fsm_id: currentFsm,
      fsm_name: getFsmName(currentFsm),
      source: "physical_g1",
      robot_timestamp: status.timestamp,
      recorded_at: now.toISOString(),
    };

    setSnapshots((previous) => [
      snapshot,
      ...previous,
    ]);

    addLog(
      "RECORD STATE",
      `Recorded physical FSM ${currentFsm}`
    );
  }

  function exportSnapshots() {
    if (snapshots.length === 0) {
      return;
    }

    const data = {
      format: "g1-robot-state-recording",
      version: 1,
      note:
        "FSM and timestamps only. No measured XYZ coordinates, orientation, or joint positions are included.",
      snapshots,
    };

    const blob = new Blob(
      [JSON.stringify(data, null, 2)],
      {
        type: "application/json",
      }
    );

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");

    anchor.href = url;
    anchor.download = `g1-robot-state-${Date.now()}.json`;

    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();

    window.setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  return (
    <main className="min-h-screen bg-[#f5f6f5] px-6 py-8 text-[#292f33] lg:px-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <header>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#7b8687]">
            G1 Studio / Robot Operations
          </p>

          <h1 className="mt-2 text-3xl font-bold">
            Robot Control
          </h1>

          <p className="mt-2 text-sm text-[#657078]">
            Live physical robot monitoring, operating modes,
            simulated walking and robot-state recording.
          </p>
        </header>

        <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[#d8dcda] bg-white p-5">
          <div className="flex items-center gap-3">
            <Radio
              className={`h-6 w-6 ${
                live
                  ? "text-[#00866a]"
                  : "text-amber-600"
              }`}
            />

            <div>
              <p className="font-semibold">
                Physical G1 Connection
              </p>

              <p className="mt-1 text-sm text-[#738080]">
                {live
                  ? `Live Unitree SDK status · Updated ${lastUpdate}`
                  : statusError ||
                    "Waiting for physical robot status"}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => void refreshStatus()}
            disabled={refreshing}
            className="flex items-center gap-2 rounded-lg border border-[#d8dcda] px-4 py-2 text-sm font-semibold hover:bg-[#f5f7f6] disabled:opacity-50"
          >
            <RefreshCw
              className={`h-4 w-4 ${
                refreshing ? "animate-spin" : ""
              }`}
            />
            Refresh Status
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-[#d8dcda] bg-white p-5">
            <div className="flex items-center gap-2 text-[#738080]">
              <Bot className="h-5 w-5" />
              <span className="text-sm">
                Robot Connection
              </span>
            </div>

            <p className="mt-3 text-xl font-bold">
              {live ? "Connected" : "Unavailable"}
            </p>

            <p className="mt-1 text-xs text-[#738080]">
              {live
                ? "Physical Unitree G1"
                : "No fresh physical feedback"}
            </p>
          </div>

          <div className="rounded-xl border border-[#d8dcda] bg-white p-5">
            <div className="flex items-center gap-2 text-[#738080]">
              <Activity className="h-5 w-5" />
              <span className="text-sm">
                Current FSM
              </span>
            </div>

            <p className="mt-3 text-2xl font-bold">
              {currentFsm ?? "—"}
            </p>

            <p className="mt-1 text-xs text-[#738080]">
              {getFsmName(currentFsm)}
            </p>
          </div>

          <div className="rounded-xl border border-[#d8dcda] bg-white p-5">
            <div className="flex items-center gap-2 text-[#738080]">
              <ShieldCheck className="h-5 w-5" />
              <span className="text-sm">
                Physical Motion Access
              </span>
            </div>

            <p className="mt-3 text-xl font-bold text-amber-700">
              Locked
            </p>

            <p className="mt-1 text-xs text-[#738080]">
              Read-only monitoring mode
            </p>
          </div>
        </div>

        <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
          <div className="space-y-5">
            <section className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <div className="flex items-center gap-3">
                <Power className="h-6 w-6 text-[#00866a]" />

                <div>
                  <h2 className="text-xl font-bold">
                    Robot Operating Modes
                  </h2>

                  <p className="mt-1 text-sm text-[#738080]">
                    Actual physical FSM identification
                  </p>
                </div>
              </div>

              <div className="mt-6 grid gap-3 sm:grid-cols-2">
                {MODES.map((mode) => {
                  const Icon = mode.icon;
                  const active =
                    live && currentFsm === mode.id;

                  return (
                    <div
                      key={mode.id}
                      className={`rounded-xl border p-4 ${
                        active
                          ? "border-[#00866a] bg-[#eef8f3]"
                          : "border-[#dfe5e1] bg-[#fafbfa]"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <Icon
                          className={`h-6 w-6 ${
                            active
                              ? "text-[#00866a]"
                              : "text-[#738080]"
                          }`}
                        />

                        {active && (
                          <CheckCircle2 className="h-5 w-5 text-[#00866a]" />
                        )}
                      </div>

                      <p className="mt-4 font-semibold">
                        {mode.name}
                      </p>

                      <p className="mt-1 text-xs text-[#738080]">
                        FSM {mode.id} · {mode.description}
                      </p>

                      <button
                        type="button"
                        disabled
                        className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-[#d8dcda] bg-white px-3 py-2 text-xs font-semibold text-[#738080] opacity-70"
                      >
                        <LockKeyhole className="h-3.5 w-3.5" />
                        {active
                          ? "Current Mode"
                          : "Physical Control Locked"}
                      </button>
                    </div>
                  );
                })}
              </div>

              <p className="mt-4 text-xs leading-relaxed text-[#738080]">
                Damp, Stand, Sit and Locomotion transitions
                are safety-sensitive physical actions.
                This dashboard monitors the reported FSM
                but does not initiate mode changes.
              </p>
            </section>

            <section className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <div className="flex items-center gap-3">
                <Footprints className="h-6 w-6 text-[#00866a]" />

                <div>
                  <h2 className="text-xl font-bold">
                    Walking Controls
                  </h2>

                  <p className="mt-1 text-sm text-[#738080]">
                    Interactive simulation · No physical movement
                  </p>
                </div>
              </div>

              <div className="mx-auto mt-8 grid max-w-sm grid-cols-3 gap-3">
                <div />

                <MotionButton
                  label="Forward"
                  command="FORWARD"
                  icon={<ArrowUp className="h-6 w-6" />}
                  onCommand={simulateMovement}
                />

                <div />

                <MotionButton
                  label="Turn Left"
                  command="TURN_LEFT"
                  icon={<RotateCcw className="h-6 w-6" />}
                  onCommand={simulateMovement}
                />

                <MotionButton
                  label="Sim Stop"
                  command="STOP"
                  icon={<Square className="h-6 w-6" />}
                  onCommand={simulateMovement}
                  stop
                />

                <MotionButton
                  label="Turn Right"
                  command="TURN_RIGHT"
                  icon={<RotateCw className="h-6 w-6" />}
                  onCommand={simulateMovement}
                />

                <div />

                <MotionButton
                  label="Backward"
                  command="BACKWARD"
                  icon={<ArrowDown className="h-6 w-6" />}
                  onCommand={simulateMovement}
                />

                <div />
              </div>

              <div className="mt-7 flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
                <AlertTriangle className="h-5 w-5 shrink-0 text-amber-700" />

                <p className="text-sm leading-relaxed text-amber-900">
                  Walking buttons operate only in the
                  browser simulation. The Sim Stop button
                  does not stop the physical G1 and is not
                  an emergency stop.
                </p>
              </div>
            </section>
          </div>

          <aside className="space-y-5">
            <section className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <div className="flex items-center gap-2">
                <MapPin className="h-5 w-5 text-[#00866a]" />

                <h2 className="text-lg font-bold">
                  Record Robot State
                </h2>
              </div>

              <p className="mt-3 text-sm leading-relaxed text-[#738080]">
                Save the live robot FSM and observation
                timestamp for your experiment log.
              </p>

              <button
                type="button"
                disabled={!live}
                onClick={recordSnapshot}
                className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-[#00866a] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#007457] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Save className="h-4 w-4" />
                Record State
              </button>

              <button
                type="button"
                disabled={snapshots.length === 0}
                onClick={exportSnapshots}
                className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-[#d8dcda] px-4 py-3 text-sm font-medium transition hover:bg-[#f5f7f6] disabled:opacity-40"
              >
                <Download className="h-4 w-4" />
                Export JSON
              </button>

              <div className="mt-4 space-y-2">
                {snapshots.length === 0 ? (
                  <p className="text-xs text-[#83908c]">
                    No robot states recorded yet.
                  </p>
                ) : (
                  snapshots.map((item) => (
                    <div
                      key={item.id}
                      className="rounded-lg border border-[#e3e8e5] p-3"
                    >
                      <p className="text-sm font-semibold">
                        {item.name}
                      </p>

                      <p className="mt-1 text-xs text-[#738080]">
                        FSM {item.fsm_id} ·{" "}
                        {new Date(
                          item.recorded_at
                        ).toLocaleTimeString()}
                      </p>
                    </div>
                  ))
                )}
              </div>

              <p className="mt-4 text-xs leading-relaxed text-[#83908c]">
                Records contain FSM and timestamps, not
                robot XYZ position or joint angles.
                Data stays in browser memory until exported.
              </p>
            </section>

            <section className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <h2 className="text-lg font-bold">
                Simulation State
              </h2>

              <div className="mt-5 space-y-4 text-sm">
                <div className="flex justify-between gap-2">
                  <span className="text-[#738080]">
                    Last Command
                  </span>

                  <span className="font-semibold">
                    {lastCommand}
                  </span>
                </div>

                <div className="flex justify-between gap-2">
                  <span className="text-[#738080]">
                    Simulated Steps
                  </span>

                  <span className="font-semibold">
                    {simulatedSteps}
                  </span>
                </div>

                <div className="flex justify-between gap-2">
                  <span className="text-[#738080]">
                    Simulated Heading
                  </span>

                  <span className="font-semibold">
                    {simulatedHeading}°
                  </span>
                </div>
              </div>

              <p className="mt-4 text-xs text-[#83908c]">
                These values are simulation placeholders,
                not measured physical movement.
              </p>
            </section>

            <section className="rounded-xl border border-[#d8dcda] bg-white p-6">
              <h2 className="flex items-center gap-2 text-lg font-bold">
                <Clock3 className="h-5 w-5 text-[#00866a]" />
                Command History
              </h2>

              {logs.length === 0 ? (
                <p className="mt-4 text-sm text-[#738080]">
                  No commands recorded yet.
                </p>
              ) : (
                <div className="mt-4 max-h-72 space-y-3 overflow-y-auto">
                  {logs.map((entry) => (
                    <div
                      key={entry.id}
                      className="rounded-lg border border-[#e3e8e5] p-3"
                    >
                      <div className="flex justify-between gap-2">
                        <span className="text-sm font-semibold">
                          {entry.action}
                        </span>

                        <span className="text-xs text-[#83908c]">
                          {new Date(
                            entry.timestamp
                          ).toLocaleTimeString()}
                        </span>
                      </div>

                      <p className="mt-1 text-xs text-[#738080]">
                        {entry.result}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </aside>
        </div>

        <p className="text-center text-xs text-[#83908c]">
          HFU IPSE · Unitree G1 Research Platform ·
          Read-only physical monitoring
        </p>
      </div>
    </main>
  );
}