"use client";

// G1 Studio - Safety tests
// Measures how fast G1 really stops (from G1's own measured speed, 50 Hz):
// STOP button, software E-STOP, obstacle in the path during a guide run.

import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase, getJson, postJson } from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";

type Result = {
  time: string;
  kind: string;
  label: string;
  ok: boolean;
  reaction_s?: number;
  stop_distance_m?: number;
  speed_at_trigger?: number;
  decel_mps2?: number;
  reason?: string;
  note?: string;
  guide_message?: string;
  samples?: [number, number][];
};
type KindStats = {
  label: string;
  n: number;
  failed: number;
  reaction_mean_s: number | null;
  reaction_sd_s: number | null;
  reaction_max_s: number | null;
  distance_mean_m: number | null;
  distance_max_m: number | null;
};
type Status = {
  running: { kind: string; label: string; state: string } | null;
  last: Result | null;
  motion: { speed_mps: number | null; yaw_rate: number | null; age_s: number | null } | null;
};

const TESTS = [
  {
    kind: "stop",
    title: "STOP button",
    how: "Let G1 walk straight (joystick in the app, or a guide). Then press the button – Studio sends STOP and measures until G1 stands.",
  },
  {
    kind: "estop",
    title: "Software E-STOP",
    how: "Same as STOP, but with the E-STOP. Afterwards reset the E-STOP in the G1 Remote app (operator screen).",
  },
  {
    kind: "obstacle",
    title: "Obstacle in the path",
    how: "Arm the test, start a guide or tour, then step into G1's path (≥ 1.5 m ahead). Measured from 'blocked' to standstill.",
  },
];

