"use client";

// G1 Studio - Simulation & path planner
// Runs the REAL guide code against a simulated G1 on the Session 03 map
// (walls + virtual people as LiDAR points, real speed limits) and plays it back.

import { useEffect, useMemo, useRef, useState } from "react";
import LabMapCanvas, { MapInfo, MapRoute, Pose } from "@/components/studio/LabMapCanvas";
import { apiBase, getJson, postJson } from "@/lib/g1api";

type Person = { x: number; y: number; t_from: number; t_to: number };
type Frame = [number, number, number, number, string, number, number]; // t x y yaw state stop progress
type SimResult = {
  result: string;
  message: string;
  duration_s: number;
  blocked_s: number;
  frames: Frame[];
  events: [number, string, string][];
  states: [number, string, string][];
  narrow_spots: { x: number; y: number; clearance_m: number }[];
  end_error_m: number;
  route: string;
  map_source?: string;
};
type Plan = { path: [number, number][]; length_m: number; min_clearance_m: number };
type Mode = "none" | "plan_start" | "plan_goal" | "person";

const STATE_TEXT: Record<string, string> = {
  starting: "Starting",
  guiding: "Walking",
  explaining: "Explaining",
  blocked: "Blocked – waiting",
  arrived: "Arrived",
  returning: "Walking home",
  done: "Finished",
  aborted: "Aborted",
  cancelled: "Cancelled",
};

