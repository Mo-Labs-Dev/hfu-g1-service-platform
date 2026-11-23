"use client";

// G1 Studio - Live View
// "What is G1 doing?" for the big screen: current activity, G1 on the lab map, and a timeline of
// everything that happens (heard -> answered, walking, blocked, pointing, show steps).
// Replay: every autonomous walk is recorded and can be played back on the map.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiBase, getJson } from "@/lib/g1api";
import MiniMap, { Pose } from "@/components/studio/MiniMap";

type Ev = { id: number; t: string; kind: "talk" | "walk" | "arm" | "show" | string; text: string; detail: string; level: string };
type Now = {
  walk: { state: string; route: string; progress: number | null; message: string; stop: string } | null;
  pose: (Pose & { source?: string }) | null;
  arm: { state: string; target: string | null; message: string } | null;
  show: { state: string; title: string; step: number; steps: number; label: string; message: string } | null;
};
type Activity = { events: Ev[]; now: Now; recording: boolean; recording_points: number };
type PathItem = { id: string; started: string; route: string; kind: string; result: string; duration_s: number; length_m: number; blocked: number; points: number };
type Traj = { started: string; route: string; result: string; duration_s: number; length_m: number; samples: [number, number, number, number, string][]; blocked: [number, number][] };

const KIND_ICON: Record<string, string> = { talk: "💬", walk: "🚶", arm: "👉", show: "🎬" };
const IDLE_ARM = new Set(["idle", "done", "failed", "refused", "stopped", null as unknown as string]);
const IDLE_WALK = new Set(["idle", "done", "aborted", "cancelled", "failed", "error"]);

export default function LiveViewPage() {
  const [tab, setTab] = useState<"live" | "replay">("live");
  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Live View</h1>
          </div>
          <p className="text-[13px] text-[#657078]">What G1 is doing right now – and replay of every walk</p>
          <div className="ml-auto flex overflow-hidden rounded border border-[#c6ccd1] text-[13px] font-bold">
            {([["live", "Live"], ["replay", "Replay"]] as const).map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)} className={`px-4 py-2 ${tab === k ? "bg-[#009b77] text-white" : "bg-white text-[#36414b]"}`}>{l}</button>
            ))}
          </div>
        </div>
      </section>
      {tab === "live" ? <Live /> : <Replay />}
    </div>
  );
}

