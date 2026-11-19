"use client";

// G1 Studio - Evaluation
// Every guide / tour run (logged automatically by the robot) with statistics,
// a duration chart, notes / exclude flags and CSV export for the thesis.

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiBase, getJson, sendJson } from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";

type Run = {
  id: string;
  started: string;
  route: string;
  kind: string;
  lang: string;
  result: string;
  duration_s: number;
  length_m: number;
  stops: number;
  progress: number;
  blocked_count: number;
  blocked_s: number;
  message: string;
  note: string;
  excluded: boolean;
  alignment?: { used?: boolean; dx?: number; dy?: number; dyaw_deg?: number; fit?: number; reason?: string };
};

type Stats = {
  runs: number;
  excluded: number;
  done: number;
  aborted: number;
  cancelled: number;
  success_rate: number | null;
  avg_duration_s: number | null;
  avg_blocked_s: number | null;
  total_distance_m: number;
  alignment: {
    runs: number;
    avg_shift_cm: number | null;
    max_shift_cm: number | null;
    avg_abs_yaw_deg: number | null;
    avg_fit: number | null;
  };
  per_route: Record<string, { runs: number; done: number; success_rate: number | null; avg_duration_s: number | null; avg_blocked_s: number | null }>;
};

const RESULT_STYLE: Record<string, string> = {
  done: "bg-[#eaf7f2] text-[#00866a]",
  aborted: "bg-[#fdecec] text-[#b42020]",
  cancelled: "bg-[#f0f2f3] text-[#566373]",
  error: "bg-[#fdecec] text-[#b42020]",
};
const BAR_COLOR: Record<string, string> = { done: "#009b77", aborted: "#d62828", cancelled: "#aab3ba", error: "#d62828" };

