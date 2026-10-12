
"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

type Step = {
  id?: string;
  name?: string;
  action?: string;
  action_type?: string;
  type?: string;
  description?: string;
  parameters?: Record<string, unknown>;
};

type Workflow = {
  id: string;
  name: string;
  description?: string;
  status?: string;
  steps: Step[];
};

type Source = "custom" | "demonstration";

type ExecutionState =
  | "idle"
  | "starting"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

type EngineEvent = {
  type: string;
  data: Record<string, unknown>;
};

const API =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

const WS =
  process.env.NEXT_PUBLIC_WS_URL ||
  "ws://localhost:8000/ws";

function getText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function actionLabel(step: Step): string {
  return (
    step.action ||
    step.action_type ||
    step.type ||
    step.name ||
    "Action"
  ).replaceAll("_", " ");
}

function stepDescription(step: Step): string {
  if (step.description) return step.description;

  const params = step.parameters || {};

  if (typeof params.text === "string") {
    return params.text;
  }

  if (typeof params.location_id === "string") {
    return `Location: ${params.location_id}`;
  }

  if (typeof params.seconds === "number") {
    return `Wait ${params.seconds} seconds`;
  }

  return (
    Object.entries(params)
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(" · ") ||
    step.name ||
    "Robot action"
  );
}

function parseEvent(raw: string): EngineEvent | null {
  try {
    const value: unknown = JSON.parse(raw);

    if (
      typeof value !== "object" ||
      value === null ||
      !("type" in value) ||
      typeof value.type !== "string"
    ) {
      return null;
    }

    const data =
      "data" in value &&
      typeof value.data === "object" &&
      value.data !== null &&
      !Array.isArray(value.data)
        ? (value.data as Record<string, unknown>)
        : {};

    return { type: value.type, data };
  } catch {
    return null;
  }
}

