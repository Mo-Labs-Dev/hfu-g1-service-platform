
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

type ExecutionStep = {
  id: string;
  position: number;
  name: string;
  action: string;
  parameters: Record<string, unknown>;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  error: string | null;
};

type Execution = {
  id: string;
  workflow_id: string | null;
  workflow_name: string;
  mode: string;
  status: string;
  workflow_snapshot: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  error: string | null;
  steps: ExecutionStep[];
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function formatDuration(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(2)}s`;
}

function statusClasses(status: string): string {
  switch (status.toLowerCase()) {
    case "completed":
      return "bg-emerald-50 text-emerald-700 ring-emerald-200";
    case "running":
      return "bg-blue-50 text-blue-700 ring-blue-200";
    case "failed":
      return "bg-red-50 text-red-700 ring-red-200";
    case "cancelled":
      return "bg-amber-50 text-amber-700 ring-amber-200";
    default:
      return "bg-slate-50 text-slate-600 ring-slate-200";
  }
}

export default function ExecutionDetailsPage() {
  const params = useParams<{ id: string }>();
  const executionId = params.id;

  const [execution, setExecution] = useState<Execution | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExecution = useCallback(
    async (isRefresh = false) => {
      if (!executionId) return;

      if (isRefresh) setRefreshing(true);
      else setLoading(true);

      setError(null);

      try {
        const response = await fetch(
          `${API_BASE}/api/executions/${encodeURIComponent(
            executionId
          )}`,
          { cache: "no-store" }
        );

        if (!response.ok) {
          throw new Error(
            response.status === 404
              ? "Execution not found"
              : `Unable to load execution (${response.status})`
          );
        }

        const data: Execution = await response.json();
        setExecution(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Unexpected error"
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [executionId]
  );

  useEffect(() => {
    void loadExecution();
  }, [loadExecution]);

  const completedSteps =
    execution?.steps.filter(
      (step) => step.status === "completed"
    ).length ?? 0;

  const failedSteps =
    execution?.steps.filter(
      (step) => step.status === "failed"
    ).length ?? 0;

  return (
    <div className="min-h-screen bg-[#f7f9f8] text-slate-900">
      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link
              href="/studio/executions"
              className="text-sm font-medium text-emerald-700 hover:underline"
            >
              ← Execution History
            </Link>

            <h1 className="mt-3 text-3xl font-bold tracking-tight">
              Execution Results
            </h1>

            <p className="mt-2 text-sm text-slate-500">
              Review the recorded workflow execution.
            </p>
          </div>

          <button
            type="button"
            onClick={() => void loadExecution(true)}
            disabled={refreshing || loading}
            className="rounded-xl bg-emerald-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:opacity-50"
          >
            {refreshing ? "Refreshing..." : "Refresh Results"}
          </button>
        </div>

        {loading ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center text-slate-500">
            Loading execution results...
          </div>
        ) : error ? (
          <div className="rounded-2xl border border-red-200 bg-white p-10">
            <h2 className="font-semibold text-red-700">
              Unable to load execution
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              {error}
            </p>
          </div>
        ) : execution ? (
          <>
            <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
                    Workflow Execution
                  </p>

                  <h2 className="mt-2 text-2xl font-bold">
                    {execution.workflow_name}
                  </h2>

                  <p className="mt-2 break-all font-mono text-xs text-slate-400">
                    {execution.id}
                  </p>
                </div>

                <span
                  className={`rounded-full px-4 py-2 text-sm font-semibold capitalize ring-1 ${statusClasses(
                    execution.status
                  )}`}
                >
                  {execution.status}
                </span>
              </div>

              {execution.workflow_id && (
                <Link
                  href={`/studio/workflows/${encodeURIComponent(
                    execution.workflow_id
                  )}`}
                  className="mt-5 inline-block text-sm font-semibold text-emerald-700 hover:underline"
                >
                  Open Original Workflow →
                </Link>
              )}
            </div>

            <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                {
                  label: "Duration",
                  value: formatDuration(
                    execution.duration_seconds
                  ),
                },
                {
                  label: "Completed Steps",
                  value: `${completedSteps}/${execution.steps.length}`,
                },
                {
                  label: "Failed Steps",
                  value: failedSteps.toString(),
                },
                {
                  label: "Execution Mode",
                  value: execution.mode,
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
                >
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    {item.label}
                  </p>

                  <p className="mt-3 text-2xl font-bold capitalize">
                    {item.value}
                  </p>
                </div>
              ))}
            </div>

            <div className="mb-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold">
                Execution Information
              </h3>

              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                <div>
                  <p className="text-xs text-slate-500">
                    Started At
                  </p>
                  <p className="mt-1 text-sm font-medium">
                    {formatDate(execution.started_at)}
                  </p>
                </div>

                <div>
                  <p className="text-xs text-slate-500">
                    Finished At
                  </p>
                  <p className="mt-1 text-sm font-medium">
                    {formatDate(execution.finished_at)}
                  </p>
                </div>
              </div>

              {execution.error && (
                <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4">
                  <p className="text-sm font-semibold text-red-700">
                    Execution Error
                  </p>
                  <p className="mt-2 whitespace-pre-wrap text-sm text-red-600">
                    {execution.error}
                  </p>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-6">
                <h3 className="text-lg font-semibold">
                  Step-by-Step Results
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  Recorded action results in execution order.
                </p>
              </div>

              {execution.steps.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  No step results recorded.
                </p>
              ) : (
                <div className="space-y-4">
                  {[...execution.steps]
                    .sort((a, b) => a.position - b.position)
                    .map((step) => (
                      <div
                        key={step.id}
                        className="rounded-xl border border-slate-200 p-5"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div className="flex items-start gap-4">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-sm font-bold text-emerald-700">
                              {step.position + 1}
                            </div>

                            <div>
                              <h4 className="font-semibold">
                                {step.name}
                              </h4>
                              <p className="mt-1 text-sm text-slate-500">
                                Action: {step.action.replace(/_/g, " ")}
                              </p>
                            </div>
                          </div>

                          <span
                            className={`rounded-full px-3 py-1 text-xs font-semibold capitalize ring-1 ${statusClasses(
                              step.status
                            )}`}
                          >
                            {step.status}
                          </span>
                        </div>

                        <div className="mt-5 grid gap-4 border-t border-slate-100 pt-4 sm:grid-cols-3">
                          <div>
                            <p className="text-xs text-slate-500">
                              Duration
                            </p>
                            <p className="mt-1 text-sm font-semibold">
                              {formatDuration(
                                step.duration_seconds
                              )}
                            </p>
                          </div>

                          <div>
                            <p className="text-xs text-slate-500">
                              Started
                            </p>
                            <p className="mt-1 text-sm">
                              {formatDate(step.started_at)}
                            </p>
                          </div>

                          <div>
                            <p className="text-xs text-slate-500">
                              Finished
                            </p>
                            <p className="mt-1 text-sm">
                              {formatDate(step.finished_at)}
                            </p>
                          </div>
                        </div>

                        {Object.keys(step.parameters).length > 0 && (
                          <details className="mt-5 rounded-lg bg-slate-50 p-4">
                            <summary className="cursor-pointer text-sm font-medium text-slate-700">
                              Action Parameters
                            </summary>

                            <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words text-xs text-slate-600">
                              {JSON.stringify(
                                step.parameters,
                                null,
                                2
                              )}
                            </pre>
                          </details>
                        )}

                        {step.error && (
                          <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
                            {step.error}
                          </p>
                        )}
                      </div>
                    ))}
                </div>
              )}
            </div>

            <p className="mt-5 text-xs text-slate-400">
              Results reflect recorded simulation events.
              Physical Unitree G1 performance has not been validated.
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}