function fmt(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export default function SimulationPage() {
  const [info, setInfo] = useState<(MapInfo & { alignment: { home: Pose | null } }) | null>(null);
  const [routes, setRoutes] = useState<MapRoute[]>([]);
  const [routeName, setRouteName] = useState("");
  const [lang, setLang] = useState<"en" | "de">("en");
  const [people, setPeople] = useState<Person[]>([]);
  const [personFrom, setPersonFrom] = useState(0);
  const [personFor, setPersonFor] = useState(30);
  const [mode, setMode] = useState<Mode>("none");
  const [planStart, setPlanStart] = useState<[number, number] | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [result, setResult] = useState<SimResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const raf = useRef<number | null>(null);
  const last = useRef<number | null>(null);

  useEffect(() => {
    Promise.all([
      getJson<MapInfo & { alignment: { home: Pose | null } }>("/api/map/info"),
      getJson<MapRoute[]>("/api/map/routes"),
    ])
      .then(([i, r]) => {
        setInfo(i);
        setRoutes(r);
        setRouteName(r.find((x) => x.kind === "tour")?.name || r[0]?.name || "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // playback
  useEffect(() => {
    if (!playing || !result) return;
    const tick = (now: number) => {
      if (last.current !== null) {
        const dt = ((now - last.current) / 1000) * speed;
        setTime((t) => {
          const nt = t + dt;
          if (nt >= result.duration_s) {
            setPlaying(false);
            return result.duration_s;
          }
          return nt;
        });
      }
      last.current = now;
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      last.current = null;
    };
  }, [playing, speed, result]);

  const frame = useMemo<Frame | null>(() => {
    if (!result?.frames.length) return null;
    const fr = result.frames;
    let lo = 0;
    let hi = fr.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (fr[mid][0] <= time) lo = mid;
      else hi = mid - 1;
    }
    return fr[lo];
  }, [result, time]);

  const trail = useMemo<[number, number][]>(
    () => (result ? result.frames.filter((f) => f[0] <= time).map((f) => [f[1], f[2]]) : []),
    [result, time],
  );

  const recentEvents = useMemo(
    () => (result ? result.events.filter((e) => e[0] <= time && e[1] === "say").slice(-6).reverse() : []),
    [result, time],
  );

  async function runSim(kind: "route" | "plan") {
    setBusy(true);
    setError("");
    setPlaying(false);
    try {
      const res =
        kind === "route"
          ? await postJson<SimResult>("/api/sim/run", { route: routeName, lang, people, return_home: true }, 120000)
          : await postJson<SimResult>("/api/sim/run_path", { path: plan?.path, lang, people }, 120000);
      setResult(res);
      setTime(0);
      setPlaying(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onMapClick(p: { x: number; y: number }) {
    if (mode === "person") {
      setPeople((ps) => [...ps, { x: p.x, y: p.y, t_from: personFrom, t_to: personFor > 0 ? personFrom + personFor : 1e9 }]);
      return;
    }
    if (mode === "plan_start") {
      setPlanStart([p.x, p.y]);
      setPlan(null);
      setMode("plan_goal");
      return;
    }
    if (mode === "plan_goal" && planStart) {
      setMode("none");
      setBusy(true);
      setError("");
      try {
        const res = await postJson<Plan>("/api/sim/plan", { start: planStart, goal: [p.x, p.y] }, 60000);
        setPlan(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    }
  }

  const selected = routes.find((r) => r.name === routeName);
  const overlayPaths = [
    ...(selected?.path && !plan ? [{ points: selected.path, color: "rgba(0,155,119,0.55)", width: 4 }] : []),
    ...(plan ? [{ points: plan.path, color: "#9333ea", dash: true, width: 3 }] : []),
    ...(trail.length > 1 ? [{ points: trail, color: "#2f6fdb", width: 2 }] : []),
  ];
  const overlayCircles = [
    ...people.map((p, i) => {
      const active = !result || (time >= p.t_from && time < p.t_to);
      return {
        x: p.x,
        y: p.y,
        r: 0.25,
        color: active ? "rgba(217,119,6,0.85)" : "rgba(217,119,6,0.25)",
        label: `P${i + 1}${p.t_to < 1e8 ? ` ${p.t_from}–${p.t_to}s` : ""}`,
      };
    }),
    ...(planStart && (mode === "plan_goal" || plan) ? [{ x: planStart[0], y: planStart[1], r: 0.15, color: "#9333ea", label: "A" }] : []),
    ...(plan ? [{ x: plan.path[plan.path.length - 1][0], y: plan.path[plan.path.length - 1][1], r: 0.15, color: "#9333ea", label: "B" }] : []),
    ...(result?.narrow_spots || []).map((s) => ({ x: s.x, y: s.y, r: 0.2, color: "rgba(214,40,40,0.6)", label: `${Math.round(s.clearance_m * 100)} cm` })),
  ];
  const simPose = frame ? { x: frame[1], y: frame[2], yaw: frame[3] } : null;
  const stopTitle = frame && selected && frame[5] > 0 ? selected.stops[frame[5] - 1]?.title_en : "";

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1700px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#2f6fdb]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Simulation</h1>
          </div>
          <p className="text-[13px] text-[#657078]">
            Real guide code · simulated G1, LiDAR and people · Session 03 map · the real robot does not move
          </p>
          {busy && <span className="ml-auto text-[13px] font-bold text-[#2f6fdb]">Working…</span>}
        </div>
        {error && <div className="border-t border-[#f3c6c6] bg-[#fdecec] px-6 py-2 text-center text-[13px] font-semibold text-[#b42020]">{error}</div>}
      </section>

      <div className="mx-auto grid max-w-[1700px] grid-cols-1 gap-6 px-6 py-6 md:px-10 xl:grid-cols-[1fr_380px]">
        <div className="flex flex-col gap-3">
          <div className="h-[calc(100vh-300px)] min-h-[480px] rounded-lg border border-[#d8dde1] bg-white p-2">
            {info && (
              <LabMapCanvas
                info={info}
                imageUrl={`${apiBase()}/api/map/image.png`}
                routes={[]}
                visible={{}}
                home={info.alignment?.home ?? null}
                live={null}
                showLabels
                placingHome={false}
                draftHome={null}
                onDraftHome={() => undefined}
                overlayPaths={overlayPaths}
                overlayCircles={overlayCircles}
                simPose={simPose}
                onMapClick={mode !== "none" ? (p) => void onMapClick(p) : undefined}
              />
            )}
          </div>

          {/* playback bar */}
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#d8dde1] bg-white px-4 py-3">
            <button
              disabled={!result}
              onClick={() => {
                if (result && time >= result.duration_s) setTime(0);
                setPlaying(!playing);
              }}
              className="w-[90px] rounded bg-[#2f6fdb] px-3 py-1.5 text-[13px] font-bold text-white disabled:opacity-40"
            >
              {playing ? "❚❚ Pause" : "▶ Play"}
            </button>
            <input
              type="range"
              min={0}
              max={result?.duration_s || 0}
              step={0.25}
              value={time}
              onChange={(e) => {
                setPlaying(false);
                setTime(Number(e.target.value));
              }}
              className="min-w-[200px] flex-1"
              disabled={!result}
            />
            <span className="w-[110px] text-right font-mono text-[13px] text-[#36414b]">
              {fmt(time)} / {fmt(result?.duration_s || 0)}
            </span>
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="rounded border border-[#c6ccd1] px-2 py-1 text-[13px]">
              {[1, 5, 10, 20, 50].map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
            </select>
            {frame && (
              <span className="rounded-full bg-[#eef3fd] px-3 py-1 text-[12px] font-bold text-[#2f6fdb]">
                {STATE_TEXT[frame[4]] || frame[4]}
                {stopTitle ? ` · ${stopTitle}` : ""} · {Math.round(frame[6] * 100)}%
              </span>
            )}
          </div>
        </div>

        <aside className="space-y-6">
          {/* simulate a taught route / tour */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">1 · Simulate a tour or route</h2>
            <select
              value={routeName}
              onChange={(e) => {
                setRouteName(e.target.value);
                setPlan(null);
                setResult(null);
              }}
              className="mt-3 w-full rounded border border-[#c6ccd1] bg-white px-3 py-2 text-[14px]"
            >
              {routes.map((r) => (
                <option key={r.name} value={r.name}>
                  {r.kind === "tour" ? "Tour: " : "Route: "}
                  {r.title_en || r.name} · {r.length_m} m
                </option>
              ))}
            </select>
            <div className="mt-3 flex items-center gap-2">
              <div className="flex overflow-hidden rounded border border-[#c6ccd1]">
                {(["en", "de"] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => setLang(l)}
                    className={`px-3 py-1.5 text-[12px] font-bold ${lang === l ? "bg-[#2f6fdb] text-white" : "bg-white text-[#566373]"}`}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
              <button
                onClick={() => void runSim("route")}
                disabled={!routeName || busy}
                className="ml-auto rounded bg-[#2f6fdb] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
              >
                ▶ Simulate
              </button>
            </div>
            {selected?.alignment.source !== "scan" && (
              <p className="mt-2 text-[11px] text-[#9a6812]">Route not aligned to the map yet – position is approximate (Lab Map → Align to map).</p>
            )}
          </section>

          {/* planner */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">2 · Path planner (A*)</h2>
            <p className="mt-2 text-[12px] leading-[17px] text-[#657078]">
              Click start A and goal B on the map. The planner keeps ≥ 30 cm from walls and prefers the middle of corridors.
            </p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => {
                  setMode("plan_start");
                  setPlan(null);
                  setPlanStart(null);
                  setResult(null);
                }}
                className={`rounded border px-3 py-1.5 text-[12px] font-bold ${
                  mode === "plan_start" || mode === "plan_goal" ? "border-[#9333ea] bg-[#f6effe] text-[#9333ea]" : "border-[#c6ccd1] text-[#36414b]"
                }`}
              >
                {mode === "plan_start" ? "Click start A…" : mode === "plan_goal" ? "Click goal B…" : "Plan new path"}
              </button>
              <button
                onClick={() => void runSim("plan")}
                disabled={!plan || busy}
                className="ml-auto rounded bg-[#9333ea] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
              >
                ▶ Simulate path
              </button>
            </div>
            {plan && (
              <p className="mt-3 text-[12px] text-[#36414b]">
                Path: <b>{plan.length_m} m</b> · narrowest {Math.round(plan.min_clearance_m * 100)} cm from a wall · ≈{" "}
                {Math.round(plan.length_m / 0.22)} s walking
              </p>
            )}
            <p className="mt-2 text-[11px] text-[#87919c]">
              Planned paths are for planning and testing. The real G1 walks taught routes (global localization = future work).
            </p>
          </section>

          {/* people */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">3 · Virtual people</h2>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[12px] text-[#566373]">
              <label>
                appears at (s)
                <input type="number" min={0} value={personFrom} onChange={(e) => setPersonFrom(Number(e.target.value))} className="mt-1 w-full rounded border border-[#c6ccd1] px-2 py-1" />
              </label>
              <label>
                stays for (s, 0 = always)
                <input type="number" min={0} value={personFor} onChange={(e) => setPersonFor(Number(e.target.value))} className="mt-1 w-full rounded border border-[#c6ccd1] px-2 py-1" />
              </label>
            </div>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => setMode(mode === "person" ? "none" : "person")}
                className={`rounded border px-3 py-1.5 text-[12px] font-bold ${mode === "person" ? "border-[#d97706] bg-[#fff6e5] text-[#9a6812]" : "border-[#c6ccd1] text-[#36414b]"}`}
              >
                {mode === "person" ? "Click on the map… (done)" : "Add people"}
              </button>
              <button onClick={() => setPeople([])} disabled={!people.length} className="rounded border border-[#c6ccd1] px-3 py-1.5 text-[12px] font-bold text-[#36414b] disabled:opacity-40">
                Clear ({people.length})
              </button>
            </div>
            <p className="mt-2 text-[11px] text-[#87919c]">Run the simulation again after adding people.</p>
          </section>

          {/* results */}
          {result && (
            <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
              <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Result</h2>
              <dl className="mt-3 grid grid-cols-2 gap-y-2 text-[13px]">
                <dt className="text-[#657078]">Result</dt>
                <dd className={`font-bold ${result.result === "done" ? "text-[#00866a]" : "text-[#d62828]"}`}>{result.result}</dd>
                <dt className="text-[#657078]">Duration</dt>
                <dd className="font-bold">{fmt(result.duration_s)} min</dd>
                <dt className="text-[#657078]">Blocked</dt>
                <dd className="font-bold">{result.blocked_s} s</dd>
                <dt className="text-[#657078]">End error</dt>
                <dd className="font-bold">{Math.round(result.end_error_m * 100)} cm</dd>
              </dl>
              {result.result !== "done" && result.message && <p className="mt-2 text-[12px] text-[#d62828]">{result.message}</p>}
              {result.narrow_spots.length > 0 && (
                <p className="mt-3 rounded bg-[#fdecec] p-2 text-[12px] text-[#b42020]">
                  {result.narrow_spots.length} narrow spot{result.narrow_spots.length > 1 ? "s" : ""} (&lt; 25 cm to a wall, red on the map) – risk of
                  false “blocked” stops there.
                </p>
              )}
              <h3 className="mt-4 text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">G1 says</h3>
              <ul className="mt-2 space-y-1.5">
                {recentEvents.map((e, i) => (
                  <li key={i} className="text-[12px] leading-[16px] text-[#36414b]">
                    <span className="mr-2 font-mono text-[#87919c]">{fmt(e[0])}</span>
                    {e[2]}
                  </li>
                ))}
                {!recentEvents.length && <li className="text-[12px] text-[#87919c]">—</li>}
              </ul>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
