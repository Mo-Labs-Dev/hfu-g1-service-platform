"use client";

// G1 Studio - Show Mode
// Build a demo from blocks (say, answer, gesture, walk, point, wait, pause) and run it with one button,
// step by step (operator presses Continue) or automatically. Stop is always available (no PIN).

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiBase, getJson, postJson, sendJson } from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";

type Step = {
  type: "say" | "ask" | "gesture" | "walk" | "point" | "wait" | "pause";
  text_en?: string; text_de?: string; question_en?: string; question_de?: string;
  gesture?: string; destination?: string; target?: string; seconds?: number; text?: string;
};
type Show = { id: string; title: string; lang: "en" | "de"; description: string; steps: Step[]; updated?: string };
type LogEntry = { i: number; type: string; label: string; result: "done" | "failed"; seconds: number; message: string };
type RunState = {
  state: "idle" | "running" | "waiting" | "done" | "stopped" | "failed";
  show: string | null; title: string; step: number; steps: number; label: string; message: string;
  mode: "auto" | "step"; lang: string; log: LogEntry[]; labels: string[];
};
type ShowsResponse = {
  shows: Show[]; state: RunState | null; destinations: { name: string; title: string }[];
  gestures: string[]; targets: string[]; max_steps: number;
};
type RunRec = { started: string; title: string; result: string; duration_s: number; steps_done: number; steps_total: number; mode: string; message: string };

const BLOCKS: { type: Step["type"]; label: string; icon: string; hint: string; motion?: boolean; make: () => Step }[] = [
  { type: "say", label: "Say", icon: "💬", hint: "G1 says your sentence", make: () => ({ type: "say", text_en: "", text_de: "" }) },
  { type: "ask", label: "Answer a question", icon: "❓", hint: "G1 answers like a visitor asked (AI / card)", make: () => ({ type: "ask", question_en: "", question_de: "" }) },
  { type: "gesture", label: "Gesture", icon: "👋", hint: "Wave, clap, heart …", motion: true, make: () => ({ type: "gesture", gesture: "high_wave" }) },
  { type: "walk", label: "Walk to", icon: "🚶", hint: "Autonomous walk to a Lab Map destination", motion: true, make: () => ({ type: "walk", destination: "" }) },
  { type: "point", label: "Point at", icon: "👉", hint: "Camera-guided arm points at a tag", motion: true, make: () => ({ type: "point", target: "object" }) },
  { type: "wait", label: "Wait", icon: "⏱", hint: "Pause a few seconds", make: () => ({ type: "wait", seconds: 3 }) },
  { type: "pause", label: "Wait for operator", icon: "✋", hint: "Continues when you press Continue", make: () => ({ type: "pause", text: "Visitors may ask questions" }) },
];
const ICON: Record<string, string> = Object.fromEntries(BLOCKS.map((b) => [b.type, b.icon]));
const MOTION = new Set(["gesture", "walk", "point"]);
const TARGET_NAMES: Record<string, string> = { object: "the object (tag 0)", target_a: "target A (tag 1)", target_b: "target B (tag 2)" };

const input = "w-full rounded border border-[#c6ccd1] px-2.5 py-1.5 text-[13px] text-[#292f33] outline-none focus:border-[#009b77]";