function SpeedCurve({ points, height = 80 }: { points: [number, number][]; height?: number }) {
  if (points.length < 2) return <div style={{ height }} className="flex items-center text-[11px] text-[#87919c]">no data</div>;
  const t0 = points[0][0];
  const t1 = points[points.length - 1][0];
  const vmax = Math.max(0.3, ...points.map((p) => p[1]));
  const w = 400;
  const x = (t: number) => ((t - t0) / Math.max(0.001, t1 - t0)) * w;
  const y = (v: number) => height - (v / vmax) * (height - 6) - 3;
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const zero = points.some((p) => p[0] === 0) || (t0 < 0 && t1 > 0);
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <line x1="0" x2={w} y1={y(0.05)} y2={y(0.05)} stroke="#cfe9df" strokeDasharray="4 3" />
      {zero && <line x1={x(0)} x2={x(0)} y1="0" y2={height} stroke="#d62828" strokeDasharray="3 3" />}
      <path d={d} fill="none" stroke="#2f6fdb" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function SafetyTestsPage() {
  const { ensurePin, forgetPin, pinDialog } = usePin();
  const [status, setStatus] = useState<Status | null>(null);
  const [live, setLive] = useState<[number, number][]>([]);
  const [results, setResults] = useState<{ items: Result[]; stats: Record<string, KindStats> } | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [estopConfirm, setEstopConfirm] = useState(false);
  const t0 = useRef(Date.now());

  const loadResults = useCallback(async () => {
    try {
      setResults(await getJson("/api/safety/results"));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void loadResults();
    let alive = true;
    let wasRunning = false;
    const poll = async () => {
      try {
        const s = await getJson<Status>("/api/safety/status", 2000);
        if (!alive) return;
        setStatus(s);
        const now = (Date.now() - t0.current) / 1000;
        const v = s.motion?.speed_mps;
        if (v != null && (s.motion?.age_s ?? 9) < 1) {
          setLive((l) => [...l.filter((p) => p[0] > now - 15), [now, v]]);
        }
        if (wasRunning && !s.running) void loadResults();
        wasRunning = !!s.running;
      } catch {
        if (alive) setStatus(null);
      }
    };
    const t = setInterval(poll, 250);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [loadResults]);

  async function run(kind: string) {
    setError("");
    const pin = await ensurePin();
    if (!pin) return;
    try {
      await postJson("/api/safety/test", { pin, kind, note });
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      setError(text);
    }
  }

  const speed = status?.motion?.speed_mps;
  const last = status?.last;

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {pinDialog}
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#d62828]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Safety tests</h1>
          </div>
          <p className="text-[13px] text-[#657078]">Measured stop reaction times and distances (G1’s own speed, 50 Hz)</p>
          <a href={`${apiBase()}/api/safety/export.csv`} className="ml-auto rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white">
            ⬇ CSV
          </a>
        </div>
        {error && <div className="border-t border-[#f3c6c6] bg-[#fdecec] px-6 py-2 text-center text-[13px] font-semibold text-[#b42020]">{error}</div>}
      </section>

      <div className="mx-auto max-w-[1500px] space-y-6 px-6 py-6 md:px-10">
        <p className="rounded border border-[#f3dfb5] bg-[#fff6e5] px-4 py-3 text-[13px] text-[#7a520e]">
          Only with free space around G1, at walking speed, with a second person at the physical remote. Never test with
          visitors nearby.
        </p>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          {/* live speed */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5 xl:col-span-1">
            <h2 className="text-[12px] font-bold uppercase tracking-[0.08em] text-[#36414b]">G1 speed (live)</h2>
            <p className="mt-2 text-[40px] font-bold leading-none text-[#292f33]">
              {speed != null ? speed.toFixed(2) : "—"} <span className="text-[16px] text-[#657078]">m/s</span>
            </p>
            <div className="mt-3">
              <SpeedCurve points={live} />
            </div>
            <p className="mt-1 text-[11px] text-[#87919c]">last 15 s · dashed line = 0.05 m/s (standing)</p>
            <label className="mt-4 block text-[12px] font-semibold text-[#566373]">
              Note for the next test
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. straight corridor, 0.25 m/s"
                className="mt-1 w-full rounded border border-[#c6ccd1] px-3 py-2 text-[13px] outline-none focus:border-[#009b77]"
              />
            </label>
          </section>

          {/* tests */}
          <section className="space-y-3 xl:col-span-2">
            {TESTS.map((t) => {
              const running = status?.running?.kind === t.kind;
              return (
                <div key={t.kind} className="flex flex-wrap items-center gap-4 rounded-lg border border-[#d8dde1] bg-white p-4">
                  <div className="min-w-[260px] flex-1">
                    <p className="text-[15px] font-bold text-[#292f33]">{t.title}</p>
                    <p className="mt-1 text-[12px] leading-[17px] text-[#657078]">{t.how}</p>
                  </div>
                  {running ? (
                    <div className="flex items-center gap-3">
                      <span className="text-[13px] font-bold text-[#b7790f]">
                        {status?.running?.state === "armed" ? "Armed – waiting for 'blocked'…" : "Measuring…"}
                      </span>
                      <button onClick={() => void postJson("/api/safety/cancel")} className="rounded border border-[#c6ccd1] px-3 py-2 text-[12px] font-bold">
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      disabled={!!status?.running}
                      onClick={() => (t.kind === "estop" ? setEstopConfirm(true) : void run(t.kind))}
                      className={`rounded px-5 py-2.5 text-[13px] font-bold text-white disabled:opacity-40 ${
                        t.kind === "obstacle" ? "bg-[#2f6fdb]" : "bg-[#d62828]"
                      }`}
                    >
                      {t.kind === "obstacle" ? "Arm test" : `Trigger ${t.title}`}
                    </button>
                  )}
                </div>
              );
            })}

            {last && (
              <div className={`rounded-lg border p-4 ${last.ok ? "border-[#cfe9df] bg-[#f4fbf8]" : "border-[#f3c6c6] bg-[#fdecec]"}`}>
                <p className="text-[13px] font-bold text-[#292f33]">
                  Last test: {last.label} · {last.time.replace("T", " ")}
                </p>
                {last.ok ? (
                  <div className="mt-2 grid grid-cols-2 gap-4 md:grid-cols-4">
                    <div>
                      <p className="text-[11px] text-[#657078]">Reaction to standstill</p>
                      <p className="text-[24px] font-bold text-[#292f33]">{last.reaction_s?.toFixed(2)} s</p>
                    </div>
                    <div>
                      <p className="text-[11px] text-[#657078]">Stopping distance</p>
                      <p className="text-[24px] font-bold text-[#292f33]">{((last.stop_distance_m ?? 0) * 100).toFixed(0)} cm</p>
                    </div>
                    <div>
                      <p className="text-[11px] text-[#657078]">Speed at trigger</p>
                      <p className="text-[24px] font-bold text-[#292f33]">{last.speed_at_trigger?.toFixed(2)} m/s</p>
                    </div>
                    <div>
                      <SpeedCurve points={last.samples || []} height={60} />
                      <p className="text-[10px] text-[#87919c]">red line = trigger</p>
                    </div>
                  </div>
                ) : (
                  <p className="mt-1 text-[13px] text-[#b42020]">{last.reason}</p>
                )}
              </div>
            )}
          </section>
        </div>

        {/* stats */}
        <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
          <h2 className="text-[12px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Results (for the thesis)</h2>
          <table className="mt-3 w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-[0.06em] text-[#87919c]">
                <th className="py-2">Test</th>
                <th>n</th>
                <th>Reaction mean ± SD</th>
                <th>Reaction max</th>
                <th>Distance mean</th>
                <th>Distance max</th>
                <th>Failed</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(results?.stats || {}).map(([k, s]) => (
                <tr key={k} className="border-t border-[#eef0f2]">
                  <td className="py-2 font-semibold text-[#292f33]">{s.label}</td>
                  <td>{s.n}</td>
                  <td>
                    {s.reaction_mean_s != null ? `${s.reaction_mean_s.toFixed(2)} s` : "—"}
                    {s.reaction_sd_s != null ? ` ± ${s.reaction_sd_s.toFixed(2)}` : ""}
                  </td>
                  <td>{s.reaction_max_s != null ? `${s.reaction_max_s.toFixed(2)} s` : "—"}</td>
                  <td>{s.distance_mean_m != null ? `${(s.distance_mean_m * 100).toFixed(0)} cm` : "—"}</td>
                  <td>{s.distance_max_m != null ? `${(s.distance_max_m * 100).toFixed(0)} cm` : "—"}</td>
                  <td className={s.failed ? "font-bold text-[#d62828]" : ""}>{s.failed}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3 className="mt-6 text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">All tests</h3>
          <ul className="mt-2 divide-y divide-[#eef0f2]">
            {(results?.items || []).slice(0, 40).map((r, i) => (
              <li key={i} className="flex flex-wrap gap-x-4 py-2 text-[12px]">
                <span className="w-[140px] text-[#566373]">{r.time.replace("T", " ")}</span>
                <span className="w-[180px] font-semibold text-[#292f33]">{r.label}</span>
                {r.ok ? (
                  <span>
                    {r.reaction_s?.toFixed(2)} s · {((r.stop_distance_m ?? 0) * 100).toFixed(0)} cm · from {r.speed_at_trigger?.toFixed(2)} m/s
                  </span>
                ) : (
                  <span className="text-[#d62828]">failed: {r.reason}</span>
                )}
                {r.note && <span className="text-[#87919c]">“{r.note}”</span>}
              </li>
            ))}
            {!results?.items.length && <li className="py-2 text-[12px] text-[#87919c]">No tests yet.</li>}
          </ul>
        </section>
      </div>

      {estopConfirm && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/40">
          <div className="w-[420px] rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-[18px] font-bold text-[#8f1010]">E-STOP test</h2>
            <p className="mt-3 text-[14px] text-[#36414b]">
              G1 must be walking now. After the test the E-STOP stays active until you reset it in the G1 Remote app.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button onClick={() => setEstopConfirm(false)} className="rounded px-4 py-2 text-[13px] font-semibold text-[#566373]">
                Cancel
              </button>
              <button
                onClick={() => {
                  setEstopConfirm(false);
                  void run("estop");
                }}
                className="rounded bg-[#8f1010] px-4 py-2 text-[13px] font-bold text-white"
              >
                Trigger E-STOP
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
