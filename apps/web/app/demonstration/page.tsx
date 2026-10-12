"use client";

import { useEffect, useMemo, useState } from "react";

import Header from "@/components/layout/Header";
import { apiGet, apiPost } from "@/services/api";
import {
  G1Event,
  g1WebSocket,
} from "@/services/websocket";


type TaskStep = {
  id: string;
  name: string;
  action: string;
  parameters: Record<string, unknown>;
  status: string;
};

type Demonstration = {
  id: string;
  name: string;
  description: string;
  location_id: string | null;
  steps: TaskStep[];
  enabled: boolean;
};

type RunResponse = {
  accepted: boolean;
  demonstration_id: string;
};


function formatAction(action: string | null) {
  if (!action) return "IDLE";

  return action.replaceAll("_", " ").toUpperCase();
}


export default function DemonstrationPage() {
  const [demonstrations, setDemonstrations] =
    useState<Demonstration[]>([]);

  const [loading, setLoading] = useState(true);

  const [runningId, setRunningId] =
    useState<string | null>(null);

  const [taskName, setTaskName] =
    useState<string | null>(null);

  const [taskStatus, setTaskStatus] =
    useState("idle");

  const [currentStep, setCurrentStep] =
    useState<number | null>(null);

  const [currentAction, setCurrentAction] =
    useState<string | null>(null);

  const [completedSteps, setCompletedSteps] =
    useState<number[]>([]);

  const [error, setError] =
    useState<string | null>(null);


  useEffect(() => {
    loadDemonstrations();

    g1WebSocket.connect();

    const unsubscribe =
      g1WebSocket.subscribe(handleRobotEvent);

    return () => {
      unsubscribe();
    };
  }, []);


  async function loadDemonstrations() {
    try {
      setError(null);

      const data = await apiGet<Demonstration[]>(
        "/api/demonstrations"
      );

      setDemonstrations(data);
    } catch (err) {
      console.error(err);

      setError(
        "Unable to connect to the G1 backend."
      );
    } finally {
      setLoading(false);
    }
  }


  function handleRobotEvent(event: G1Event) {
    console.log("[G1 EVENT]", event);

    switch (event.type) {
      case "task_started":
        setTaskName(
          String(event.data.task_name)
        );

        setTaskStatus("running");
        setCurrentStep(null);
        setCompletedSteps([]);
        break;

      case "step_started":
        setCurrentStep(
          Number(event.data.step_index)
        );
        break;

      case "robot_action":
        setCurrentAction(
          String(event.data.action)
        );
        break;

      case "step_completed":
        setCompletedSteps((previous) => {
          const index = Number(
            event.data.step_index
          );

          if (previous.includes(index)) {
            return previous;
          }

          return [...previous, index];
        });
        break;

      case "task_completed":
        setTaskStatus("completed");
        setCurrentStep(null);
        setCurrentAction(null);
        setRunningId(null);
        break;

      case "task_failed":
        setTaskStatus("failed");
        setCurrentStep(null);
        setCurrentAction(null);
        setRunningId(null);
        break;

      case "task_cancelled":
        setTaskStatus("cancelled");
        setCurrentStep(null);
        setCurrentAction(null);
        setRunningId(null);
        break;
    }
  }


  async function runDemonstration(
    demonstration: Demonstration
  ) {
    try {
      setError(null);

      setRunningId(demonstration.id);
      setTaskName(demonstration.name);
      setTaskStatus("starting");

      setCurrentStep(null);
      setCurrentAction(null);
      setCompletedSteps([]);

      await apiPost<RunResponse>(
        `/api/demonstrations/${demonstration.id}/run`
      );
    } catch (err) {
      console.error(err);

      setError(
        "The demonstration could not be started."
      );

      setRunningId(null);
      setTaskStatus("failed");
    }
  }


  const activeDemo = useMemo(() => {
    if (runningId) {
      return demonstrations.find(
        (demo) => demo.id === runningId
      );
    }

    if (taskName) {
      return demonstrations.find(
        (demo) => demo.name === taskName
      );
    }

    return undefined;
  }, [
    demonstrations,
    runningId,
    taskName,
  ]);


  const progress =
    activeDemo && activeDemo.steps.length > 0
      ? Math.round(
          (completedSteps.length /
            activeDemo.steps.length) *
            100
        )
      : 0;


  return (
    <div className="min-h-screen bg-slate-950">
      <Header
        title="Demonstrations"
        description="Configure, execute and monitor robot workflows"
      />

      <div className="mx-auto max-w-[1600px] p-8">

        {/* PAGE TOOLBAR */}

        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Workflow Library
            </p>

            <p className="mt-1 text-sm text-slate-400">
              {demonstrations.length} configured demonstrations
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-3 py-2">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />

              <span className="text-xs font-medium text-slate-300">
                Backend Online
              </span>
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-300">
              SIMULATION
            </div>
          </div>
        </div>


        {error && (
          <div className="mb-6 rounded-lg border border-red-900/70 bg-red-950/30 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}


        {/* ACTIVE TASK */}

        {taskName && (
          <section className="mb-8 overflow-hidden rounded-xl border border-slate-800 bg-slate-900">

            <div className="flex items-start justify-between border-b border-slate-800 px-6 py-5">
              <div>
                <div className="flex items-center gap-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Active Task
                  </p>

                  {taskStatus === "running" && (
                    <span className="flex items-center gap-2 text-xs text-blue-400">
                      <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
                      LIVE
                    </span>
                  )}
                </div>

                <h2 className="mt-2 text-xl font-semibold tracking-tight text-white">
                  {taskName}
                </h2>
              </div>


              <div className="flex items-center gap-6">
                <div className="text-right">
                  <p className="text-xs uppercase tracking-wider text-slate-500">
                    Progress
                  </p>

                  <p className="mt-1 text-lg font-semibold text-white">
                    {progress}%
                  </p>
                </div>

                <span
                  className={`rounded-md border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider ${
                    taskStatus === "completed"
                      ? "border-emerald-800 bg-emerald-950/40 text-emerald-400"
                      : taskStatus === "failed"
                        ? "border-red-800 bg-red-950/40 text-red-400"
                        : "border-blue-800 bg-blue-950/40 text-blue-400"
                  }`}
                >
                  {taskStatus}
                </span>
              </div>
            </div>


            {/* PROGRESS BAR */}

            <div className="h-1 bg-slate-800">
              <div
                className="h-full bg-blue-500 transition-all duration-500"
                style={{
                  width: `${progress}%`,
                }}
              />
            </div>


            {/* EXECUTION PIPELINE */}

            {activeDemo && (
              <div className="px-6 py-6">

                <p className="mb-5 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Execution Sequence
                </p>

                <div className="grid gap-3 lg:grid-cols-5">

                  {activeDemo.steps.map(
                    (step, index) => {

                      const completed =
                        completedSteps.includes(index);

                      const running =
                        currentStep === index &&
                        taskStatus === "running";

                      return (
                        <div
                          key={step.id}
                          className={`relative rounded-lg border p-4 transition ${
                            running
                              ? "border-blue-500 bg-blue-950/20"
                              : completed
                                ? "border-emerald-900/70 bg-emerald-950/10"
                                : "border-slate-800 bg-slate-950"
                          }`}
                        >
                          <div className="mb-4 flex items-center justify-between">

                            <span
                              className={`flex h-7 w-7 items-center justify-center rounded-md text-xs font-semibold ${
                                completed
                                  ? "bg-emerald-950 text-emerald-400"
                                  : running
                                    ? "bg-blue-600 text-white"
                                    : "bg-slate-800 text-slate-500"
                              }`}
                            >
                              {completed
                                ? "✓"
                                : index + 1}
                            </span>

                            <span
                              className={`text-[10px] font-semibold uppercase tracking-wider ${
                                completed
                                  ? "text-emerald-500"
                                  : running
                                    ? "text-blue-400"
                                    : "text-slate-600"
                              }`}
                            >
                              {completed
                                ? "Done"
                                : running
                                  ? "Running"
                                  : "Pending"}
                            </span>

                          </div>

                          <p className="text-sm font-medium leading-5 text-slate-200">
                            {step.name}
                          </p>

                          <p className="mt-2 text-xs uppercase tracking-wider text-slate-600">
                            {step.action.replaceAll(
                              "_",
                              " "
                            )}
                          </p>
                        </div>
                      );
                    }
                  )}

                </div>


                <div className="mt-6 flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-4 py-3">

                  <div className="flex items-center gap-4">
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">
                        Robot Action
                      </p>

                      <p className="mt-1 font-mono text-sm font-medium text-blue-400">
                        {formatAction(
                          currentAction
                        )}
                      </p>
                    </div>
                  </div>

                  <div className="text-right">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">
                      Execution
                    </p>

                    <p className="mt-1 text-sm text-slate-300">
                      {completedSteps.length} /{" "}
                      {activeDemo.steps.length} steps
                    </p>
                  </div>

                </div>

              </div>
            )}

          </section>
        )}


        {/* DEMONSTRATION LIBRARY */}

        <section>
          <div className="mb-4 flex items-end justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">
                Demonstration Library
              </h2>

              <p className="mt-1 text-sm text-slate-500">
                Select a workflow to execute on G1
              </p>
            </div>

            <p className="text-xs font-medium text-slate-500">
              {demonstrations.length} AVAILABLE
            </p>
          </div>


          {loading ? (
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-8 text-sm text-slate-400">
              Loading demonstration library...
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">

              {demonstrations.map((demo) => {

                const isRunning =
                  runningId === demo.id;

                return (
                  <article
                    key={demo.id}
                    className="group flex min-h-[220px] flex-col rounded-xl border border-slate-800 bg-slate-900 p-5 transition hover:border-slate-700"
                  >

                    <div className="flex items-start justify-between">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 bg-slate-950 font-mono text-xs font-bold text-blue-400">
                        {demo.id
                          .split("-")[0]
                          .slice(0, 2)
                          .toUpperCase()}
                      </div>

                      <div className="flex items-center gap-2">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />

                        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                          Ready
                        </span>
                      </div>
                    </div>


                    <div className="mt-5 flex-1">
                      <h3 className="text-base font-semibold text-white">
                        {demo.name}
                      </h3>

                      <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-500">
                        {demo.description}
                      </p>
                    </div>


                    <div className="mt-5 flex items-center justify-between border-t border-slate-800 pt-4">

                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">
                          Sequence
                        </p>

                        <p className="mt-1 text-xs font-medium text-slate-300">
                          {demo.steps.length} steps
                        </p>
                      </div>


                      <button
                        onClick={() =>
                          runDemonstration(demo)
                        }
                        disabled={
                          runningId !== null ||
                          !demo.enabled
                        }
                        className="rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500"
                      >
                        {isRunning
                          ? "RUNNING"
                          : "RUN"}
                      </button>

                    </div>

                  </article>
                );
              })}

            </div>
          )}
        </section>

      </div>
    </div>
  );
}