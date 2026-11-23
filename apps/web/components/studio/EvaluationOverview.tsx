"use client";

// Evaluation -> "All features": conversations, autonomous walking, point demo and shows in one view,
// recorded automatically. Every block exports as CSV for the thesis evaluation chapter.

import { useEffect, useState } from "react";
import { apiBase, getJson } from "@/lib/g1api";

type Stat = { n: number; mean: number | null; median: number | null; p90: number | null; min: number | null; max: number | null };
type Summary = {
  days: number;
  conversations: {
    total: number; operator_sentences: number; paused_refusals: number; by_source: Record<string, number>;
    by_language: Record<string, number>; answer_s: Record<string, Stat>; answer_s_all: Stat; weak_answers: number; weak_rate: number | null;
  };
  walks: {
    runs: number; done: number; success_rate: number | null; total_distance_m: number;
    autonomous_goto: { runs: number; done: number; success_rate: number | null };
    recorded_paths: number; recorded_m: number; blocked_events: number;
  };
  points: { runs: number; done: number; success_rate: number | null; results: Record<string, number>; duration_s: Stat; by_target: Record<string, { runs: number; done: number }> };
  shows: { runs: number; done: number; stopped: number; failed: number; success_rate: number | null; duration_s: Stat; failed_step_types: Record<string, number> };
  daily: { day: string; conversations: number; walks: number; points: number; shows: number }[];
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)} %`);
const sec = (v: number | null | undefined) => (v == null ? "—" : `${v} s`);
const SRC: Record<string, string> = { app: "App", mic: "G1 microphone", studio: "Studio" };

export default function EvaluationOverview() {
  const [days, setDays] = useState(0);
  const [s, setS] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getJson<Summary>(`/api/evaluation/summary?days=${days}`, 8000)
        .then((r) => { if (alive) { setS(r); setError(null); } })
        .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    void load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [days]);

  const c = s?.conversations;
  return (
    <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">All features</h2>
          <p className="text-[12px] text-[#657078]">Conversations, autonomous walking, point demo and shows – recorded automatically</p>
        </div>
        <div className="ml-auto flex overflow-hidden rounded border border-[#c6ccd1] text-[12px] font-bold">
          {([[1, "Today"], [7, "7 days"], [30, "30 days"], [0, "All"]] as const).map(([d, l]) => (
            <button key={d} onClick={() => setDays(d)} className={`px-3 py-1.5 ${days === d ? "bg-[#009b77] text-white" : "bg-white text-[#566373]"}`}>{l}</button>
          ))}
        </div>
      </div>
      {error && <p className="mt-3 rounded bg-[#fdecec] p-2 text-[12px] font-semibold text-[#b42020]">{error}</p>}

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Conversations" value={String(c?.total ?? "—")} sub={c ? `${c.by_source.app ?? 0} app · ${c.by_source.mic ?? 0} mic · ${c.by_language.de ?? 0} German` : ""} />
        <Kpi label="Answer time" value={sec(c?.answer_s_all.median)} sub={c?.answer_s_all.n ? `median · mean ${c.answer_s_all.mean} s · p90 ${c.answer_s_all.p90} s` : "no timed answers yet"} />
        <Kpi label="Good answers" value={c?.weak_rate != null ? pct(1 - c.weak_rate) : "—"} sub={c ? `${c.weak_answers} “I don't know”` : ""} />
        <Kpi label="Autonomous walks" value={pct(s?.walks.autonomous_goto.success_rate)} sub={s ? `${s.walks.autonomous_goto.done}/${s.walks.autonomous_goto.runs} arrived · ${s.walks.recorded_m} m recorded` : ""} />
        <Kpi label="Point demo" value={pct(s?.points.success_rate)} sub={s ? `${s.points.done}/${s.points.runs} done · ${sec(s.points.duration_s.median)} median` : ""} />
        <Kpi label="Shows" value={pct(s?.shows.success_rate)} sub={s ? `${s.shows.done} done · ${s.shows.failed} failed · ${s.shows.stopped} stopped` : ""} />
      </div>

      {s && (
        <div className="mt-5 grid grid-cols-1 gap-6 xl:grid-cols-[1.2fr_1fr]">
          <div>
            <h3 className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Activity per day</h3>
            <div className="mt-2 flex flex-col gap-3">
              {(["conversations", "walks", "points", "shows"] as const).map((k) => (
                <DayBars key={k} label={{ conversations: "Conversations", walks: "Walks / tours", points: "Point demo runs", shows: "Shows" }[k]}
                  days={s.daily.map((d) => ({ day: d.day, v: d[k] }))} />
              ))}
            </div>
          </div>
          <div>
            <h3 className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Answer time by source</h3>
            <table className="mt-2 w-full text-[12px]">
              <thead>
                <tr className="text-left text-[#657078]"><th className="py-1 font-semibold">Source</th><th className="font-semibold">n</th><th className="font-semibold">median</th><th className="font-semibold">mean</th><th className="font-semibold">p90</th><th className="font-semibold">max</th></tr>
              </thead>
              <tbody className="tabular-nums text-[#292f33]">
                {Object.entries(c!.answer_s).map(([k, v]) => (
                  <tr key={k} className="border-t border-[#eef0f1]"><td className="py-1.5 font-semibold">{SRC[k] || k}</td><td>{v.n}</td><td>{sec(v.median)}</td><td>{sec(v.mean)}</td><td>{sec(v.p90)}</td><td>{sec(v.max)}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-[11px] text-[#8a949c]">App / Studio: question received → answer ready. Microphone: end of speech → answer ready (includes speech recognition).</p>

            {Object.keys(s.points.results).length > 0 && (
              <>
                <h3 className="mt-4 text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Point demo results</h3>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {Object.entries(s.points.results).map(([k, v]) => (
                    <span key={k} className="rounded bg-[#f0f2f3] px-2 py-0.5 text-[12px] text-[#36414b]">{k.replace(/_/g, " ")}: <b>{v}</b></span>
                  ))}
                </div>
              </>
            )}
            {Object.keys(s.shows.failed_step_types).length > 0 && (
              <>
                <h3 className="mt-4 text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Show steps that failed</h3>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {Object.entries(s.shows.failed_step_types).map(([k, v]) => (
                    <span key={k} className="rounded bg-[#fdf0f0] px-2 py-0.5 text-[12px] text-[#a33]">{k}: <b>{v}</b></span>
                  ))}
                </div>
              </>
            )}

            <h3 className="mt-4 text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Export (CSV, all data)</h3>
            <div className="mt-1 flex flex-wrap gap-2">
              {(["conversations", "paths", "points", "shows"] as const).map((k) => (
                <a key={k} href={`${apiBase()}/api/evaluation/export/${k}.csv`}
                  className="rounded border border-[#c6ccd1] px-3 py-1.5 text-[12px] font-bold text-[#36414b] hover:border-[#009b77]">
                  ⬇ {k === "paths" ? "walk paths" : k === "points" ? "point demo" : k}
                </a>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-[#e0e3e1] bg-[#f7f8f7] px-3 py-2.5">
      <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">{label}</div>
      <div className="mt-0.5 text-[22px] font-bold text-[#292f33]">{value}</div>
      {sub && <div className="truncate text-[11px] text-[#8a949c]" title={sub}>{sub}</div>}
    </div>
  );
}

// one small bar row per measure (small multiples: one hue, no legend needed)
function DayBars({ label, days }: { label: string; days: { day: string; v: number }[] }) {
  const max = Math.max(1, ...days.map((d) => d.v));
  const total = days.reduce((a, d) => a + d.v, 0);
  const W = 100 / days.length;
  return (
    <div>
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="font-semibold text-[#36414b]">{label}</span>
        <span className="tabular-nums text-[#657078]">{total} total</span>
      </div>
      <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="mt-1 h-[44px] w-full">
        <line x1={0} x2={100} y1={23.8} y2={23.8} stroke="#d8dde1" strokeWidth={0.4} vectorEffect="non-scaling-stroke" />
        {days.map((d, i) => {
          const h = (d.v / max) * 22;
          return (
            <g key={d.day}>
              <title>{`${d.day}: ${d.v}`}</title>
              <rect x={i * W} y={0} width={W} height={24} fill="transparent" />
              {d.v > 0 && <rect x={i * W + W * 0.15} y={24 - h} width={W * 0.7} height={h} rx={0.6} fill="#009b77" />}
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between text-[10px] text-[#8a949c]">
        <span>{days[0]?.day.slice(5)}</span><span>{days[days.length - 1]?.day.slice(5)}</span>
      </div>
    </div>
  );
}