export default function ShowModePage() {
  const { ensurePin, forgetPin, pinDialog } = usePin();
  const [data, setData] = useState<ShowsResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Show | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [runs, setRuns] = useState<RunRec[]>([]);
  const [mode, setMode] = useState<"step" | "auto">("step");
  const [lang, setLang] = useState<"en" | "de">("en");
  const [safetyOk, setSafetyOk] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const flash = useCallback((text: string, error = false) => {
    setMessage({ text, error });
    setTimeout(() => setMessage(null), 7000);
  }, []);

  const load = useCallback(async (keep?: string) => {
    try {
      const r = await getJson<ShowsResponse>("/api/shows");
      setData(r);
      setRun(r.state);
      const id = keep ?? r.shows[0]?.id ?? null;
      setSelected(id);
      const sh = r.shows.find((s) => s.id === id);
      setDraft(sh ? JSON.parse(JSON.stringify(sh)) : null);
      if (sh) setLang(sh.lang);
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    }
  }, [flash]);

  const loadRuns = useCallback(() => {
    getJson<{ runs: RunRec[] }>("/api/shows/runs?limit=8").then((r) => setRuns(r.runs)).catch(() => undefined);
  }, []);

  useEffect(() => {
    void load();
    loadRuns();
  }, [load, loadRuns]);

  // live run state: WebSocket + slow poll as backup
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
          if (ev.type === "show") setRun(ev.data);
        } catch { /* ignore */ }
      };
    };
    connect();
    const poll = setInterval(() => {
      getJson<RunState>("/api/shows/state", 3000).then(setRun).catch(() => undefined);
    }, 2500);
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      socket?.close();
      clearInterval(poll);
    };
  }, []);

  const running = run?.state === "running" || run?.state === "waiting";
  useEffect(() => {
    if (run && !running) loadRuns();
  }, [run?.state, running, loadRuns]); // eslint-disable-line react-hooks/exhaustive-deps

  const saved = data?.shows.find((s) => s.id === selected);
  const dirty = !!draft && JSON.stringify(stripUpdated(draft)) !== JSON.stringify(saved ? stripUpdated(saved) : null);
  const hasMotion = useMemo(() => !!draft?.steps.some((s) => MOTION.has(s.type)), [draft]);

  async function withPin(run: (pin: string) => Promise<void>) {
    const pin = await ensurePin();
    if (!pin) return;
    setBusy(true);
    try {
      await run(pin);
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      flash(text, true);
    } finally {
      setBusy(false);
    }
  }

  const save = () => withPin(async (pin) => {
    if (!draft) return;
    const r = await sendJson<Show>("PUT", "/api/shows", { pin, show: draft });
    await load(r.id);
    flash("Show saved.");
  });

  const start = () => withPin(async (pin) => {
    if (!selected) return;
    const r = await postJson<RunState>(`/api/shows/${selected}/start`, { pin, mode, lang, start_at: 0 });
    setRun(r);
    setSafetyOk(false);
  });

  const next = () => withPin(async (pin) => { setRun(await postJson<RunState>("/api/shows/next", { pin })); });

  async function stop() {
    try {
      setRun(await postJson<RunState>("/api/shows/stop", {}));
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    }
  }

  function newShow() {
    const id = `show_${Date.now().toString(36)}`;
    setSelected(id);
    setDraft({ id, title: "New show", lang: "en", description: "", steps: [BLOCKS[0].make()] });
  }

  function duplicate() {
    if (!draft) return;
    const id = `show_${Date.now().toString(36)}`;
    setSelected(id);
    setDraft({ ...JSON.parse(JSON.stringify(draft)), id, title: `${draft.title} (copy)` });
  }

  const remove = () => withPin(async (pin) => {
    if (!selected || !saved || !confirm(`Delete the show “${saved.title}”?`)) return;
    await postJson(`/api/shows/${selected}/delete`, { pin });
    await load();
  });

  const setStep = (i: number, patch: Partial<Step>) =>
    setDraft((d) => (d ? { ...d, steps: d.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) } : d));
  const moveStep = (i: number, dir: -1 | 1) =>
    setDraft((d) => {
      if (!d || i + dir < 0 || i + dir >= d.steps.length) return d;
      const steps = [...d.steps];
      [steps[i], steps[i + dir]] = [steps[i + dir], steps[i]];
      return { ...d, steps };
    });

  const isThisShow = run && run.show === selected;
  const canStart = !!saved && !dirty && !running && !busy && (!hasMotion || safetyOk);

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {pinDialog}
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Show Mode</h1>
          </div>
          <p className="text-[13px] text-[#657078]">Build a demo from blocks – run it with one button</p>
          {running && (
            <button onClick={() => void stop()}
              className="ml-auto rounded bg-[#c62828] px-6 py-2.5 text-[15px] font-bold text-white shadow hover:bg-[#a51f1f]">
              ■ STOP SHOW
            </button>
          )}
        </div>
      </section>

      {message && (
        <div className="mx-auto max-w-[1500px] px-6 pt-4 md:px-10">
          <div className={`rounded border px-4 py-2 text-[13px] font-semibold ${message.error ? "border-[#f0c4c4] bg-[#fdf0f0] text-[#a33]" : "border-[#bfe3d6] bg-[#eaf7f2] text-[#00866a]"}`}>
            {message.text}
          </div>
        </div>
      )}

      <div className="mx-auto grid max-w-[1500px] grid-cols-1 gap-6 px-6 py-6 md:px-10 xl:grid-cols-[240px_1fr_400px]">
        {/* ---------------- show list ---------------- */}
        <section className="h-fit rounded-lg border border-[#d8dde1] bg-white p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Shows</h2>
            <button onClick={newShow} disabled={running} className="text-[12px] font-bold text-[#00866a] underline disabled:opacity-40">+ New</button>
          </div>
          <div className="mt-3 flex flex-col gap-1.5">
            {data?.shows.map((s) => (
              <button key={s.id} disabled={running && s.id !== selected}
                onClick={() => { setSelected(s.id); setDraft(JSON.parse(JSON.stringify(s))); setLang(s.lang); setSafetyOk(false); }}
                className={`rounded px-3 py-2 text-left text-[13px] disabled:opacity-40 ${s.id === selected ? "bg-[#292f33] font-bold text-white" : "bg-[#f4f5f4] text-[#36414b] hover:bg-[#eaedeb]"}`}>
                {s.title}
                <div className={`text-[11px] ${s.id === selected ? "text-[#c9d1d6]" : "text-[#8a949c]"}`}>
                  {s.steps.length} steps{s.steps.some((x) => MOTION.has(x.type)) ? " · moves" : ""}
                </div>
              </button>
            ))}
            {draft && !saved && (
              <div className="rounded bg-[#292f33] px-3 py-2 text-[13px] font-bold text-white">{draft.title}<div className="text-[11px] text-[#c9d1d6]">not saved yet</div></div>
            )}
          </div>
        </section>

        {/* ---------------- editor ---------------- */}
        <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
          {!draft ? <div className="text-[13px] text-[#8a949c]">Create a show with “+ New”.</div> : (
            <>
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-[240px] flex-1">
                  <input value={draft.title} maxLength={80} disabled={running} onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                    className="w-full rounded border border-transparent px-1 text-[20px] font-bold text-[#292f33] outline-none hover:border-[#c6ccd1] focus:border-[#009b77]" />
                  <input value={draft.description} maxLength={200} disabled={running} placeholder="Short description (optional)"
                    onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                    className="mt-1 w-full rounded border border-transparent px-1 text-[13px] text-[#657078] outline-none hover:border-[#c6ccd1] focus:border-[#009b77]" />
                </div>
                <div className="flex gap-2">
                  <button onClick={duplicate} disabled={running} className="rounded border border-[#c6ccd1] px-3 py-1.5 text-[12px] font-bold text-[#36414b] disabled:opacity-40">Duplicate</button>
                  {saved && <button onClick={() => void remove()} disabled={running} className="rounded border border-[#f0c4c4] px-3 py-1.5 text-[12px] font-bold text-[#a33] disabled:opacity-40">Delete</button>}
                  <button onClick={() => void save()} disabled={!dirty || busy || running}
                    className="rounded bg-[#009b77] px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-40">{dirty ? "Save show" : "Saved"}</button>
                </div>
              </div>

              <div className="mt-5 flex flex-col gap-2">
                {draft.steps.map((s, i) => {
                  const st = isThisShow ? stepStatus(run!, i) : null;
                  return (
                    <div key={i} className={`rounded-lg border p-3 ${st === "current" ? "border-[#009b77] bg-[#f2fbf8] shadow" : st === "failed" ? "border-[#f0c4c4] bg-[#fdf6f6]" : "border-[#e0e3e1]"}`}>
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#f0f2f3] text-[11px] font-bold text-[#36414b]">{i + 1}</span>
                        <span className="text-[16px]">{ICON[s.type]}</span>
                        <span className="text-[13px] font-bold text-[#292f33]">{BLOCKS.find((b) => b.type === s.type)?.label}</span>
                        {MOTION.has(s.type) && <span className="rounded bg-[#fff4e0] px-1.5 text-[10px] font-bold uppercase text-[#9a5b00]">moves</span>}
                        {st === "done" && <span className="text-[12px] font-bold text-[#00866a]">✓</span>}
                        {st === "current" && <span className="text-[12px] font-bold text-[#00866a]">▶ now</span>}
                        {st === "failed" && <span className="text-[12px] font-bold text-[#a33]">✕ failed</span>}
                        <div className="ml-auto flex gap-1 text-[12px] text-[#566373]">
                          <button disabled={running || i === 0} onClick={() => moveStep(i, -1)} className="px-1 disabled:opacity-25">▲</button>
                          <button disabled={running || i === draft.steps.length - 1} onClick={() => moveStep(i, 1)} className="px-1 disabled:opacity-25">▼</button>
                          <button disabled={running || draft.steps.length === 1} onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_, j) => j !== i) })}
                            className="px-1 text-[#a33] disabled:opacity-25">✕</button>
                        </div>
                      </div>
                      <fieldset disabled={running} className="mt-2 pl-8">
                        <StepFields step={s} onChange={(p) => setStep(i, p)} data={data} />
                      </fieldset>
                    </div>
                  );
                })}
              </div>

              <div className="mt-4 rounded-lg border border-dashed border-[#c6ccd1] p-3">
                <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Add block</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {BLOCKS.map((b) => (
                    <button key={b.type} title={b.hint} disabled={running || draft.steps.length >= (data?.max_steps ?? 40)}
                      onClick={() => setDraft({ ...draft, steps: [...draft.steps, b.make()] })}
                      className="rounded border border-[#e0e3e1] bg-[#f7f8f7] px-3 py-1.5 text-[12px] font-bold text-[#36414b] hover:border-[#009b77] disabled:opacity-40">
                      {b.icon} {b.label}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>

        {/* ---------------- run panel ---------------- */}
        <section className="h-fit rounded-lg border border-[#d8dde1] bg-white p-5 xl:sticky xl:top-4">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Run</h2>

          {run && run.state !== "idle" && (
            <div className={`mt-3 rounded-lg p-3 ${running ? "bg-[#eaf7f2]" : run.state === "done" ? "bg-[#f0f2f3]" : "bg-[#fdf0f0]"}`}>
              <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">
                {run.state === "running" ? "Running" : run.state === "waiting" ? "Waiting for you" : run.state} · {run.title}
              </div>
              {running && <div className="mt-1 text-[15px] font-bold text-[#292f33]">Step {run.step + 1}/{run.steps}: {run.label}</div>}
              {run.message && <div className="mt-1 text-[13px] text-[#36414b]">{run.message}</div>}
              <div className="mt-2 h-1.5 overflow-hidden rounded bg-white">
                <div className="h-full bg-[#009b77] transition-all" style={{ width: `${(run.log.filter((l) => l.result === "done").length / Math.max(1, run.steps)) * 100}%` }} />
              </div>
              {run.state === "waiting" && (
                <button onClick={() => void next()} disabled={busy}
                  className="mt-3 w-full rounded bg-[#009b77] py-3 text-[15px] font-bold text-white disabled:opacity-40">Continue ▶</button>
              )}
              {running && (
                <button onClick={() => void stop()} className="mt-2 w-full rounded bg-[#c62828] py-2.5 text-[14px] font-bold text-white">■ Stop</button>
              )}
            </div>
          )}

          {!running && (
            <>
              <div className="mt-4 text-[12px] font-semibold text-[#566373]">Mode</div>
              <div className="mt-1 flex overflow-hidden rounded border border-[#c6ccd1] text-[12px] font-bold">
                {([["step", "Step by step"], ["auto", "Automatic"]] as const).map(([k, l]) => (
                  <button key={k} onClick={() => setMode(k)} className={`flex-1 py-2 ${mode === k ? "bg-[#009b77] text-white" : "bg-white text-[#36414b]"}`}>{l}</button>
                ))}
              </div>
              <div className="mt-3 text-[12px] font-semibold text-[#566373]">Language</div>
              <div className="mt-1 flex overflow-hidden rounded border border-[#c6ccd1] text-[12px] font-bold">
                {(["en", "de"] as const).map((l) => (
                  <button key={l} onClick={() => setLang(l)} className={`flex-1 py-2 ${lang === l ? "bg-[#009b77] text-white" : "bg-white text-[#36414b]"}`}>{l === "en" ? "English" : "Deutsch"}</button>
                ))}
              </div>
              {hasMotion && (
                <label className="mt-4 flex items-start gap-2 rounded border border-[#f2e2c4] bg-[#fffaf0] p-3 text-[12px] text-[#6b4a12]">
                  <input type="checkbox" className="mt-0.5" checked={safetyOk} onChange={(e) => setSafetyOk(e.target.checked)} />
                  <span>This show <b>moves the robot</b>. Remote in my hand, G1 in walking mode on HOME, nobody within 1 m, path free.</span>
                </label>
              )}
              {dirty && <div className="mt-3 text-[12px] font-semibold text-[#9a5b00]">Save the show before running it.</div>}
              <button onClick={() => void start()} disabled={!canStart}
                className="mt-4 w-full rounded bg-[#009b77] py-3 text-[15px] font-bold text-white disabled:opacity-40">
                ▶ Start show
              </button>
              <p className="mt-2 text-[11px] text-[#8a949c]">
                Step by step: you press Continue after every block. Any failed block stops the show and all motion.
              </p>
            </>
          )}

          <h3 className="mt-6 text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Recent runs</h3>
          <div className="mt-2 flex flex-col gap-1.5">
            {runs.length === 0 && <div className="text-[12px] text-[#8a949c]">No runs yet.</div>}
            {runs.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-[12px]">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${r.result === "done" ? "bg-[#eaf7f2] text-[#00866a]" : r.result === "stopped" ? "bg-[#f0f2f3] text-[#566373]" : "bg-[#fdf0f0] text-[#a33]"}`}>{r.result}</span>
                <span className="flex-1 truncate text-[#36414b]" title={r.message}>{r.title}</span>
                <span className="text-[#8a949c]">{r.steps_done}/{r.steps_total} · {Math.round(r.duration_s)} s</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function stripUpdated(s: Show) {
  const { updated, ...rest } = s; // eslint-disable-line @typescript-eslint/no-unused-vars
  return rest;
}

function stepStatus(run: RunState, i: number): "done" | "current" | "failed" | null {
  const entry = run.log.find((l) => l.i === i);
  if (entry) return entry.result === "done" ? "done" : "failed";
  if ((run.state === "running" || run.state === "waiting") && run.step === i) return "current";
  return null;
}

function StepFields({ step, onChange, data }: { step: Step; onChange: (p: Partial<Step>) => void; data: ShowsResponse | null }) {
  switch (step.type) {
    case "say":
    case "ask": {
      const k = step.type === "say" ? "text" : "question";
      return (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          <input className={input} maxLength={400} placeholder={step.type === "say" ? "English sentence" : "Question (English)"}
            value={(step as Record<string, unknown>)[`${k}_en`] as string || ""} onChange={(e) => onChange({ [`${k}_en`]: e.target.value } as Partial<Step>)} />
          <input className={input} maxLength={400} placeholder={step.type === "say" ? "Deutscher Satz" : "Frage (Deutsch)"}
            value={(step as Record<string, unknown>)[`${k}_de`] as string || ""} onChange={(e) => onChange({ [`${k}_de`]: e.target.value } as Partial<Step>)} />
        </div>
      );
    }
    case "gesture":
      return (
        <select className={input} value={step.gesture} onChange={(e) => onChange({ gesture: e.target.value })}>
          {(data?.gestures ?? []).map((g) => <option key={g} value={g}>{g.replace(/_/g, " ")}</option>)}
        </select>
      );
    case "walk":
      return (
        <div>
          <select className={input} value={step.destination || ""} onChange={(e) => onChange({ destination: e.target.value })}>
            <option value="">– choose a destination –</option>
            {(data?.destinations ?? []).map((d) => <option key={d.name} value={d.name}>{d.title}</option>)}
          </select>
          {(data?.destinations ?? []).length === 0 && (
            <div className="mt-1 text-[11px] text-[#9a5b00]">No destinations yet – add them on the Lab Map page.</div>
          )}
        </div>
      );
    case "point":
      return (
        <select className={input} value={step.target} onChange={(e) => onChange({ target: e.target.value })}>
          {(data?.targets ?? []).map((t) => <option key={t} value={t}>{TARGET_NAMES[t] || t}</option>)}
        </select>
      );
    case "wait":
      return (
        <label className="flex items-center gap-2 text-[13px] text-[#36414b]">
          <input type="number" min={0.5} max={300} step={0.5} className={`${input} w-24`} value={step.seconds ?? 3}
            onChange={(e) => onChange({ seconds: Number(e.target.value) })} /> seconds
        </label>
      );
    case "pause":
      return <input className={input} maxLength={120} placeholder="Note for the operator" value={step.text || ""} onChange={(e) => onChange({ text: e.target.value })} />;
  }
}
