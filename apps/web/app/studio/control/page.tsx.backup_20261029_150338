"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  Activity,
  ArrowDown,
  ArrowUp,
  Bot,
  Camera,
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

import LidarPreview from "@/components/robot/LidarPreview";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const CAMERA_URL =
  process.env.NEXT_PUBLIC_G1_CAMERA_URL || "";

const STATUS_INTERVAL_MS = 3000;
const MAX_STATUS_AGE_MS = 15000;

type PhysicalStatus = {
  connected: boolean;
  source: string;
  fsm_id: number | null;
  locomotion_mode: boolean;
  motion_enabled: boolean;
  posture_control_available: boolean;
  locomotion_control_available: boolean;
  timestamp: string | null;
  error: string | null;
};

type PhysicalMotionBridgeStatus = {
  source?: string;
  connected?: boolean;
  fsm_id?: number | null;
  mode?: string;
  armed?: boolean;
  physical_motion_enabled?: boolean;
  velocity_commands_available?: boolean;
  fault_latched?: boolean;
  watchdog_triggered?: boolean;
  stop_verified?: boolean;
  velocity?: number[];
  feedback?: {
    feedback_fresh?: boolean;
    feedback_age_ms?: number | null;
    measured_velocity?: number[] | null;
    stop_verified_by_feedback?: boolean;
  };
};

type WalkingMode = "simulation" | "physical";

type ControlCapabilities = {
  posture_control_available: boolean;
  locomotion_control_available: boolean;
  supported_actions: string[];
  required_sequence: number[];
  physical_motion_enabled: boolean;
  message: string;
};

type PhysicalControlAction =
  | "damp"
  | "stand_up"
  | "start_locomotion";

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
    description: "Joint damping",
    icon: Power,
    action: "damp" as PhysicalControlAction,
    sourceFsm: 0,
    targetFsm: 1,
  },
  {
    id: 4,
    name: "Stand Mode",
    description: "Standing posture",
    icon: Bot,
    action: "stand_up" as PhysicalControlAction,
    sourceFsm: 1,
    targetFsm: 4,
  },
  {
    id: 500,
    name: "Locomotion",
    description: "Walking controller",
    icon: Footprints,
    action: "start_locomotion" as PhysicalControlAction,
    sourceFsm: 4,
    targetFsm: 500,
  },
  {
    id: 3,
    name: "Sit Mode",
    description: "Sitting posture",
    icon: ArrowDown,
    action: null,
    sourceFsm: null,
    targetFsm: 3,
  },
];

function getFsmName(value: number | null): string {
  if (value === null) {
    return "Unknown";
  }

  return FSM_NAMES[value] ?? `FSM ${value}`;
}

function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border border-[#dce4e3] bg-white p-5 shadow-sm ${className}`}
    >
      {children}
    </section>
  );
}

