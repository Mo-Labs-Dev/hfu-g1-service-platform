
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

type Execution = {
  id: string;
  workflow_id: string | null;
  workflow_name: string;
  mode: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  error: string | null;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function formatDate(value: string | null): string {
  if (!value) return "Not started";

  return new Date(value).toLocaleString();
}

function formatDuration(value: number | null): string {
  if (value === null) return "—";
  return `${value.toFixed(2)}s`;
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

export default function ExecutionHistoryPage() {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");

  const loadExecutions = useCallback(
    async (isRefresh = false) => {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);

      setError(null);

      try {
        const response = await fetch(
          `${API_BASE}/api/executions?limit=100`,
          { cache: "no-store" }
        );

        if (!response.ok) {
          throw new Error(
            `Unable to load execution history (${response.status})`
          );
        }

        const data: Execution[] = await response.json();
        setExecutions(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Unexpected error"
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );

  useEffect(() => {
    void loadExecutions();
  }, [loadExecutions]);

  const stats = useMemo(() => {
    const completed = executions.filter(
      (item) => item.status === "completed"
    );

    const failed = executions.filter(
      (item) => item.status === "failed"
    );

    const finished = executions.filter((item) =>
      ["completed", "failed", "cancelled"].includes(item.status)
    );

    const durations = completed
      .map((item) => item.duration_seconds)
      .filter((value): value is number => value !== null);

    const averageDuration =
      durations.length > 0
        ? durations.reduce((sum, value) => sum + value, 0) /
          durations.length
        : null;

    return {
      total: executions.length,
      completed: completed.length,
      failed: failed.length,
      successRate:
        finished.length > 0
          ? (completed.length / finished.length) * 100
          : null,
      averageDuration,
    };
  }, [executions]);

  const filteredExecutions = useMemo(() => {
    if (filter === "all") return executions;

    return executions.filter((item) => item.status === filter);
  }, [executions, filter]);

  const summaryCards = [
    { label: "Total Executions", value: stats.total.toString() },
    { label: "Completed", value: stats.completed.toString() },
    { label: "Failed", value: stats.failed.toString() },
    {
      label: "Success Rate",
      value:
        stats.successRate === null
          ? "—"
          : `${stats.successRate.toFixed(1)}%`,
    },
    {
      label: "Avg. Duration",
      value: formatDuration(stats.averageDuration),
    },
  ];

  return (
    <div className="min-h-screen bg-[#f7f9f8] text-slate-900">
      <div className="mx-auto max-w-7xl px-5 py-10 sm:px-8">
        <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link
              href="/studio"
              className="text-sm font-medium text-emerald-700 hover:underline"
            >
              ← Back to Studio
            </Link>

            <h1 className="mt-3 text-3xl font-bold tracking-tight">
              Execution History
            </h1>

            <p className="mt-2 text-sm text-slate-500">
              Monitor workflow runs and review recorded results.
            </p>
          </div>

          <button
            type="button"
            onClick={() => void loadExecutions(true)}
            disabled={refreshing}
            className="rounded-xl bg-emerald-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:opacity-50"
          >
            {refreshing ? "Refreshing..." : "Refresh History"}
          </button>
        </div>

        <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {summaryCards.map((card) => (
            <div
              key={card.label}
              className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {card.label}
              </p>

              <p className="mt-3 text-3xl font-bold text-slate-900">
                {card.value}
              </p>
            </div>
          ))}
        </div>

        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 p-6">
            <div>
              <h2 className="text-lg font-semibold">
                Recent Executions
              </h2>

              <p className="mt-1 text-sm text-slate-500">
                Showing up to 100 recent records.
              </p>
            </div>

            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm outline-none focus:border-emerald-500"
            >
              <option value="all">All Statuses</option>
              <option value="completed">Completed</option>
              <option value="running">Running</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
              <option value="pending">Pending</option>
            </select>
          </div>

          {loading ? (
            <div className="p-12 text-center text-slate-500">
              Loading execution history...
            </div>
          ) : error ? (
            <div className="p-12 text-center">
              <p className="font-medium text-red-600">
                Failed to load history
              </p>
              <p className="mt-2 text-sm text-slate-500">
                {error}
              </p>
            </div>
          ) : filteredExecutions.length === 0 ? (
            <div className="p-12 text-center">
              <p className="font-medium text-slate-700">
                No executions found
              </p>
              <p className="mt-2 text-sm text-slate-500">
                Run a workflow to generate execution history.
              </p>
              <Link
                href="/studio/workflows"
                className="mt-5 inline-block rounded-lg bg-emerald-700 px-5 py-2.5 text-sm font-semibold text-white"
              >
                Open Workflows
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-6 py-4">Workflow</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4">Mode</th>
                    <th className="px-6 py-4">Started</th>
                    <th className="px-6 py-4">Duration</th>
                    <th className="px-6 py-4">Details</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-slate-100">
                  {filteredExecutions.map((execution) => (
                    <tr
                      key={execution.id}
                      className="transition hover:bg-slate-50"
                    >
                      <td className="px-6 py-5">
                        <p className="font-semibold">
                          {execution.workflow_name}
                        </p>
                        <p className="mt-1 max-w-[220px] truncate font-mono text-xs text-slate-400">
                          {execution.id}
                        </p>
                      </td>

                      <td className="px-6 py-5">
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold capitalize ring-1 ${statusClasses(
                            execution.status
                          )}`}
                        >
                          {execution.status}
                        </span>
                      </td>

                      <td className="px-6 py-5 text-sm capitalize text-slate-600">
                        {execution.mode}
                      </td>

                      <td className="px-6 py-5 text-sm text-slate-600">
                        {formatDate(execution.started_at)}
                      </td>

                      <td className="px-6 py-5 text-sm font-medium">
                        {formatDuration(execution.duration_seconds)}
                      </td>

                      <td className="px-6 py-5">
                        <Link
                          href={`/studio/executions/${encodeURIComponent(
                            execution.id
                          )}`}
                          className="text-sm font-semibold text-emerald-700 hover:underline"
                        >
                          View Results →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="mt-5 text-xs text-slate-400">
          Statistics reflect the loaded execution records. Simulation
          results do not represent physical robot performance.
        </p>
      </div>
    </div>
  );
}
