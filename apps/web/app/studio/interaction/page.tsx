"use client";

// G1 Studio - Interaction
// One place to watch and steer every conversation with G1:
//   - live list of all turns (G1 Remote app, G1's own microphone, Studio tests, operator sentences)
//   - switches: app talk, "Hey G1" microphone, arm gestures, speak answers
//   - answer length + a note for today that G1 uses in its answers
//   - make G1 say a sentence word for word (also shown in the app's Talk screen)
// Changes need the operator PIN and take effect immediately (no app restart).

import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase, getJson, postJson, sendJson } from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";
import TalkCardsPanel from "@/components/studio/TalkCardsPanel";
import InsightsPanel from "@/components/studio/InsightsPanel";

type Source = "app" | "mic" | "studio" | "operator";
type Turn = {
  id: number;
  t: string;
  source: Source;
  heard: string;
  reply: string;
  lang: "en" | "de";
  seconds: number | null;
  spoke: boolean;
  note?: string;
};
type Settings = {
  app_talk: boolean;
  speak_answers: boolean;
  reply_length: "short" | "normal" | "long";
  note: string;
};
type Status = {
  settings: Settings;
  stats: { today: number; by_source: Record<Source, number>; avg_answer_s: number | null; german: number };
  sessions: number;
  voice: {
    running: boolean;
    enabled?: boolean;
    mic?: string;
    model?: string;
    conversation?: boolean;
    last_heard?: string;
    last_transcribe_s?: number;
  };
  gestures: boolean;
  llm: { model: string; ok?: boolean; loaded?: boolean | null };
};

const SOURCE_STYLE: Record<Source, { label: string; cls: string }> = {
  app: { label: "App", cls: "bg-[#e8f1fb] text-[#1d5fa8]" },
  mic: { label: "G1 microphone", cls: "bg-[#eaf7f2] text-[#00866a]" },
  studio: { label: "Studio test", cls: "bg-[#f3eefb] text-[#6b46a8]" },
  operator: { label: "Operator", cls: "bg-[#fff4e0] text-[#9a5b00]" },
};

const QUICK = {
  en: [
    "Hello everyone, welcome to the HFU robotics lab!",
    "Please keep a distance of one metre from me while I am walking.",
    "The tour starts in two minutes. Please gather near me.",
    "Thank you for visiting. Have a great day!",
  ],
  de: [
    "Hallo zusammen, herzlich willkommen im Robotik-Labor der HFU!",
    "Bitte halten Sie einen Meter Abstand, während ich laufe.",
    "Die Führung beginnt in zwei Minuten. Bitte kommen Sie zu mir.",
    "Vielen Dank für Ihren Besuch. Einen schönen Tag noch!",
  ],
};

function clock(t: string) {
  return t.length >= 19 ? t.slice(11, 19) : t;
}