function MotionButton({
  label,
  icon,
  onPress,
  onRelease,
  disabled = false,
  stop = false,
}: {
  label: string;
  icon: ReactNode;
  onPress: () => void;
  onRelease: () => void;
  disabled?: boolean;
  stop?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        onPress();
      }}
      onPointerUp={onRelease}
      onPointerCancel={onRelease}
      onLostPointerCapture={onRelease}
      onKeyDown={(event) => {
        if (event.repeat) return;
        if (event.key === " " || event.key === "Enter") {
          event.preventDefault();
          onPress();
        }
      }}
      onKeyUp={(event) => {
        if (event.key === " " || event.key === "Enter") {
          event.preventDefault();
          onRelease();
        }
      }}
      className={`flex min-h-20 touch-none select-none flex-col items-center justify-center gap-2 rounded-xl border p-3 text-sm font-semibold transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 ${
        stop
          ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
          : "border-[#d8dfda] bg-white text-[#34413b] hover:bg-[#eef7f3]"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function CameraPreview() {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  const online =
    CAMERA_URL.length > 0 &&
    loaded &&
    !failed;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-[#d8dcda] bg-white">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div>
          <h3 className="font-semibold">
            G1 Camera
          </h3>

          <p className="text-xs text-[#738080]">
            Robot Vision · Live Preview
          </p>
        </div>

        <span
          className={`rounded-full px-2 py-1 text-xs font-semibold ${
            online
              ? "bg-emerald-50 text-emerald-700"
              : "bg-amber-50 text-amber-700"
          }`}
        >
          {online
            ? "Streaming"
            : "Offline"}
        </span>
      </div>

      <div className="relative flex h-[230px] items-center justify-center overflow-hidden bg-[#101c27]">
        {CAMERA_URL && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={CAMERA_URL}
            alt="G1 camera feed"
            className="absolute inset-0 h-full w-full object-contain"
            onLoad={() => {
              setLoaded(true);
              setFailed(false);
            }}
            onError={() => {
              setLoaded(false);
              setFailed(true);
            }}
          />
        )}

        {!online && (
          <div className="pointer-events-none relative z-10 flex flex-col items-center gap-3 bg-[#101c27]/90 px-6 py-4 text-center">
            <Camera className="h-9 w-9 text-[#96a9b5]" />

            <span className="text-sm font-medium text-white">
              Camera Feed Unavailable
            </span>

            <p className="max-w-xs text-xs text-[#aebdc6]">
              {CAMERA_URL
                ? "Unable to load the configured camera stream."
                : "Waiting for a real G1 camera stream configuration."}
            </p>
          </div>
        )}
      </div>

      <div className="px-4 py-3">
        <p className="text-xs text-[#738080]">
          {online
            ? "Camera media received"
            : "No verified G1 camera feed"}
        </p>
      </div>
    </div>
  );
}

export default function RobotControlPage() {
  const [status, setStatus] =
    useState<PhysicalStatus | null>(null);

  const [statusError, setStatusError] =
    useState<string | null>(null);

  const [capabilities, setCapabilities] =
    useState<ControlCapabilities | null>(null);

  const [capabilityError, setCapabilityError] =
    useState<string | null>(null);

  const [refreshing, setRefreshing] =
    useState(false);

  const [controlNotice, setControlNotice] = useState<string | null>(null);

  const [controlBusy, setControlBusy] =
    useState<PhysicalControlAction | null>(
      null
    );

  const [logs, setLogs] =
    useState<LogEntry[]>([]);

  const [snapshots, setSnapshots] =
    useState<Snapshot[]>([]);

  const [lastCommand, setLastCommand] =
    useState("None");

  const [walkingMode, setWalkingMode] = useState<WalkingMode>("physical");
  const [physicalMotionStatus, setPhysicalMotionStatus] =
    useState<PhysicalMotionBridgeStatus | null>(null);
  const [physicalMotionError, setPhysicalMotionError] = useState<string | null>(null);
  const [physicalStopBusy, setPhysicalStopBusy] = useState(false);
  const [physicalStopMessage, setPhysicalStopMessage] = useState<string | null>(null);
  const [walkingNotice, setWalkingNotice] = useState<string | null>(null);

  const [motionStatus, setMotionStatus] = useState<{
    mode: string;
    physical_motion_enabled: boolean;
    velocity: number[];
    moving: boolean;
  } | null>(null);
  const [motionError, setMotionError] = useState<string | null>(null);
  const [motionBusy, setMotionBusy] = useState(false);
  const motionTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const motionActive = useRef(false);
  const motionSending = useRef(false);
  const motionGeneration = useRef(0);

  const mounted = useRef(true);
  const busy = useRef(false);
  const nextId = useRef(1);

  const addLog = useCallback(
    (
      action: string,
      result: string
    ) => {
      const entry: LogEntry = {
        id: nextId.current++,
        action,
        result,
        timestamp:
          new Date().toISOString(),
      };

      setLogs((previous) =>
        [entry, ...previous].slice(0, 30)
      );
    },
    []
  );

  const refreshStatus =
    useCallback(async () => {
      if (busy.current) {
        return;
      }

      busy.current = true;
      setRefreshing(true);

      try {
        const response = await fetch(
          `${API_URL}/api/physical-robot/status`,
          {
            cache: "no-store",
            signal:
              AbortSignal.timeout(6000),
          }
        );

        if (!response.ok) {
          throw new Error(
            `Status HTTP ${response.status}`
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
          result.source !==
            "physical_g1" ||
          result.fsm_id === null
        ) {
          setStatusError(
            result.error ||
              "Physical robot unavailable"
          );

          return;
        }

        const timestamp =
          result.timestamp
            ? new Date(
                result.timestamp
              ).getTime()
            : NaN;

        const age = Math.abs(
          Date.now() - timestamp
        );

        if (
          !Number.isFinite(timestamp) ||
          age > MAX_STATUS_AGE_MS
        ) {
          setStatusError(
            "Robot feedback is stale"
          );

          return;
        }

        setStatusError(null);
      } catch (error) {
        if (mounted.current) {
          setStatus(null);

          setStatusError(
            error instanceof Error
              ? error.message
              : "Robot status API unavailable"
          );
        }
      } finally {
        busy.current = false;

        if (mounted.current) {
          setRefreshing(false);
        }
      }
    }, []);

  const refreshCapabilities =
    useCallback(async () => {
      try {
        const response = await fetch(
          `${API_URL}/api/physical-robot/control-capabilities`,
          {
            cache: "no-store",
            signal:
              AbortSignal.timeout(5000),
          }
        );

        if (!response.ok) {
          throw new Error(
            `Capabilities HTTP ${response.status}`
          );
        }

        const result: ControlCapabilities =
          await response.json();

        if (!mounted.current) {
          return;
        }

        setCapabilities(result);
        setCapabilityError(null);
      } catch (error) {
        if (mounted.current) {
          setCapabilities(null);

          setCapabilityError(
            error instanceof Error
              ? error.message
              : "Control capability request failed"
          );
        }
      }
    }, []);

  useEffect(() => {
    mounted.current = true;

    void refreshStatus();
    void refreshCapabilities();

    const statusTimer =
      window.setInterval(() => {
        void refreshStatus();
      }, STATUS_INTERVAL_MS);

    const capabilityTimer =
      window.setInterval(() => {
        void refreshCapabilities();
      }, 5000);

    return () => {
      mounted.current = false;

      window.clearInterval(
        statusTimer
      );

      window.clearInterval(
        capabilityTimer
      );
    };
  }, [
    refreshStatus,
    refreshCapabilities,
  ]);

  const live =
    status?.connected === true &&
    status.source === "physical_g1" &&
    status.fsm_id !== null &&
    statusError === null;

  const currentFsm =
    live ? status!.fsm_id : null;

  const postureControlAvailable =
    capabilities?.posture_control_available ===
    true;

  const locomotionControlAvailable =
    capabilities?.locomotion_control_available ===
    true;

  async function requestPhysicalControl(
    action: PhysicalControlAction
  ) {
    if (controlBusy !== null) {
      setControlNotice("Another FSM transition is still in progress.");
      return;
    }

    if (!live) {
      setControlNotice(statusError || "Robot feedback is unavailable or stale. Check the connection and refresh.");
      addLog(
        action.toUpperCase(),
        "Blocked: physical G1 is not online."
      );

      return;
    }

    const isLocomotion =
      action === "start_locomotion";

    const controlAvailable =
      isLocomotion
        ? locomotionControlAvailable
        : postureControlAvailable;

    if (!controlAvailable) {
      setControlNotice(capabilityError || capabilities?.message || "FastAPI has not authorized this FSM action. Check the backend configuration.");
      addLog(
        action.toUpperCase(),
        isLocomotion
          ? "Blocked: locomotion control is not armed."
          : "Blocked: physical posture control is not armed."
      );

      return;
    }

    const expectedSource =
      action === "damp"
        ? 0
        : action === "stand_up"
        ? 1
        : 4;

    const targetFsm =
      action === "damp"
        ? 1
        : action === "stand_up"
        ? 4
        : 500;

    if (currentFsm !== expectedSource) {
      setControlNotice(`This transition requires FSM ${expectedSource}; robot currently reports FSM ${currentFsm}. Use the appropriate next transition.`);
      addLog(
        action.toUpperCase(),
        `Blocked: expected FSM ${expectedSource}, current FSM is ${currentFsm}.`
      );

      return;
    }

    const actionName =
      action === "damp"
        ? "Damp Mode"
        : action === "stand_up"
        ? "Stand Up"
        : "Start Locomotion";

    const confirmed =
      window.confirm(
        [
          `Send "${actionName}" to the physical Unitree G1?`,
          "",
          `FSM ${expectedSource} → FSM ${targetFsm}`,
          "",
          isLocomotion
            ? "The robot will enter locomotion mode. Do not send walking commands until the robot is confirmed stable and ready."
            : "Make sure the robot and its surroundings are safe.",
        ].join("\n")
      );

    if (!confirmed) {
      addLog(
        actionName.toUpperCase(),
        "Cancelled by operator."
      );

      return;
    }

    setControlNotice(null);
    setControlBusy(action);

    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/posture`,
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/json",
          },
          body: JSON.stringify({
            action,
            confirmed: true,
          }),
          cache: "no-store",
          signal:
            AbortSignal.timeout(15000),
        }
      );

      const body =
        await response
          .json()
          .catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          body?.detail ||
            body?.error ||
            `Physical control request failed (${response.status})`
        );
      }

      const afterFsm =
        body?.after_fsm;

      addLog(
        actionName.toUpperCase(),
        afterFsm !== undefined
          ? `FSM transition confirmed: ${expectedSource} → ${afterFsm}.`
          : `${actionName} command accepted by physical robot backend.`
      );

      setControlNotice(`Command accepted. Checking robot feedback for FSM ${targetFsm}.`);
      await refreshStatus();
      await refreshCapabilities();
    } catch (error) {
      setControlNotice(error instanceof Error ? error.message : "FSM command failed.");
      addLog(
        actionName.toUpperCase(),
        error instanceof Error
          ? error.message
          : "Physical control command failed."
      );
    } finally {
      if (mounted.current) {
        setControlBusy(null);
      }
    }
  }

  const fetchMotionStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/motion/status`,
        { cache: "no-store", signal: AbortSignal.timeout(2500) }
      );
      if (!response.ok) throw new Error(`Motion simulator HTTP ${response.status}`);
      const data = await response.json();
      if (data.mode !== "simulation" || data.physical_motion_enabled !== false) {
        throw new Error("Motion simulator identity mismatch");
      }
      if (mounted.current) {
        setMotionStatus(data);
        setMotionError(null);
      }
    } catch (error) {
      if (mounted.current) {
        setMotionStatus(null);
        setMotionError(error instanceof Error ? error.message : "Simulator unavailable");
      }
    }
  }, []);

  const stopMotion = useCallback(async () => {
    motionActive.current = false;
    motionGeneration.current += 1;
    if (motionTimer.current !== null) {
      clearInterval(motionTimer.current);
      motionTimer.current = null;
    }
    setLastCommand("STOP");
    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/motion/stop`,
        { method: "POST", cache: "no-store", signal: AbortSignal.timeout(2500) }
      );
      if (!response.ok) throw new Error(`Stop HTTP ${response.status}`);
      setMotionBusy(false);
      void fetchMotionStatus();
    } catch (error) {
      setMotionError(error instanceof Error ? error.message : "Stop request failed");
      setMotionBusy(false);
      addLog("SIM STOP", "Stop request failed; simulator watchdog should expire commands.");
    }
  }, [addLog, fetchMotionStatus]);

  const startMotion = useCallback((command: Exclude<MotionCommand, "STOP">) => {
    if (motionActive.current || motionStatus === null || motionError !== null) return;

    const velocities: Record<Exclude<MotionCommand, "STOP">, [number, number, number]> = {
      FORWARD: [0.05, 0, 0],
      BACKWARD: [-0.05, 0, 0],
      TURN_LEFT: [0, 0, 0.10],
      TURN_RIGHT: [0, 0, -0.10],
    };
    const [vx, vy, omega] = velocities[command];
    motionActive.current = true;
    const generation = ++motionGeneration.current;
    setMotionBusy(true);
    setLastCommand(command);
    addLog(command, "Simulated motion requested");

    const send = async () => {
      if (!motionActive.current || generation !== motionGeneration.current || motionSending.current) return;
      motionSending.current = true;
      try {
        const response = await fetch(`${API_URL}/api/physical-robot/motion`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ vx, vy, omega }),
          cache: "no-store",
          signal: AbortSignal.timeout(1000),
        });
        if (!response.ok) throw new Error(`Motion HTTP ${response.status}`);
        const data = await response.json();
        if (data.physical_motion_enabled !== false || data.status !== "simulated") {
          throw new Error("Unexpected motion response");
        }
      } catch (error) {
        if (generation === motionGeneration.current) {
          setMotionError(error instanceof Error ? error.message : "Motion request failed");
          void stopMotion();
        }
      } finally {
        motionSending.current = false;
      }
    };

    void send();
    motionTimer.current = setInterval(() => void send(), 150);
  }, [motionStatus, motionError, addLog, stopMotion]);

  useEffect(() => {
    void fetchMotionStatus();
    const timer = window.setInterval(() => void fetchMotionStatus(), 600);
    const halt = () => {
      if (motionActive.current) void stopMotion();
    };
    const visibility = () => {
      if (document.hidden) halt();
    };
    window.addEventListener("blur", halt);
    window.addEventListener("pointerup", halt);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      clearInterval(timer);
      window.removeEventListener("blur", halt);
      window.removeEventListener("pointerup", halt);
      document.removeEventListener("visibilitychange", visibility);
      if (motionActive.current) void stopMotion();
    };
  }, [fetchMotionStatus, stopMotion]);

  const fetchPhysicalMotionStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/physical-motion/status`,
        { cache: "no-store", signal: AbortSignal.timeout(3000) }
      );
      if (!response.ok) {
        throw new Error(`Physical motion status HTTP ${response.status}`);
      }
      const data: PhysicalMotionBridgeStatus = await response.json();
      if (data.source !== "physical_g1") {
        throw new Error("Unexpected physical motion source");
      }
      if (mounted.current) {
        setPhysicalMotionStatus(data);
        setPhysicalMotionError(null);
      }
    } catch (error) {
      if (mounted.current) {
        setPhysicalMotionStatus(null);
        setPhysicalMotionError(
          error instanceof Error ? error.message : "Physical bridge unavailable"
        );
      }
    }
  }, []);

  useEffect(() => {
    if (walkingMode !== "physical") return;
    void fetchPhysicalMotionStatus();
    const timer = window.setInterval(() => {
      void fetchPhysicalMotionStatus();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [walkingMode, fetchPhysicalMotionStatus]);

  const requestPhysicalStop = useCallback(async () => {
    if (physicalStopBusy) return;
    setPhysicalStopBusy(true);
    setPhysicalStopMessage(null);
    try {
      const response = await fetch(
        `${API_URL}/api/physical-robot/physical-motion/stop`,
        { method: "POST", cache: "no-store", signal: AbortSignal.timeout(6000) }
      );
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = result.detail;
        throw new Error(typeof detail === "string" ? detail : `Stop HTTP ${response.status}`);
      }
      setPhysicalStopMessage(
        "Zero-velocity stop request sent. Physical stopping is NOT verified."
      );
      addLog("PHYSICAL STOP", "Bridge stop request returned; stopping not physically verified.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Stop request failed";
      setPhysicalStopMessage(`STOP REQUEST FAILED: ${message}`);
      addLog("PHYSICAL STOP FAILED", message);
    } finally {
      setPhysicalStopBusy(false);
      void fetchPhysicalMotionStatus();
    }
  }, [physicalStopBusy, addLog, fetchPhysicalMotionStatus]);

  function explainPhysicalWalking(direction: string) {
    const reason = physicalMotionError ||
      (!physicalMotionStatus?.connected ? "The physical bridge is not connected." :
       currentFsm !== 500 ? "The robot must first reach FSM 500." :
       !physicalMotionStatus?.physical_motion_enabled ? "The backend has not enabled physical velocity commands." :
       !physicalMotionStatus?.stop_verified ? "Independent physical stop verification is unavailable." :
       !physicalMotionStatus?.armed ? "The physical motion controller is disarmed." :
       "Physical movement has not been commissioned for this interface.");
    setWalkingNotice(`${direction}: ${reason} No movement command was sent.`);
    addLog(`PHYSICAL ${direction}`, reason);
  }

  function selectWalkingMode(next: WalkingMode) {
    if (next === walkingMode) return;
    if (motionActive.current) void stopMotion();
    setPhysicalStopMessage(null);
    setWalkingNotice(null);
    setWalkingMode(next);
    addLog("WALKING MODE", next === "physical" ? "Physical monitoring selected; movement locked." : "Simulation selected.");
  }

  function recordSnapshot() {
    if (
      !live ||
      currentFsm === null ||
      !status?.timestamp
    ) {
      return;
    }

    const snapshot: Snapshot = {
      id: nextId.current++,
      name: `Robot State ${
        snapshots.length + 1
      }`,
      fsm_id: currentFsm,
      fsm_name:
        getFsmName(currentFsm),
      source: "physical_g1",
      robot_timestamp:
        status.timestamp,
      recorded_at:
        new Date().toISOString(),
    };

    setSnapshots((previous) => [
      snapshot,
      ...previous,
    ]);

    addLog(
      "RECORD STATE",
      `Recorded FSM ${currentFsm}`
    );
  }

  function exportSnapshots() {
    if (snapshots.length === 0) {
      return;
    }

    const data = {
      format:
        "g1-robot-state-recording",
      version: 1,
      note:
        "FSM and timestamps only. No measured XYZ coordinates, orientation, or joint positions.",
      snapshots,
    };

    const blob = new Blob(
      [
        JSON.stringify(
          data,
          null,
          2
        ),
      ],
      {
        type: "application/json",
      }
    );

    const url =
      URL.createObjectURL(blob);

    const anchor =
      document.createElement("a");

    anchor.href = url;

    anchor.download =
      `g1-robot-state-${Date.now()}.json`;

    document.body.appendChild(
      anchor
    );

    anchor.click();

    anchor.remove();

    window.setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  return (
    <main className="min-h-screen bg-[#f5f7f8] px-4 py-6 text-[#263238] lg:px-8 2xl:px-10">
      <div className="mx-auto w-full max-w-none space-y-5">

        <header>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#7b8687]">
            G1 Studio / Robot Operations
          </p>

          <h1 className="mt-2 text-3xl font-bold">
            Robot Control
          </h1>

          <p className="mt-2 text-sm text-[#657078]">
            Live monitoring and robot operations
          </p>
        </header>

        <Panel>
          <div className="flex flex-wrap items-center justify-between gap-4">

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
                    ? `Updated · ${
                        status?.timestamp
                          ? new Date(
                              status.timestamp
                            ).toLocaleTimeString()
                          : "Updated"
                      }`
                    : statusError ||
                      "Waiting for physical G1 feedback"}
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => {
                void refreshStatus();
                void refreshCapabilities();
              }}
              disabled={refreshing}
              className="flex items-center gap-2 rounded-lg border border-[#d8dcda] px-4 py-2 text-sm font-semibold hover:bg-[#f5f7f6] disabled:opacity-50"
            >
              <RefreshCw
                className={`h-4 w-4 ${
                  refreshing
                    ? "animate-spin"
                    : ""
                }`}
              />

              Refresh Status
            </button>

          </div>
        </Panel>

        <div className="grid gap-4 md:grid-cols-3">

          <Panel>
            <div className="flex items-center gap-2 text-sm text-[#738080]">
              <Bot className="h-5 w-5" />
              Robot Connection
            </div>

            <p className="mt-3 text-xl font-bold">
              {live
                ? "Connected"
                : "Unavailable"}
            </p>

            <p className="mt-1 text-xs text-[#738080]">
              {live
                ? "Physical Unitree G1"
                : "No fresh physical feedback"}
            </p>
          </Panel>

          <Panel>
            <div className="flex items-center gap-2 text-sm text-[#738080]">
              <Activity className="h-5 w-5" />
              Current FSM
            </div>

            <p className="mt-3 text-2xl font-bold">
              {currentFsm ?? "—"}
            </p>

            <p className="mt-1 text-xs text-[#738080]">
              {getFsmName(currentFsm)}
            </p>
          </Panel>

          <Panel>
            <div className="flex items-center gap-2 text-sm text-[#738080]">
              <ShieldCheck className="h-5 w-5" />

              <span>
                Physical Control
              </span>
            </div>

            <div className="mt-3 flex gap-2">

              <span
                className={`rounded-full px-2 py-1 text-xs font-semibold ${
                  postureControlAvailable
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700"
                }`}
              >
                Posture:{" "}
                {postureControlAvailable
                  ? "Armed"
                  : "Locked"}
              </span>

              <span
                className={`rounded-full px-2 py-1 text-xs font-semibold ${
                  locomotionControlAvailable
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700"
                }`}
              >
                Locomotion:{" "}
                {locomotionControlAvailable
                  ? "Armed"
                  : "Locked"}
              </span>

            </div>

            <p className="mt-2 text-xs text-[#738080]">
              {capabilities?.message ||
                capabilityError ||
                "Checking physical control capability"}
            </p>
          </Panel>

        </div>

        <section>

          <div className="mb-3 flex items-center justify-between gap-3">

            <h2 className="text-xl font-bold">
              Live Robot Perception
            </h2>

            <span className="text-xs text-[#738080]">
              Camera + LiDAR
            </span>

          </div>

          <div className="grid gap-4 lg:grid-cols-2">

            <CameraPreview />

            <LidarPreview />

          </div>

        </section>

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.8fr)_minmax(320px,1fr)]">

          <div className="space-y-5">

            <Panel>

              <div className="flex items-center gap-3">

                <Power className="h-6 w-6 text-[#00866a]" />

                <div>

                  <h2 className="text-xl font-bold">
                    Robot Operating Modes
                  </h2>

                  <p className="mt-1 text-sm text-[#738080]">
                    Physical G1 FSM and guarded control
                  </p>

                </div>

              </div>

              <div className="mt-6 grid gap-3 sm:grid-cols-2">

                {MODES.map((mode) => {

                  const Icon = mode.icon;

                  const active =
                    live &&
                    currentFsm === mode.id;

                  const isPhysicalControl =
                    mode.action !== null;

                  const isLocomotion =
                    mode.action ===
                    "start_locomotion";

                  const capabilityAvailable =
                    isLocomotion
                      ? locomotionControlAvailable
                      : postureControlAvailable;

                  const sourceGuard =
                    mode.sourceFsm ===
                    null ||
                    currentFsm ===
                      mode.sourceFsm;

                                     // Buttons remain clickable to explain unavailable actions.
                   // The backend remains the authority for physical FSM commands.
                   const buttonEnabled =
                     isPhysicalControl && controlBusy === null;

const buttonText =
                    controlBusy === mode.action
                      ? "Sending..."
                      : isLocomotion
                        ? "Start Locomotion"
                        : mode.id === 1
                          ? "Activate Damp"
                          : "Stand Up";

                  return (
                    <div
                      key={mode.id}
                      className={`rounded-xl border p-4 transition-colors ${
                        active
                          ? "border-[#00866a] bg-[#eef8f3]"
                          : "border-[#dfe5e1] bg-[#fafbfa]"
                      }`}
                    >

                      <div className="flex items-start justify-between">

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

                      <p className="mt-1 text-xs text-[#738080]">FSM {mode.id}</p>

                      {isPhysicalControl ? (
                        <>
                          <button
                            type="button"
                            disabled={
                              !buttonEnabled
                            }
                            onClick={() => {
                              if (
                                mode.action
                              ) {
                                void requestPhysicalControl(
                                  mode.action
                                );
                              }
                            }}
                            className={`mt-4 flex w-full items-center justify-center gap-2 rounded-lg px-3 py-3 text-xs font-semibold transition ${
                              buttonEnabled
                                ? "bg-[#00866a] text-white hover:bg-[#007457] active:scale-[0.99]"
                                : "border border-[#d8dcda] bg-white text-[#738080] opacity-70"
                            }`}
                          >

                            {controlBusy ===
                            mode.action ? (
                              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Power className="h-3.5 w-3.5" />
                            )}

                            {buttonText}

                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          disabled
                          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-[#d8dcda] bg-white px-3 py-3 text-xs font-semibold text-[#738080] opacity-70"
                        >
                          <LockKeyhole className="h-3.5 w-3.5" />
                          Sit Mode Unavailable
                        </button>
                      )}

                    </div>
                  );
                })}

              </div>

                           {controlNotice && <div role="status" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{controlNotice}</div>}
</Panel>

            <Panel>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <Footprints className="h-6 w-6 text-[#00866a]" />
                  <div>
                    <h2 className="text-xl font-bold">Walking Controls</h2>
                    <p className="mt-1 text-sm text-[#738080]">
                      {walkingMode === "simulation"
                        ? "Browser simulation · No physical movement"
                        : "Physical G1 monitoring · Movement locked"}
                    </p>
                  </div>
                </div>
                <div className="flex rounded-xl border border-[#d8dfda] bg-[#f5f7f6] p-1" role="group" aria-label="Walking mode">
                  <button type="button" onClick={() => selectWalkingMode("simulation")}
                    aria-pressed={walkingMode === "simulation"}
                    className={`rounded-lg px-4 py-2 text-sm font-semibold ${walkingMode === "simulation" ? "bg-white text-[#00866a] shadow-sm" : "text-[#738080]"}`}>
                    Simulation
                  </button>
                  <button type="button" onClick={() => selectWalkingMode("physical")}
                    aria-pressed={walkingMode === "physical"}
                    className={`rounded-lg px-4 py-2 text-sm font-semibold ${walkingMode === "physical" ? "bg-white text-[#00866a] shadow-sm" : "text-[#738080]"}`}>
                    Physical G1
                  </button>
                </div>
              </div>

              {walkingMode === "simulation" ? (
                <>
                  <div className="mt-4 flex items-center justify-between text-xs">
                    <span className={motionError ? "text-red-700" : "text-emerald-700"}>
                      {motionError ? "Simulator unavailable" : motionStatus ? "Simulator connected" : "Connecting..."}
                    </span>
                    <span>{motionBusy ? "Command active" : motionStatus?.moving ? "Moving (simulated)" : "Stopped"}</span>
                  </div>
                  <div className="mx-auto mt-5 grid max-w-sm grid-cols-3 gap-3">
                    <div />
                    <MotionButton label="Forward" icon={<ArrowUp className="h-6 w-6" />} disabled={!motionStatus || !!motionError} onPress={() => startMotion("FORWARD")} onRelease={() => { if (motionActive.current) void stopMotion(); }} />
                    <div />
                    <MotionButton label="Turn Left" icon={<RotateCcw className="h-6 w-6" />} disabled={!motionStatus || !!motionError} onPress={() => startMotion("TURN_LEFT")} onRelease={() => { if (motionActive.current) void stopMotion(); }} />
                    <MotionButton label="Sim Stop" icon={<Square className="h-6 w-6" />} onPress={() => void stopMotion()} onRelease={() => {}} stop />
                    <MotionButton label="Turn Right" icon={<RotateCw className="h-6 w-6" />} disabled={!motionStatus || !!motionError} onPress={() => startMotion("TURN_RIGHT")} onRelease={() => { if (motionActive.current) void stopMotion(); }} />
                    <div />
                    <MotionButton label="Backward" icon={<ArrowDown className="h-6 w-6" />} disabled={!motionStatus || !!motionError} onPress={() => startMotion("BACKWARD")} onRelease={() => { if (motionActive.current) void stopMotion(); }} />
                    <div />
                  </div>
                  <p className="mt-4 text-center text-xs text-[#667783]">Hold to move · Release to stop · Simulation only</p>
                  {motionError && <p className="mt-2 text-center text-xs text-red-700">{motionError}</p>}
                </>
              ) : (
                <>
                  <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {[
                      ["Bridge", physicalMotionError ? "Unavailable" : physicalMotionStatus?.connected ? "Connected" : "Waiting"],
                      ["FSM", physicalMotionStatus?.fsm_id?.toString() ?? "Unknown"],
                      ["Controller", physicalMotionStatus?.mode ?? "Unavailable"],
                      ["Arming", physicalMotionStatus?.armed ? "Armed" : "Disarmed"],
                      ["LowState", physicalMotionStatus?.feedback?.feedback_fresh ? "Fresh" : "Unavailable"],
                      ["Stop verification", physicalMotionStatus?.stop_verified ? "Verified" : "Not verified"],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-xl border border-[#dfe5e1] bg-[#fafbfa] p-3">
                        <p className="text-xs text-[#738080]">{label}</p>
                        <p className="mt-1 break-words text-sm font-semibold">{value}</p>
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                    Physical velocity output is locked. FSM 500 means locomotion mode is selected, not that walking or stopping has been verified.
                    {physicalMotionStatus?.fault_latched && <p className="mt-2 font-semibold">Bridge fault is latched.</p>}
                    {physicalMotionStatus?.watchdog_triggered && <p className="mt-2 font-semibold">Motion watchdog triggered.</p>}
                  </div>
                  <div className="mx-auto mt-5 grid max-w-sm grid-cols-3 gap-3">
                    <div />
                    <MotionButton label="Forward" icon={<ArrowUp className="h-6 w-6" />} onPress={() => explainPhysicalWalking("Forward")} onRelease={() => {}} />
                    <div />
                    <MotionButton label="Turn Left" icon={<RotateCcw className="h-6 w-6" />} onPress={() => explainPhysicalWalking("Turn Left")} onRelease={() => {}} />
                    <MotionButton label="Request Stop" icon={<Square className="h-6 w-6" />} disabled={physicalStopBusy || !physicalMotionStatus?.connected} onPress={() => void requestPhysicalStop()} onRelease={() => {}} stop />
                    <MotionButton label="Turn Right" icon={<RotateCw className="h-6 w-6" />} onPress={() => explainPhysicalWalking("Turn Right")} onRelease={() => {}} />
                    <div />
                    <MotionButton label="Backward" icon={<ArrowDown className="h-6 w-6" />} onPress={() => explainPhysicalWalking("Backward")} onRelease={() => {}} />
                    <div />
                  </div>
                  <p className="mt-4 text-center text-xs text-[#667783]">Direction commands disabled · Stop requests are not a verified emergency stop</p>
                  {physicalMotionError && <p className="mt-3 text-center text-xs text-red-700">{physicalMotionError}</p>}
                  {physicalStopMessage && <p role="status" className="mt-3 text-center text-sm font-semibold text-amber-800">{physicalStopMessage}</p>}
                </>
              )}
            </Panel>

          </div>

          <aside className="space-y-5">
            <Panel>
<h2 className="text-lg font-bold">Simulation State</h2>
<div className="mt-5 space-y-4 text-sm">
  <div className="flex justify-between"><span>Last Command</span><strong>{lastCommand}</strong></div>
  <div className="flex justify-between"><span>Velocity X</span><strong>{(motionStatus?.velocity?.[0] ?? 0).toFixed(2)} m/s</strong></div>
  <div className="flex justify-between"><span>Velocity Y</span><strong>{(motionStatus?.velocity?.[1] ?? 0).toFixed(2)} m/s</strong></div>
  <div className="flex justify-between"><span>Yaw rate</span><strong>{(motionStatus?.velocity?.[2] ?? 0).toFixed(2)} rad/s</strong></div>
</div>
</Panel>

            <Panel>

              <h2 className="text-lg font-bold">
                Physical FSM Sequence
              </h2>

              <div className="mt-5 space-y-3">

                <div
                  className={`rounded-lg border p-3 ${
                    currentFsm === 0
                      ? "border-[#00866a] bg-[#eef8f3]"
                      : "border-[#e3e8e5]"
                  }`}
                >
                  <div className="flex items-center justify-between">

                    <span className="text-sm font-semibold">
                      FSM 0
                    </span>

                    <span className="text-xs text-[#738080]">
                      Idle
                    </span>

                  </div>

                  <p className="mt-1 text-xs text-[#738080]">
                    → Damp
                  </p>

                </div>

                <div
                  className={`rounded-lg border p-3 ${
                    currentFsm === 1
                      ? "border-[#00866a] bg-[#eef8f3]"
                      : "border-[#e3e8e5]"
                  }`}
                >
                  <div className="flex items-center justify-between">

                    <span className="text-sm font-semibold">
                      FSM 1
                    </span>

                    <span className="text-xs text-[#738080]">
                      Damp
                    </span>

                  </div>

                  <p className="mt-1 text-xs text-[#738080]">
                    → Stand Up
                  </p>

                </div>

                <div
                  className={`rounded-lg border p-3 ${
                    currentFsm === 4
                      ? "border-[#00866a] bg-[#eef8f3]"
                      : "border-[#e3e8e5]"
                  }`}
                >
                  <div className="flex items-center justify-between">

                    <span className="text-sm font-semibold">
                      FSM 4
                    </span>

                    <span className="text-xs text-[#738080]">
                      Stand
                    </span>

                  </div>

                  <p className="mt-1 text-xs text-[#738080]">
                    → Start Locomotion
                  </p>

                </div>

                <div
                  className={`rounded-lg border p-3 ${
                    currentFsm === 500
                      ? "border-[#00866a] bg-[#eef8f3]"
                      : "border-[#e3e8e5]"
                  }`}
                >
                  <div className="flex items-center justify-between">

                    <span className="text-sm font-semibold">
                      FSM 500
                    </span>

                    <span className="text-xs text-[#738080]">
                      Locomotion
                    </span>

                  </div>

                  <p className="mt-1 text-xs text-[#738080]">
                    Controller selected
                  </p>

                </div>

              </div>

            </Panel>

            <Panel>

              <h2 className="flex items-center gap-2 text-lg font-bold">

                <Clock3 className="h-5 w-5 text-[#00866a]" />

                Command History

              </h2>

              {logs.length ===
              0 ? (
                <p className="mt-4 text-sm text-[#738080]">
                  No commands recorded yet.
                </p>
              ) : (
                <div className="mt-4 max-h-72 space-y-3 overflow-y-auto">

                  {logs.map(
                    (entry) => (
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
                    )
                  )}

                </div>
              )}

            </Panel>

          </aside>

        </div>

        <p className="text-center text-xs text-[#83908c]">
          HFU IPSE · Unitree G1 Research Platform ·
          Physical posture and locomotion control protected
          by backend guards
        </p>

      </div>
    </main>
  );
}