// ---------------------------------------------------------------- live
function Live() {
  const [act, setAct] = useState<Activity | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [trail, setTrail] = useState<[number, number][]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastTalk, setLastTalk] = useState<Ev | null>(null);
  const box = useRef<HTMLDivElement | null>(null);

  const poll = useCallback(async () => {
    try {
      const a = await getJson<Activity>("/api/activity?limit=60", 3000);
      setAct(a);
      setError(null);
      setEvents((prev) => (prev.length ? prev : a.events));
      const p = a.now?.pose;
      const walking = a.now?.walk && !IDLE_WALK.has(a.now.walk.state);
      if (walking && p) {
        setTrail((t) => {
          const last = t[t.length - 1];
          return !last || Math.hypot(last[0] - p.x, last[1] - p.y) > 0.05 ? [...t, [p.x, p.y]].slice(-3000) : t;
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void poll();
    const t = setInterval(poll, 1000);
    return () => clearInterval(t);
  }, [poll]);

  // new walk -> new trail
  const walkKey = act?.now?.walk && !IDLE_WALK.has(act.now.walk.state) ? act.now.walk.route : null;
  const prevKey = useRef<string | null>(null);
  useEffect(() => {
    if (walkKey && walkKey !== prevKey.current) setTrail([]);
    prevKey.current = walkKey;
  }, [walkKey]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      socket = new WebSocket(apiBase().replace(/^http/, "ws") + "/ws");
      socket.onclose = () => { if (!stopped) retry = setTimeout(connect, 3000); };
      socket.onmessage = (m) => {
        try {
          const ev = JSON.parse(m.data);
          if (ev.type === "activity") {
            setEvents((prev) => (prev.some((p) => p.id === ev.data.id) ? prev : [...prev, ev.data].slice(-200)));
            if (ev.data.kind === "talk") setLastTalk(ev.data);
          }
        } catch { /* ignore */ }
      };
    };
    connect();
    return () => { stopped = true; if (retry) clearTimeout(retry); socket?.close(); };
  }, []);

  const now = act?.now;
  const headline = useMemo(() => {
    if (!now) return { icon: "…", text: error ? "Studio backend not reachable" : "Connecting…", sub: "" };
    if (now.show && (now.show.state === "running" || now.show.state === "waiting"))
      return { icon: "🎬", text: now.show.state === "waiting" ? "Waiting for the operator" : now.show.label, sub: `Show “${now.show.title}” · step ${now.show.step + 1} of ${now.show.steps}` };
    if (now.walk && !IDLE_WALK.has(now.walk.state)) {
      const pct = now.walk.progress != null ? ` · ${Math.round(now.walk.progress * 100)} %` : "";
      const what = now.walk.state === "blocked" ? "Waiting – path blocked" : now.walk.state === "arrived" ? `Arrived: ${now.walk.stop || now.walk.route}` : `Walking to ${now.walk.stop || now.walk.route}`;
      return { icon: "🚶", text: what, sub: `${now.walk.state}${pct}${now.walk.message ? " · " + now.walk.message : ""}` };
    }
    if (now.arm && !IDLE_ARM.has(now.arm.state))
      return { icon: "👉", text: now.arm.state === "talking" ? "Talking with gestures" : `Pointing at ${(now.arm.target || "").replace("_", " ")}`, sub: now.arm.message };
    if (lastTalk && Date.now() - Date.parse(lastTalk.t) < 15000)
      return { icon: "💬", text: "Talking with a visitor", sub: lastTalk.text };
    return { icon: "🤖", text: "Ready", sub: "Say “Hey G1 …” or use the app" };
  }, [now, lastTalk, error]);

  const fullscreen = () => {
    const el = box.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  return (
    <div ref={box} className="mx-auto max-w-[1500px] bg-[#f7f8f7] px-6 py-6 md:px-10">
      <div className="flex items-center gap-5 rounded-xl border border-[#d8dde1] bg-white px-6 py-5">
        <div className="text-[44px] leading-none">{headline.icon}</div>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[#657078]">G1 right now</div>
          <div className="truncate text-[28px] font-bold tracking-[-0.02em] text-[#292f33]">{headline.text}</div>
          {headline.sub && <div className="truncate text-[14px] text-[#566373]">{headline.sub}</div>}
        </div>
        {act?.recording && <span className="rounded-full bg-[#fdf0f0] px-3 py-1 text-[12px] font-bold text-[#c62828]">● recording walk</span>}
        <button onClick={fullscreen} className="rounded border border-[#c6ccd1] px-3 py-1.5 text-[12px] font-bold text-[#36414b]">⛶ Big screen</button>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
        <section className="rounded-xl border border-[#d8dde1] bg-white p-4">
          <div className="mb-2 flex items-center justify-between text-[12px] text-[#657078]">
            <span className="font-bold uppercase tracking-[0.08em] text-[#36414b]">Lab map</span>
            <span>{now?.pose ? `x ${now.pose.x.toFixed(2)} m · y ${now.pose.y.toFixed(2)} m · ${now.pose.quality || now.pose.source || ""}` : "position unknown"}</span>
          </div>
          <MiniMap pose={now?.pose ?? null} path={trail} height={560} fit={trail.length > 1 ? "path" : "map"} />
        </section>

        <section className="flex max-h-[660px] flex-col rounded-xl border border-[#d8dde1] bg-white">
          <div className="border-b border-[#eef0f1] px-5 py-3 text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Timeline</div>
          <div className="flex flex-1 flex-col-reverse overflow-y-auto px-5 py-3">
            <div>
              {events.length === 0 && <div className="py-10 text-center text-[13px] text-[#8a949c]">Nothing happened yet.</div>}
              {events.map((e) => (
                <div key={e.id} className="flex gap-3 border-b border-[#f2f3f3] py-2.5 last:border-0">
                  <div className="w-12 shrink-0 pt-0.5 text-[11px] text-[#8a949c]">{e.t.slice(11, 16)}</div>
                  <div className="text-[18px] leading-none">{KIND_ICON[e.kind] || "•"}</div>
                  <div className="min-w-0 flex-1">
                    <div className={`text-[14px] font-semibold ${e.level === "warn" ? "text-[#9a5b00]" : e.level === "ok" ? "text-[#00866a]" : "text-[#292f33]"}`}>{e.text}</div>
                    {e.detail && <div className="text-[12px] text-[#566373]">{e.detail}</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- replay
function Replay() {
  const [paths, setPaths] = useState<PathItem[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [traj, setTraj] = useState<Traj | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<{ paths: PathItem[] }>("/api/activity/paths")
      .then((r) => { setPaths(r.paths); if (r.paths[0]) setSel(r.paths[0].id); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!sel) return;
    setPlaying(false);
    getJson<Traj>(`/api/activity/paths/${sel}`).then((tr) => { setTraj(tr); setT(tr.samples[tr.samples.length - 1]?.[0] ?? 0); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [sel]);

  const end = traj?.samples[traj.samples.length - 1]?.[0] ?? 0;
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setT((x) => {
        const n = x + 0.1 * speed;
        if (n >= end) { setPlaying(false); return end; }
        return n;
      });
    }, 100);
    return () => clearInterval(id);
  }, [playing, speed, end]);

  const upto = traj ? traj.samples.filter((s) => s[0] <= t) : [];
  const cur = upto[upto.length - 1];
  const pose: Pose | null = cur ? { x: cur[1], y: cur[2], yaw: cur[3] } : null;

  return (
    <div className="mx-auto grid max-w-[1500px] grid-cols-1 gap-6 px-6 py-6 md:px-10 lg:grid-cols-[360px_1fr]">
      <section className="h-fit rounded-xl border border-[#d8dde1] bg-white p-4">
        <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Recorded walks <span className="text-[#8a949c]">({paths?.length ?? 0})</span></h2>
        {error && <div className="mt-2 text-[12px] text-[#a33]">{error}</div>}
        {paths?.length === 0 && <div className="mt-3 text-[12px] text-[#8a949c]">No walks recorded yet. Every autonomous walk / tour is recorded automatically from now on.</div>}
        <div className="mt-3 flex max-h-[640px] flex-col gap-1.5 overflow-y-auto">
          {paths?.map((p) => (
            <button key={p.id} onClick={() => setSel(p.id)}
              className={`rounded px-3 py-2 text-left ${sel === p.id ? "bg-[#292f33] text-white" : "bg-[#f4f5f4] text-[#36414b] hover:bg-[#eaedeb]"}`}>
              <div className="flex items-center gap-2 text-[13px] font-bold">
                <span className="flex-1 truncate">{p.route || "walk"}</span>
                <span className={`rounded px-1.5 text-[10px] uppercase ${p.result === "done" ? "bg-[#009b77] text-white" : "bg-[#e0a100] text-white"}`}>{p.result}</span>
              </div>
              <div className={`text-[11px] ${sel === p.id ? "text-[#c9d1d6]" : "text-[#8a949c]"}`}>
                {p.started?.slice(0, 16).replace("T", " ")} · {p.length_m} m · {Math.round(p.duration_s)} s{p.blocked ? ` · ${p.blocked}× blocked` : ""}
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-[#d8dde1] bg-white p-4">
        {!traj ? <div className="py-20 text-center text-[13px] text-[#8a949c]">Choose a recorded walk.</div> : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-4 text-[13px] text-[#36414b]">
              <b className="text-[16px]">{traj.route?.replace(/^goto:/, "").replace(/_/g, " ")}</b>
              <span>{traj.length_m} m</span><span>{Math.round(traj.duration_s)} s</span>
              <span>{traj.length_m && traj.duration_s ? (traj.length_m / traj.duration_s).toFixed(2) : "–"} m/s avg</span>
              <span>{traj.blocked.length}× blocked</span>
              <span className="ml-auto font-bold">{cur ? cur[4] : ""}</span>
            </div>
            <MiniMap pose={pose} path={upto.map((s) => [s[1], s[2]] as [number, number])}
              ghostPath={traj.samples.map((s) => [s[1], s[2]] as [number, number])} blocked={traj.blocked} height={560} />
            <div className="mt-3 flex items-center gap-3">
              <button onClick={() => { if (t >= end) setT(0); setPlaying((p) => !p); }}
                className="w-24 rounded bg-[#009b77] py-2 text-[13px] font-bold text-white">{playing ? "❚❚ Pause" : "▶ Play"}</button>
              <input type="range" min={0} max={end} step={0.1} value={t} onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }} className="flex-1 accent-[#009b77]" />
              <span className="w-20 text-right text-[12px] tabular-nums text-[#566373]">{t.toFixed(1)} / {end.toFixed(0)} s</span>
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="rounded border border-[#c6ccd1] px-2 py-1 text-[12px]">
                {[1, 2, 4, 10].map((s) => <option key={s} value={s}>{s}×</option>)}
              </select>
            </div>
            <div className="mt-2 flex gap-4 text-[11px] text-[#657078]">
              <span><span className="inline-block h-2 w-4 rounded bg-[#009b77] align-middle" /> walked</span>
              <span><span className="inline-block h-2 w-4 rounded bg-[#9fb4c4] align-middle" /> full path</span>
              <span><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#e0a100] align-middle" /> blocked</span>
              <span><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#36414b] align-middle" /> start</span>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