export default function InteractionPage() {
  const { ensurePin, forgetPin, pinDialog } = usePin();
  const [status, setStatus] = useState<Status | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [live, setLive] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<Source | "all">("all");
  const [tab, setTab] = useState<"live" | "cards" | "insights">("live");
  const [note, setNote] = useState<string | null>(null);
  const [sayText, setSayText] = useState("");
  const [sayLang, setSayLang] = useState<"en" | "de">("en");
  const [sayInApp, setSayInApp] = useState(true);
  const [question, setQuestion] = useState("");
  const [askSpeak, setAskSpeak] = useState(false);
  const [askLang, setAskLang] = useState<"en" | "de">("en");
  const testSession = useRef<string | null>(null);
  const feedEnd = useRef<HTMLDivElement | null>(null);

  const flash = useCallback((text: string, error = false) => {
    setMessage({ text, error });
    setTimeout(() => setMessage(null), 6000);
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getJson<Status>("/api/interaction/control/status", 4000));
    } catch (e) {
      setStatus(null);
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true });
    }
  }, []);

  // first load + status poll (microphone / model state changes all the time)
  useEffect(() => {
    void loadStatus();
    getJson<{ items: Turn[] }>("/api/interaction/control/log?limit=150")
      .then((r) => setTurns(r.items))
      .catch(() => undefined);
    const t = setInterval(loadStatus, 3000);
    return () => clearInterval(t);
  }, [loadStatus]);

  // live turns over the backend WebSocket
  useEffect(() => {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      socket = new WebSocket(apiBase().replace(/^http/, "ws") + "/ws");
      socket.onopen = () => setLive(true);
      socket.onclose = () => {
        setLive(false);
        if (!stopped) retry = setTimeout(connect, 3000);
      };
      socket.onmessage = (m) => {
        try {
          const ev = JSON.parse(m.data);
          if (ev.type === "interaction") {
            setTurns((prev) => (prev.some((p) => p.id === ev.data.id) ? prev : [...prev, ev.data].slice(-300)));
          } else if (ev.type === "interaction_cleared") {
            setTurns([]);
          } else if (ev.type === "interaction_settings") {
            setStatus((s) => (s ? { ...s, settings: ev.data } : s));
          }
        } catch {
          /* other event types */
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    feedEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns.length]);

  async function withPin(key: string, run: (pin: string) => Promise<void>) {
    const pin = await ensurePin();
    if (!pin) return;
    setBusy(key);
    try {
      await run(pin);
      void loadStatus();
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      flash(text, true);
    } finally {
      setBusy(null);
    }
  }

  const saveSettings = (change: Partial<Settings>, done?: string) =>
    withPin("settings", async (pin) => {
      const s = await sendJson<Settings>("PUT", "/api/interaction/control/settings", { pin, ...change });
      setStatus((st) => (st ? { ...st, settings: s } : st));
      if (done) flash(done);
    });

  const setMic = (enabled: boolean) =>
    withPin("mic", async (pin) => {
      await postJson("/api/voice/enable", { pin, enabled });
      flash(enabled ? "G1 listens for “Hey G1” again." : "G1 microphone listening paused.");
    });

  const setGestures = (enabled: boolean) =>
    withPin("gestures", async (pin) => {
      await postJson("/api/voice/gestures", { pin, enabled });
      flash(enabled ? "Arms move while G1 talks." : "Arm gestures off.");
    });

  const say = (text: string) =>
    withPin("say", async (pin) => {
      await postJson("/api/interaction/control/say", { pin, text, lang: sayLang, show_in_app: sayInApp }, 15000);
      setSayText("");
    });

  async function ask() {
    const q = question.trim();
    if (!q) return;
    setBusy("ask");
    try {
      const r = await postJson<{ answer: string; session_id: string }>(
        "/api/interaction/ask",
        { question: q, speak: askSpeak, language: askLang, source: "studio",
          ...(testSession.current ? { session_id: testSession.current } : {}) },
        140000,
      );
      testSession.current = r.session_id;
      setQuestion("");
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    } finally {
      setBusy(null);
    }
  }

  const s = status?.settings;
  const v = status?.voice;
  const shown = filter === "all" ? turns : turns.filter((t) => t.source === filter);
  const noteValue = note ?? s?.note ?? "";

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {pinDialog}
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Interaction</h1>
          </div>
          <p className="text-[13px] text-[#657078]">
            Every conversation with G1 – from the app and from G1&apos;s own microphone – live in one place
          </p>
          <div className="ml-auto flex overflow-hidden rounded border border-[#c6ccd1] text-[13px] font-bold">
            {([["live", "Live & controls"], ["cards", "Speaking cards"], ["insights", "Questions & knowledge"]] as const).map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`px-4 py-2 ${tab === k ? "bg-[#009b77] text-white" : "bg-white text-[#36414b]"}`}>
                {label}
              </button>
            ))}
          </div>
          <span
            className={`rounded-full px-3 py-1.5 text-[12px] font-bold ${
              live ? "bg-[#eaf7f2] text-[#00866a]" : "bg-[#f0f2f3] text-[#566373]"
            }`}
          >
            {live ? "● Live" : "Connecting…"}
          </span>
        </div>
      </section>

      {message && (
        <div className="mx-auto max-w-[1400px] px-6 pt-4 md:px-10">
          <div
            className={`rounded border px-4 py-2 text-[13px] font-semibold ${
              message.error ? "border-[#f0c4c4] bg-[#fdf0f0] text-[#a33]" : "border-[#bfe3d6] bg-[#eaf7f2] text-[#00866a]"
            }`}
          >
            {message.text}
          </div>
        </div>
      )}

      {tab === "cards" && (
        <div className="mx-auto max-w-[1400px] px-6 py-6 md:px-10">
          <TalkCardsPanel ensurePin={ensurePin} forgetPin={forgetPin} flash={flash} />
        </div>
      )}

      {tab === "insights" && (
        <div className="mx-auto max-w-[1400px] px-6 py-6 md:px-10">
          <InsightsPanel ensurePin={ensurePin} forgetPin={forgetPin} flash={flash} />
        </div>
      )}

      {tab === "live" && (<>
      {/* status strip */}
      <div className="mx-auto grid max-w-[1400px] grid-cols-2 gap-3 px-6 pt-6 md:grid-cols-5 md:px-10">
        <Tile label="Conversations today" value={status ? String(status.stats.today) : "–"}
          sub={status ? `${status.stats.by_source.app} app · ${status.stats.by_source.mic} mic · ${status.stats.german} German` : ""} />
        <Tile label="Avg. answer time" value={status?.stats.avg_answer_s != null ? `${status.stats.avg_answer_s} s` : "–"}
          sub={v?.last_transcribe_s != null ? `speech recognition ${v.last_transcribe_s} s` : ""} />
        <Tile label="G1 microphone" value={!v ? "–" : !v.running ? "Off" : v.enabled ? (v.conversation ? "In conversation" : "Listening") : "Paused"}
          sub={v?.mic && v.mic !== "ok" ? v.mic : v?.model || ""} warn={!!v && v.running && v.mic !== "ok"} />
        <Tile label="AI model" value={status ? (status.llm.ok ? (status.llm.loaded ? "Ready" : "Idle (loads on first question)") : "Not reachable") : "–"}
          sub={status?.llm.model || ""} warn={!!status && !status.llm.ok} />
        <Tile label="Open app conversations" value={status ? String(status.sessions) : "–"} sub="G1 remembers names / context" />
      </div>

      <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-6 px-6 py-6 md:px-10 lg:grid-cols-[420px_1fr]">
        {/* ---------------- controls ---------------- */}
        <div className="flex flex-col gap-6">
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Controls</h2>
            <div className="mt-3 divide-y divide-[#eef0f1]">
              <Switch label="App talk" hint="Visitors can ask G1 in the G1 Remote app"
                on={!!s?.app_talk} disabled={!s || busy !== null} onChange={(x) => saveSettings({ app_talk: x })} />
              <Switch label="“Hey G1” microphone" hint="Visitors talk to G1 directly"
                on={!!v?.enabled} disabled={!v?.running || busy !== null} onChange={setMic} />
              <Switch label="Speak answers" hint="Off = app answers only as text (quiet lab)"
                on={!!s?.speak_answers} disabled={!s || busy !== null} onChange={(x) => saveSettings({ speak_answers: x })} />
              <Switch label="Arm gestures" hint="Arms move while G1 talks (remote in hand!)"
                on={!!status?.gestures} disabled={!status || busy !== null} onChange={setGestures} />
            </div>

            <div className="mt-4">
              <div className="text-[12px] font-semibold text-[#566373]">Answer length</div>
              <div className="mt-1 flex overflow-hidden rounded border border-[#c6ccd1] text-[12px] font-bold">
                {(["short", "normal", "long"] as const).map((k) => (
                  <button key={k} disabled={!s || busy !== null}
                    onClick={() => saveSettings({ reply_length: k })}
                    className={`flex-1 py-2 capitalize ${s?.reply_length === k ? "bg-[#009b77] text-white" : "bg-white text-[#36414b]"}`}>
                    {k}
                  </button>
                ))}
              </div>
            </div>

            <label className="mt-4 block text-[12px] font-semibold text-[#566373]">
              Note for G1 today
              <textarea value={noteValue} maxLength={500} onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. Today is open house day – invite visitors to the pick & place demo at 14:00."
                className="mt-1 h-[70px] w-full rounded border border-[#c6ccd1] px-3 py-2 text-[14px] text-[#292f33] outline-none focus:border-[#009b77]" />
            </label>
            <div className="mt-2 flex justify-end gap-2">
              <button disabled={!s || busy !== null || noteValue === (s?.note ?? "")}
                onClick={() => withPin("settings", async (pin) => {
                  const r = await sendJson<Settings>("PUT", "/api/interaction/control/settings", { pin, note: noteValue });
                  setStatus((st) => (st ? { ...st, settings: r } : st));
                  setNote(null);
                  flash("Note saved – G1 uses it from the next question on.");
                })}
                className="rounded bg-[#009b77] px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-40">
                Save note
              </button>
            </div>

            <div className="mt-4 flex flex-wrap gap-2 border-t border-[#eef0f1] pt-4">
              <button disabled={busy !== null}
                onClick={() => withPin("reset", async (pin) => {
                  const r = await postJson<{ reset: number }>("/api/interaction/control/reset-sessions", { pin });
                  testSession.current = null;
                  flash(`${r.reset} conversation${r.reset === 1 ? "" : "s"} reset – next visitor starts fresh.`);
                })}
                className="rounded border border-[#c6ccd1] px-3 py-1.5 text-[12px] font-bold text-[#36414b] disabled:opacity-40">
                New visitor (reset all conversations)
              </button>
              <button disabled={busy !== null || turns.length === 0}
                onClick={() => withPin("clear", async (pin) => { await postJson("/api/interaction/control/clear", { pin }); })}
                className="rounded border border-[#c6ccd1] px-3 py-1.5 text-[12px] font-bold text-[#36414b] disabled:opacity-40">
                Clear list
              </button>
            </div>
          </section>

          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Make G1 say</h2>
              <Lang value={sayLang} onChange={setSayLang} />
            </div>
            <textarea value={sayText} maxLength={400} onChange={(e) => setSayText(e.target.value)}
              placeholder="G1 says this word for word"
              className="mt-3 h-[64px] w-full rounded border border-[#c6ccd1] px-3 py-2 text-[14px] text-[#292f33] outline-none focus:border-[#009b77]" />
            <div className="mt-2 flex items-center justify-between">
              <label className="flex items-center gap-2 text-[12px] font-semibold text-[#566373]">
                <input type="checkbox" checked={sayInApp} onChange={(e) => setSayInApp(e.target.checked)} />
                Also show in the app
              </label>
              <button disabled={!sayText.trim() || busy !== null} onClick={() => say(sayText.trim())}
                className="rounded bg-[#009b77] px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-40">
                {busy === "say" ? "Speaking…" : "Say it"}
              </button>
            </div>
            <div className="mt-3 flex flex-col gap-1.5">
              {QUICK[sayLang].map((q) => (
                <button key={q} disabled={busy !== null} onClick={() => say(q)}
                  className="rounded border border-[#e0e3e1] bg-[#f7f8f7] px-3 py-1.5 text-left text-[12px] text-[#36414b] hover:border-[#009b77] disabled:opacity-40">
                  {q}
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Test question</h2>
              <Lang value={askLang} onChange={setAskLang} />
            </div>
            <p className="mt-1 text-[12px] text-[#657078]">Ask like a visitor would – answers use today&apos;s settings.</p>
            <div className="mt-3 flex gap-2">
              <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000}
                onKeyDown={(e) => { if (e.key === "Enter") void ask(); }}
                placeholder="What can you do?"
                className="flex-1 rounded border border-[#c6ccd1] px-3 py-2 text-[14px] text-[#292f33] outline-none focus:border-[#009b77]" />
              <button disabled={!question.trim() || busy !== null} onClick={() => void ask()}
                className="rounded bg-[#009b77] px-4 text-[12px] font-bold text-white disabled:opacity-40">
                {busy === "ask" ? "Thinking…" : "Ask"}
              </button>
            </div>
            <label className="mt-2 flex items-center gap-2 text-[12px] font-semibold text-[#566373]">
              <input type="checkbox" checked={askSpeak} onChange={(e) => setAskSpeak(e.target.checked)} />
              G1 speaks the answer
            </label>
          </section>
        </div>

        {/* ---------------- live conversation ---------------- */}
        <section className="flex min-h-[600px] flex-col rounded-lg border border-[#d8dde1] bg-white">
          <div className="flex flex-wrap items-center gap-2 border-b border-[#eef0f1] px-5 py-3">
            <h2 className="mr-auto text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Live conversation</h2>
            {(["all", "app", "mic", "studio", "operator"] as const).map((k) => (
              <button key={k} onClick={() => setFilter(k)}
                className={`rounded-full px-3 py-1 text-[11px] font-bold ${
                  filter === k ? "bg-[#292f33] text-white" : "bg-[#f0f2f3] text-[#566373]"
                }`}>
                {k === "all" ? "All" : SOURCE_STYLE[k].label}
              </button>
            ))}
          </div>
          <div className="max-h-[calc(100vh-260px)] flex-1 overflow-y-auto px-5 py-4">
            {shown.length === 0 && (
              <div className="py-16 text-center text-[13px] text-[#8a949c]">
                No conversations yet. Say “Hey G1 …” to the robot or ask in the app.
              </div>
            )}
            {shown.map((t) => (
              <div key={t.id} className="mb-4">
                <div className="flex items-center gap-2 text-[11px] text-[#8a949c]">
                  <span className={`rounded px-2 py-0.5 font-bold ${SOURCE_STYLE[t.source].cls}`}>{SOURCE_STYLE[t.source].label}</span>
                  <span>{clock(t.t)}</span>
                  <span className="uppercase">{t.lang}</span>
                  {t.seconds != null && t.seconds > 0 && <span>· answered in {t.seconds} s</span>}
                  {t.note === "paused" && <span className="font-bold text-[#9a5b00]">· app talk paused</span>}
                  {t.spoke && <span>· 🔊</span>}
                </div>
                {t.heard && (
                  <div className="mt-1.5 max-w-[80%] rounded-lg bg-[#f0f2f3] px-3 py-2 text-[14px] text-[#292f33]">
                    {t.heard}
                  </div>
                )}
                <div className="ml-auto mt-1.5 max-w-[80%] rounded-lg bg-[#eaf7f2] px-3 py-2 text-[14px] text-[#1f3d35]">
                  <span className="mr-1 font-bold text-[#00866a]">G1:</span>
                  {t.reply}
                </div>
              </div>
            ))}
            <div ref={feedEnd} />
          </div>
        </section>
      </div>
      </>)}
    </div>
  );
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className={`rounded-lg border bg-white px-4 py-3 ${warn ? "border-[#f0c4c4]" : "border-[#d8dde1]"}`}>
      <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">{label}</div>
      <div className={`mt-1 text-[18px] font-bold ${warn ? "text-[#a33]" : "text-[#292f33]"}`}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-[#8a949c]" title={sub}>{sub}</div>}
    </div>
  );
}

function Switch({ label, hint, on, disabled, onChange }: {
  label: string; hint: string; on: boolean; disabled?: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-3">
      <div>
        <div className="text-[14px] font-bold text-[#292f33]">{label}</div>
        <div className="text-[12px] text-[#657078]">{hint}</div>
      </div>
      <button disabled={disabled} onClick={() => onChange(!on)} aria-pressed={on}
        className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-40 ${on ? "bg-[#009b77]" : "bg-[#c6ccd1]"}`}>
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
      </button>
    </div>
  );
}

function Lang({ value, onChange }: { value: "en" | "de"; onChange: (v: "en" | "de") => void }) {
  return (
    <div className="flex overflow-hidden rounded border border-[#c6ccd1] text-[11px] font-bold">
      {(["en", "de"] as const).map((l) => (
        <button key={l} onClick={() => onChange(l)}
          className={`px-2.5 py-1 uppercase ${value === l ? "bg-[#009b77] text-white" : "bg-white text-[#36414b]"}`}>
          {l}
        </button>
      ))}
    </div>
  );
}