function fmtDuration(s: number | null | undefined) {
  if (s === null || s === undefined) return "—";
  const m = Math.floor(s / 60);
  return m ? `${m} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-[#d8dde1] bg-white p-5">
      <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">{label}</p>
      <p className="mt-2 text-[28px] font-bold tracking-[-0.03em] text-[#292f33]">{value}</p>
      {sub && <p className="mt-1 text-[12px] text-[#87919c]">{sub}</p>}
    </div>
  );
}

export default function EvaluationPage() {
  const { ensurePin, forgetPin, pinDialog } = usePin();
  const [runs, setRuns] = useState<Run[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [routes, setRoutes] = useState<string[]>([]);
  const [route, setRoute] = useState("");
  const [period, setPeriod] = useState<"today" | "7d" | "all">("all");
  const [showExcluded, setShowExcluded] = useState(true);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});

  const since = useMemo(() => {
    if (period === "all") return "";
    const d = new Date();
    if (period === "7d") d.setDate(d.getDate() - 7);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T00:00:00`;
  }, [period]);

  const query = useMemo(() => {
    const q = new URLSearchParams();
    if (route) q.set("route", route);
    if (since) q.set("since", since);
    const s = q.toString();
    return s ? `?${s}` : "";
  }, [route, since]);

  const load = useCallback(async () => {
    try {
      const data = await getJson<{ runs: Run[]; stats: Stats; routes: string[] }>(`/api/runs${query}`);
      setRuns(data.runs);
      setStats(data.stats);
      setRoutes(data.routes);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [query]);

  useEffect(() => {
    void load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  async function saveMeta(run: Run, change: { note?: string; excluded?: boolean }) {
    const pin = await ensurePin();
    if (!pin) return;
    try {
      await sendJson("PUT", `/api/runs/${encodeURIComponent(run.id)}`, { pin, ...change });
      await load();
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      setError(text);
    }
  }

  const visible = showExcluded ? runs : runs.filter((r) => !r.excluded);
  const chartRuns = [...visible].reverse().slice(-40);
  const maxDur = Math.max(60, ...chartRuns.map((r) => r.duration_s || 0));

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {pinDialog}
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Evaluation</h1>
          </div>
          <p className="text-[13px] text-[#657078]">Every guide and tour run, logged automatically by G1</p>
          <div className="ml-auto flex flex-wrap items-center gap-3 text-[13px]">
            <select
              value={route}
              onChange={(e) => setRoute(e.target.value)}
              className="rounded border border-[#c6ccd1] bg-white px-3 py-2"
            >
              <option value="">All routes</option>
              {routes.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <div className="flex overflow-hidden rounded border border-[#c6ccd1]">
              {(["today", "7d", "all"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`px-3 py-2 font-bold ${period === p ? "bg-[#009b77] text-white" : "bg-white text-[#566373]"}`}
                >
                  {p === "today" ? "Today" : p === "7d" ? "7 days" : "All"}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 font-semibold text-[#566373]">
              <input type="checkbox" checked={showExcluded} onChange={(e) => setShowExcluded(e.target.checked)} />
              Show excluded
            </label>
            <a
              href={`${apiBase()}/api/runs/export.csv${query}`}
              className="rounded bg-[#009b77] px-4 py-2 font-bold text-white hover:bg-[#00866a]"
            >
              ⬇ CSV
            </a>
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-[1600px] space-y-6 px-6 py-6 md:px-10">
        {error && <p className="rounded bg-[#fdecec] p-3 text-[13px] font-semibold text-[#b42020]">{error}</p>}

        {/* KPI tiles */}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
          <Tile label="Runs" value={String(stats?.runs ?? "—")} sub={stats?.excluded ? `${stats.excluded} excluded` : undefined} />
          <Tile
            label="Success rate"
            value={stats?.success_rate != null ? `${Math.round(stats.success_rate * 100)} %` : "—"}
            sub={stats ? `${stats.done} done · ${stats.aborted} aborted · ${stats.cancelled} cancelled` : undefined}
          />
          <Tile label="Avg duration" value={fmtDuration(stats?.avg_duration_s)} sub="finished runs" />
          <Tile label="Avg blocked" value={stats?.avg_blocked_s != null ? `${stats.avg_blocked_s} s` : "—"} sub="per run" />
          <Tile
            label="HOME correction"
            value={stats?.alignment.avg_shift_cm != null ? `${stats.alignment.avg_shift_cm} cm` : "—"}
            sub={
              stats?.alignment.avg_abs_yaw_deg != null
                ? `${stats.alignment.avg_abs_yaw_deg}° avg · max ${stats.alignment.max_shift_cm} cm`
                : "no aligned runs yet"
            }
          />
          <Tile label="Distance walked" value={stats ? `${stats.total_distance_m} m` : "—"} sub="autonomous" />
        </div>

        {/* chart + per route */}
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5 xl:col-span-2">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Duration per run</h2>
            {chartRuns.length ? (
              <div className="mt-4">
                <div className="flex h-[200px] items-end gap-1.5 border-b border-l border-[#d8dde1] pl-1">
                  {chartRuns.map((r) => (
                    <div
                      key={r.id}
                      title={`${r.started.replace("T", " ")} · ${r.route} · ${r.result} · ${fmtDuration(r.duration_s)}`}
                      className="min-w-[8px] flex-1 rounded-t"
                      style={{
                        height: `${Math.max(2, ((r.duration_s || 0) / maxDur) * 100)}%`,
                        background: BAR_COLOR[r.result] || "#aab3ba",
                        opacity: r.excluded ? 0.3 : 1,
                      }}
                    />
                  ))}
                </div>
                <div className="mt-2 flex justify-between text-[11px] text-[#87919c]">
                  <span>oldest</span>
                  <span>
                    <span className="mr-3"><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-[#009b77]" />done</span>
                    <span className="mr-3"><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-[#d62828]" />aborted</span>
                    <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-[#aab3ba]" />cancelled</span>
                  </span>
                  <span>newest · max {fmtDuration(maxDur)}</span>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-[13px] text-[#657078]">No runs yet. Start a tour – it appears here automatically.</p>
            )}
          </section>

          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Per route</h2>
            <table className="mt-3 w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-[0.06em] text-[#87919c]">
                  <th className="pb-2">Route</th>
                  <th className="pb-2">Runs</th>
                  <th className="pb-2">Success</th>
                  <th className="pb-2">Avg time</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(stats?.per_route || {}).map(([name, v]) => (
                  <tr key={name} className="border-t border-[#eef0f2]">
                    <td className="py-2 font-semibold text-[#292f33]">{name}</td>
                    <td className="py-2">{v.runs}</td>
                    <td className="py-2">{v.success_rate != null ? `${Math.round(v.success_rate * 100)} %` : "—"}</td>
                    <td className="py-2">{fmtDuration(v.avg_duration_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>

        {/* table */}
        <section className="overflow-x-auto rounded-lg border border-[#d8dde1] bg-white">
          <table className="w-full min-w-[1100px] text-[13px]">
            <thead className="bg-[#fafbfb]">
              <tr className="text-left text-[11px] uppercase tracking-[0.06em] text-[#87919c]">
                <th className="px-4 py-3">Started</th>
                <th className="px-4 py-3">Route</th>
                <th className="px-4 py-3">Result</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">Progress</th>
                <th className="px-4 py-3">Blocked</th>
                <th className="px-4 py-3">HOME correction</th>
                <th className="px-4 py-3">Note</th>
                <th className="px-4 py-3">Exclude</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const a = r.alignment || {};
                const note = notes[r.id] ?? r.note;
                return (
                  <tr key={r.id} className={`border-t border-[#eef0f2] ${r.excluded ? "opacity-50" : ""}`}>
                    <td className="whitespace-nowrap px-4 py-2.5 text-[#566373]">{r.started.replace("T", " ")}</td>
                    <td className="px-4 py-2.5 font-semibold text-[#292f33]">
                      {r.route}
                      <span className="ml-1 font-normal text-[#87919c]">
                        {r.kind === "tour" ? `· ${r.stops} stops` : ""} · {r.lang?.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${RESULT_STYLE[r.result] || ""}`} title={r.message}>
                        {r.result}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5">{fmtDuration(r.duration_s)}</td>
                    <td className="px-4 py-2.5">{Math.round((r.progress || 0) * 100)} %</td>
                    <td className="whitespace-nowrap px-4 py-2.5">
                      {r.blocked_count ? `${r.blocked_count}× · ${r.blocked_s} s` : "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-[#566373]">
                      {a.used
                        ? `${Math.round(Math.hypot(a.dx || 0, a.dy || 0) * 100)} cm · ${a.dyaw_deg?.toFixed(1)}° · ${Math.round((a.fit || 0) * 100)}%`
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <input
                        value={note}
                        placeholder="e.g. visitors present"
                        onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })}
                        onBlur={() => {
                          if (note !== r.note) void saveMeta(r, { note });
                        }}
                        className="w-[220px] rounded border border-transparent px-2 py-1 hover:border-[#d8dde1] focus:border-[#009b77] focus:outline-none"
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <input type="checkbox" checked={r.excluded} onChange={(e) => void saveMeta(r, { excluded: e.target.checked })} />
                    </td>
                  </tr>
                );
              })}
              {!visible.length && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-[13px] text-[#657078]">
                    No runs for this filter yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
        <p className="text-[12px] text-[#87919c]">
          Tip: mark test runs as “excluded” so they don’t count in the statistics. Notes and exclude flags are kept in
          Studio; the robot’s log file is never changed.
        </p>
      </div>
    </div>
  );
}