export default function WorkflowDetailPage() {
  const params = useParams();

  const workflowId = Array.isArray(params.id)
    ? params.id[0]
    : String(params.id || "");

  const [workflow, setWorkflow] =
    useState<Workflow | null>(null);

  const [source, setSource] =
    useState<Source>("custom");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [executionState, setExecutionState] =
    useState<ExecutionState>("idle");

  const [message, setMessage] = useState(
    "Ready for simulation."
  );

  const [taskId, setTaskId] =
    useState<string | null>(null);

  const [currentStep, setCurrentStep] =
    useState<number | null>(null);

  const [completedSteps, setCompletedSteps] =
    useState(0);

  const [events, setEvents] =
    useState<EngineEvent[]>([]);

  const [socketConnected, setSocketConnected] =
    useState(false);

  // References are used because WebSocket callbacks can
  // receive events before React finishes a state update.
  const activeTaskIdRef = useRef<string | null>(null);
  const pendingEventsRef = useRef<EngineEvent[]>([]);
  const requestPendingRef = useRef(false);
  const executionActiveRef = useRef(false);
  const terminalReceivedRef = useRef(false);
  const runInFlightRef = useRef(false);

  const loadWorkflow = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const customResponse = await fetch(
        `${API}/api/workflows/${encodeURIComponent(workflowId)}`,
        { cache: "no-store" }
      );

      if (customResponse.ok) {
        const result: Workflow =
          await customResponse.json();

        setWorkflow(result);
        setSource("custom");
        return;
      }

      if (customResponse.status !== 404) {
        throw new Error(
          "Unable to load saved workflow."
        );
      }

      const demoResponse = await fetch(
        `${API}/api/demonstrations/${encodeURIComponent(workflowId)}`,
        { cache: "no-store" }
      );

      if (!demoResponse.ok) {
        throw new Error(
          demoResponse.status === 404
            ? "Workflow not found."
            : "Unable to load demonstration."
        );
      }

      const result: Workflow =
        await demoResponse.json();

      setWorkflow(result);
      setSource("demonstration");
    } catch (caught) {
      setWorkflow(null);
      setError(
        caught instanceof Error
          ? caught.message
          : "Unable to load workflow."
      );
    } finally {
      setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    void loadWorkflow();
  }, [loadWorkflow]);

  const applyEvent = useCallback(
    (event: EngineEvent) => {
      const { type, data } = event;

      setEvents((previous) =>
        [...previous, event].slice(-100)
      );

      const index =
        typeof data.step_index === "number" &&
        Number.isInteger(data.step_index) &&
        data.step_index >= 0
          ? data.step_index
          : null;

      if (type === "task_started") {
        setExecutionState("running");
        setMessage("Simulation started.");
        return;
      }

      if (type === "step_started") {
        if (index !== null) {
          setCurrentStep(index);
        }

        setExecutionState("running");
        setMessage(
          getText(data.step_name)
            ? `Executing: ${data.step_name}`
            : "Executing robot action..."
        );
        return;
      }

      if (type === "step_completed") {
        if (index !== null) {
          setCompletedSteps((previous) =>
            Math.max(previous, index + 1)
          );
        }

        setMessage(
          getText(data.step_name)
            ? `Completed: ${data.step_name}`
            : "Step completed."
        );
        return;
      }

      if (type === "step_failed") {
        setMessage(
          getText(data.error) ||
            "A workflow step failed."
        );
        return;
      }

      if (type === "task_completed") {
        terminalReceivedRef.current = true;
        executionActiveRef.current = false;

        setExecutionState("completed");
        setCurrentStep(null);
        setMessage(
          "Workflow simulation completed successfully."
        );
        return;
      }

      if (type === "task_failed") {
        terminalReceivedRef.current = true;
        executionActiveRef.current = false;

        setExecutionState("failed");
        setCurrentStep(null);
        setMessage(
          getText(data.error) ||
            "Workflow simulation failed."
        );
        return;
      }

      if (type === "task_cancelled") {
        terminalReceivedRef.current = true;
        executionActiveRef.current = false;

        setExecutionState("cancelled");
        setCurrentStep(null);
        setMessage("Workflow was cancelled.");
      }
    },
    []
  );

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<
      typeof setTimeout
    > | null = null;

    let disposed = false;

    function connect() {
      if (disposed) return;

      socket = new WebSocket(WS);

      socket.onopen = () => {
        if (!disposed) {
          setSocketConnected(true);
        }
      };

      socket.onmessage = (incoming) => {
        if (disposed) return;

        const event = parseEvent(
          String(incoming.data)
        );

        if (!event) return;

        const incomingTaskId = getText(
          event.data.task_id
        );

        if (!incomingTaskId) return;

        // During the POST request, buffer events.
        // They may arrive before the HTTP response.
        if (requestPendingRef.current) {
          pendingEventsRef.current = [
            ...pendingEventsRef.current,
            event,
          ].slice(-200);
          return;
        }

        // Only events from this execution are shown.
        if (
          executionActiveRef.current &&
          activeTaskIdRef.current === incomingTaskId
        ) {
          applyEvent(event);
        }
      };

      socket.onclose = () => {
        if (disposed) return;

        setSocketConnected(false);

        if (
          executionActiveRef.current &&
          !terminalReceivedRef.current
        ) {
          setMessage(
            "Live connection lost. Execution outcome is not confirmed."
          );
        }

        retryTimer = setTimeout(connect, 2500);
      };

      socket.onerror = () => {
        if (!disposed) {
          setSocketConnected(false);
        }
      };
    }

    connect();

    return () => {
      disposed = true;

      if (retryTimer) {
        clearTimeout(retryTimer);
      }

      socket?.close();
    };
  }, [applyEvent]);

  async function runWorkflow() {
    if (
      !workflow ||
      runInFlightRef.current ||
      executionActiveRef.current ||
      !socketConnected
    ) {
      return;
    }

    runInFlightRef.current = true;
    requestPendingRef.current = true;
    executionActiveRef.current = true;
    terminalReceivedRef.current = false;
    activeTaskIdRef.current = null;
    pendingEventsRef.current = [];

    setTaskId(null);
    setEvents([]);
    setCompletedSteps(0);
    setCurrentStep(null);
    setExecutionState("starting");
    setMessage(
      "Submitting workflow to MockG1..."
    );

    const endpoint =
      source === "custom"
        ? `${API}/api/workflows/${encodeURIComponent(workflowId)}/run`
        : `${API}/api/demonstrations/${encodeURIComponent(workflowId)}/run`;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
      });

      const result = await response
        .json()
        .catch(() => null);

      if (!response.ok) {
        const detail =
          typeof result?.detail === "string"
            ? result.detail
            : `Request failed (${response.status}).`;

        throw new Error(detail);
      }

      if (
        result?.accepted !== true ||
        typeof result?.task_id !== "string"
      ) {
        throw new Error(
          "Backend did not return a valid execution task ID."
        );
      }

      const acceptedTaskId: string =
        result.task_id;

      activeTaskIdRef.current =
        acceptedTaskId;

      setTaskId(acceptedTaskId);

      // Replay only events belonging to the task
      // accepted by this HTTP request.
      const matchingEvents =
        pendingEventsRef.current.filter(
          (event) =>
            event.data.task_id === acceptedTaskId
        );

      for (const event of matchingEvents) {
        applyEvent(event);
      }

      pendingEventsRef.current = [];
      requestPendingRef.current = false;

      if (
        !terminalReceivedRef.current
      ) {
        setExecutionState((previous) =>
          previous === "starting"
            ? "running"
            : previous
        );

        if (matchingEvents.length === 0) {
          setMessage(
            "Workflow accepted. Waiting for live execution events."
          );
        }
      }
    } catch (caught) {
      requestPendingRef.current = false;
      executionActiveRef.current = false;
      pendingEventsRef.current = [];

      setExecutionState("failed");
      setMessage(
        caught instanceof Error
          ? caught.message
          : "Unable to start workflow."
      );
    } finally {
      runInFlightRef.current = false;
    }
  }

  function resetExecution() {
    if (
      runInFlightRef.current ||
      executionActiveRef.current
    ) {
      return;
    }

    activeTaskIdRef.current = null;
    pendingEventsRef.current = [];
    terminalReceivedRef.current = false;

    setTaskId(null);
    setCurrentStep(null);
    setCompletedSteps(0);
    setEvents([]);
    setExecutionState("idle");
    setMessage("Ready for simulation.");
  }

  if (loading) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center bg-[#f7f8f7] text-sm text-[#899398]">
        Loading workflow...
      </div>
    );
  }

  if (!workflow || error) {
    return (
      <main className="min-h-[70vh] bg-[#f7f8f7] px-6 py-12 md:px-16">
        <Link
          href="/studio/workflows"
          className="text-xs font-bold text-[#00866a]"
        >
          ← Back to Workflows
        </Link>

        <div className="mt-8 border border-[#dfe3e1] bg-white p-10">
          <h1 className="text-xl font-bold text-[#343c40]">
            Workflow unavailable
          </h1>

          <p className="mt-3 text-sm text-[#899398]">
            {error || "Workflow not found."}
          </p>

          <button
            type="button"
            onClick={() => void loadWorkflow()}
            className="mt-6 bg-[#009b77] px-5 py-3 text-xs font-bold text-white"
          >
            Retry
          </button>
        </div>
      </main>
    );
  }

  const steps = workflow.steps || [];

  const busy =
    executionState === "starting" ||
    executionState === "running";

  const completed =
    executionState === "completed"
      ? steps.length
      : completedSteps;

  const progress =
    steps.length > 0
      ? Math.min(
          100,
          (completed / steps.length) * 100
        )
      : 0;

  const canRun =
    !busy &&
    !executionActiveRef.current &&
    socketConnected &&
    steps.length > 0;

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto max-w-[1600px] px-6 py-10 md:px-16">
          <Link
            href="/studio/workflows"
            className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#00866a]"
          >
            ← Workflows
          </Link>

          <div className="mt-7 flex flex-wrap items-end justify-between gap-5">
            <div>
              <div className="h-[3px] w-12 bg-[#009b77]" />

              <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#8a9499]">
                Workflow Engineering / {source}
              </p>

              <h1 className="mt-4 text-[38px] font-bold tracking-[-0.04em] text-[#2d3337]">
                {workflow.name}
              </h1>

              <p className="mt-3 max-w-[700px] text-[13px] leading-6 text-[#707b81]">
                {workflow.description ||
                  "Reusable Unitree G1 humanoid robot workflow."}
              </p>
            </div>

            {source === "custom" ? (
              <Link
                href={`/studio/workflows/${encodeURIComponent(workflowId)}/edit`}
                className="bg-[#009b77] px-6 py-4 text-[10px] font-bold uppercase tracking-[0.14em] text-white hover:bg-[#00866a]"
              >
                Edit Workflow →
              </Link>
            ) : (
              <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#7d878c]">
                Predefined Demonstration
              </span>
            )}
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-[1600px] px-6 py-10 md:px-16">
        <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_390px]">
          <div className="space-y-7">
            <section className="border border-[#dfe3e1] bg-white">
              <div className="flex items-center justify-between border-b border-[#e5e8e6] px-7 py-6">
                <div>
                  <h2 className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
                    Workflow Sequence
                  </h2>

                  <p className="mt-2 text-[10px] text-[#9aa2a6]">
                    Reusable G1 task actions
                  </p>
                </div>

                <span className="text-[10px] text-[#929b9f]">
                  {steps.length} Steps
                </span>
              </div>

              <div className="space-y-3 px-7 py-7">
                {steps.map((step, index) => {
                  const active =
                    busy && currentStep === index;

                  const done =
                    executionState === "completed" ||
                    index < completed;

                  return (
                    <div
                      key={step.id || index}
                      className={`flex min-h-[92px] items-center gap-5 border px-6 ${
                        active
                          ? "border-[#009b77] bg-[#f5fbf9]"
                          : "border-[#e0e4e2] bg-white"
                      }`}
                    >
                      <span
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold ${
                          done
                            ? "border-[#9acabd] bg-[#eef8f5] text-[#00866a]"
                            : active
                              ? "border-[#009b77] bg-[#009b77] text-white"
                              : "border-[#d7ddda] text-[#7f898e]"
                        }`}
                      >
                        {done
                          ? "✓"
                          : String(index + 1).padStart(
                              2,
                              "0"
                            )}
                      </span>

                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[#4e595e]">
                          {actionLabel(step)}
                        </p>

                        <p className="mt-2 break-words text-[11px] text-[#959da1]">
                          {stepDescription(step)}
                        </p>
                      </div>

                      {active && (
                        <span className="text-[9px] font-bold uppercase text-[#00866a]">
                          Executing
                        </span>
                      )}

                      {!active && done && (
                        <span className="text-[9px] font-bold uppercase text-[#00866a]">
                          Complete
                        </span>
                      )}
                    </div>
                  );
                })}

                {steps.length === 0 && (
                  <p className="py-12 text-center text-sm text-[#929b9f]">
                    No steps configured.
                  </p>
                )}
              </div>
            </section>

            <section className="border border-[#dfe3e1] bg-white">
              <div className="flex justify-between border-b border-[#e5e8e6] px-7 py-5">
                <h2 className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
                  Execution Events
                </h2>

                <span className="text-[10px] text-[#929b9f]">
                  {events.length} Events
                </span>
              </div>

              <div className="max-h-[320px] overflow-y-auto">
                {events.length === 0 ? (
                  <p className="px-7 py-12 text-center text-[11px] text-[#9aa2a6]">
                    Live execution events will appear here.
                  </p>
                ) : (
                  events
                    .slice()
                    .reverse()
                    .map((event, index) => (
                      <div
                        key={`${event.type}-${index}`}
                        className="border-b border-[#f0f2f1] px-7 py-4"
                      >
                        <p className="text-[10px] font-bold uppercase text-[#59646a]">
                          {event.type.replaceAll(
                            "_",
                            " "
                          )}
                        </p>

                        <p className="mt-2 break-words text-[10px] text-[#939ca0]">
                          {getText(
                            event.data.step_name
                          ) ||
                            getText(
                              event.data.error
                            ) ||
                            getText(
                              event.data.action
                            ) ||
                            JSON.stringify(
                              event.data
                            )}
                        </p>
                      </div>
                    ))
                )}
              </div>
            </section>
          </div>

          <aside>
            <div className="sticky top-6 border border-[#dfe3e1] bg-white p-6">
              <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#657078]">
                Robot Execution
              </h2>

              <p className="mt-2 text-[10px] text-[#9aa2a6]">
                G1 Task Engine / MockG1 Simulation
              </p>

              <div className="mt-6 space-y-5 border-y border-[#edf0ee] py-6 text-[12px] text-[#657078]">
                <div className="flex justify-between">
                  <span>Status</span>

                  <strong className="capitalize text-[#343c40]">
                    {executionState}
                  </strong>
                </div>

                <div className="flex justify-between">
                  <span>Steps Completed</span>
                  <strong>
                    {completed} / {steps.length}
                  </strong>
                </div>

                <div className="h-[3px] bg-[#e8ebe9]">
                  <div
                    className="h-full bg-[#009b77] transition-all"
                    style={{
                      width: `${progress}%`,
                    }}
                  />
                </div>

                <div className="flex justify-between gap-3">
                  <span>Task ID</span>

                  <span className="max-w-[190px] truncate font-mono text-[10px]">
                    {taskId || "—"}
                  </span>
                </div>

                <div className="flex justify-between">
                  <span>Live Events</span>

                  <strong
                    className={
                      socketConnected
                        ? "text-[#00866a]"
                        : "text-[#b65353]"
                    }
                  >
                    {socketConnected
                      ? "Connected"
                      : "Disconnected"}
                  </strong>
                </div>
              </div>

              <p
                role="status"
                className="mb-6 border border-[#e5e9e7] bg-[#fafbfa] p-4 text-[11px] leading-5 text-[#747f84]"
              >
                {message}
              </p>

              <button
                type="button"
                onClick={() =>
                  void runWorkflow()
                }
                disabled={!canRun}
                className="w-full bg-[#009b77] px-5 py-4 text-[10px] font-bold uppercase tracking-[0.14em] text-white transition hover:bg-[#00866a] disabled:cursor-not-allowed disabled:bg-[#b9c2bf]"
              >
                {busy
                  ? "Workflow Running..."
                  : "Run Workflow"}
              </button>

              {(
                executionState === "completed" ||
                executionState === "failed" ||
                executionState === "cancelled"
              ) && (
                <button
                  type="button"
                  onClick={resetExecution}
                  className="mt-3 w-full border border-[#d7ddda] px-5 py-3 text-[10px] font-bold uppercase text-[#68747a]"
                >
                  Reset Execution
                </button>
              )}

              <p className="mt-5 text-[10px] leading-5 text-[#9aa2a6]">
                This interface executes simulated actions
                only. Real G1 navigation and movement
                require separate safety validation.
              </p>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
