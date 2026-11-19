"use client";

// G1 Studio - Visitor App
// Announcement banner + which home tiles visitors see. Saved changes are pushed
// live to every G1 Remote tablet (WebSocket), no app restart needed.

import { useCallback, useEffect, useState } from "react";
import { getJson, postJson, sendJson } from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";
import AttractCard from "@/components/studio/AttractCard";

type AppConfig = {
  version: number;
  updated: string;
  announcement: { active: boolean; level: "info" | "warning"; text_en: string; text_de: string };
  tiles: Record<string, boolean>;
  tile_names: Record<string, string>;
};

export default function VisitorAppPage() {
  const { ensurePin, forgetPin, pinDialog } = usePin();
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [draft, setDraft] = useState<AppConfig | null>(null);
  const [clients, setClients] = useState<number | null>(null);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [previewLang, setPreviewLang] = useState<"en" | "de">("en");

  const load = useCallback(async () => {
    try {
      const c = await getJson<AppConfig>("/api/app/config");
      setCfg(c);
      setDraft((d) => d ?? c);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true });
    }
  }, []);

  useEffect(() => {
    void load();
    const poll = async () => {
      try {
        const r = await getJson<{ connected: number }>("/api/app/clients", 3000);
        setClients(r.connected);
      } catch {
        setClients(null);
      }
    };
    void poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [load]);

  const dirty = !!cfg && !!draft && JSON.stringify({ a: cfg.announcement, t: cfg.tiles }) !== JSON.stringify({ a: draft.announcement, t: draft.tiles });

  async function save() {
    if (!draft) return;
    const pin = await ensurePin();
    if (!pin) return;
    setBusy(true);
    try {
      const res = await sendJson<AppConfig & { clients: number }>("PUT", "/api/app/config", {
        pin,
        announcement: draft.announcement,
        tiles: draft.tiles,
      });
      setCfg({ ...res, tile_names: draft.tile_names });
      setDraft({ ...res, tile_names: draft.tile_names });
      setMessage({ text: `Saved and pushed live to ${res.clients} connected app${res.clients === 1 ? "" : "s"}.` });
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      setMessage({ text, error: true });
    } finally {
      setBusy(false);
      setTimeout(() => setMessage(null), 6000);
    }
  }

  async function withPin(run: (pin: string) => Promise<void>) {
    const pin = await ensurePin();
    if (!pin) return;
    try {
      await run(pin);
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      setMessage({ text, error: true });
      setTimeout(() => setMessage(null), 6000);
    }
  }

  function flash(text: string, error = false) {
    setMessage({ text, error });
    setTimeout(() => setMessage(null), 6000);
  }

  async function translate() {
    if (!draft?.announcement.text_en.trim()) return;
    setTranslating(true);
    try {
      const r = await postJson<{ text: string }>(
        "/api/map/translate",
        { text: draft.announcement.text_en, source: "en", target: "de" },
        120000,
      );
      setDraft({ ...draft, announcement: { ...draft.announcement, text_de: r.text } });
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true });
    } finally {
      setTranslating(false);
    }
  }

  if (!draft) {
    return <div className="p-10 text-[14px] text-[#657078]">{message?.text || "Loading…"}</div>;
  }
  const a = draft.announcement;
  const warn = a.level === "warning";
  const previewText = previewLang === "en" ? a.text_en : a.text_de || a.text_en;

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {pinDialog}
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Visitor App</h1>
          </div>
          <p className="text-[13px] text-[#657078]">Changes are pushed live to the G1 Remote tablets</p>
          <span
            className={`ml-auto rounded-full px-3 py-1.5 text-[12px] font-bold ${
              clients ? "bg-[#eaf7f2] text-[#00866a]" : "bg-[#f0f2f3] text-[#566373]"
            }`}
          >
            {clients === null ? "Backend offline" : `${clients} live connection${clients === 1 ? "" : "s"}`}
          </span>
          <button
            onClick={() => void save()}
            disabled={!dirty || busy}
            className="rounded bg-[#009b77] px-5 py-2 text-[14px] font-bold text-white disabled:opacity-40"
          >
            {busy ? "Saving…" : "Save & push to app"}
          </button>
        </div>
        {message && (
          <div
            className={`border-t px-6 py-2 text-center text-[13px] font-semibold ${
              message.error ? "border-[#f3c6c6] bg-[#fdecec] text-[#b42020]" : "border-[#cfe9df] bg-[#eaf7f2] text-[#00866a]"
            }`}
          >
            {message.text}
          </div>
        )}
      </section>

      <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-6 px-6 py-6 md:px-10 lg:grid-cols-2">
        {/* announcement */}
        <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Announcement banner</h2>
            <label className="flex items-center gap-2 text-[13px] font-bold text-[#36414b]">
              <input
                type="checkbox"
                checked={a.active}
                onChange={(e) => setDraft({ ...draft, announcement: { ...a, active: e.target.checked } })}
              />
              Show on the app
            </label>
          </div>
          <div className="mt-4 flex overflow-hidden rounded border border-[#c6ccd1] text-[12px] font-bold">
            {(["info", "warning"] as const).map((l) => (
              <button
                key={l}
                onClick={() => setDraft({ ...draft, announcement: { ...a, level: l } })}
                className={`flex-1 px-3 py-2 ${a.level === l ? (l === "info" ? "bg-[#009b77] text-white" : "bg-[#d79616] text-white") : "bg-white text-[#566373]"}`}
              >
                {l === "info" ? "Info (green)" : "Important (orange)"}
              </button>
            ))}
          </div>
          <label className="mt-4 block text-[12px] font-semibold text-[#566373]">
            English
            <textarea
              value={a.text_en}
              maxLength={300}
              onChange={(e) => setDraft({ ...draft, announcement: { ...a, text_en: e.target.value } })}
              placeholder="e.g. Live demo of G1 at 14:00 – join us at the lab entrance!"
              className="mt-1 h-[70px] w-full rounded border border-[#c6ccd1] px-3 py-2 text-[14px] text-[#292f33] outline-none focus:border-[#009b77]"
            />
          </label>
          <div className="mt-2 flex justify-end">
            <button
              onClick={() => void translate()}
              disabled={translating || !a.text_en.trim()}
              className="rounded border border-[#c6ccd1] px-3 py-1 text-[12px] font-bold text-[#36414b] disabled:opacity-40"
            >
              {translating ? "Translating…" : "Translate EN → DE"}
            </button>
          </div>
          <label className="mt-2 block text-[12px] font-semibold text-[#566373]">
            Deutsch
            <textarea
              value={a.text_de}
              maxLength={300}
              onChange={(e) => setDraft({ ...draft, announcement: { ...a, text_de: e.target.value } })}
              placeholder="z. B. Live-Demo von G1 um 14:00 – kommen Sie zum Laboreingang!"
              className="mt-1 h-[70px] w-full rounded border border-[#c6ccd1] px-3 py-2 text-[14px] text-[#292f33] outline-none focus:border-[#009b77]"
            />
          </label>
        </section>

        {/* tiles + preview */}
        <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Home screen tiles</h2>
          <p className="mt-1 text-[12px] text-[#657078]">Hide what is not ready or not wanted today (e.g. Robot Show while G1 is charging).</p>
          <div className="mt-4 grid grid-cols-2 gap-3">
            {Object.entries(draft.tile_names).map(([key, name]) => (
              <label
                key={key}
                className={`flex cursor-pointer items-center gap-3 rounded-md border p-3 text-[13px] font-semibold ${
                  draft.tiles[key] ? "border-[#009b77] bg-[#f4fbf8] text-[#292f33]" : "border-[#e4e8eb] text-[#87919c]"
                }`}
              >
                <input
                  type="checkbox"
                  checked={!!draft.tiles[key]}
                  onChange={(e) => setDraft({ ...draft, tiles: { ...draft.tiles, [key]: e.target.checked } })}
                />
                {name}
              </label>
            ))}
          </div>

          <div className="mt-6 flex items-center justify-between">
            <h3 className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#657078]">Preview</h3>
            <div className="flex overflow-hidden rounded border border-[#c6ccd1] text-[11px] font-bold">
              {(["en", "de"] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => setPreviewLang(l)}
                  className={`px-2.5 py-1 ${previewLang === l ? "bg-[#009b77] text-white" : "bg-white text-[#566373]"}`}
                >
                  {l.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-2 rounded-xl border border-[#d8dde1] bg-[#f4f7f5] p-3">
            {a.active && previewText.trim() && (
              <div
                className={`mb-3 rounded-lg px-3 py-2 text-[12px] font-semibold ${
                  warn ? "bg-[#fff6e5] text-[#9a6812]" : "bg-[#eaf7f2] text-[#00866a]"
                }`}
              >
                {warn ? "⚠ " : "ℹ "}
                {previewText}
              </div>
            )}
            <div className="grid grid-cols-3 gap-2">
              {Object.entries(draft.tile_names)
                .filter(([key]) => draft.tiles[key])
                .map(([key, name]) => (
                  <div key={key} className="rounded-md bg-white px-2 py-4 text-center text-[11px] font-bold text-[#36414b] shadow-sm">
                    {name}
                  </div>
                ))}
            </div>
          </div>
          <p className="mt-3 text-[11px] text-[#87919c]">
            Config version {cfg?.version} · last saved {cfg?.updated ? cfg.updated.replace("T", " ") : "never"}. Tour titles and
            texts are edited on the Lab Map and also update the app live.
          </p>
        </section>
        <AttractCard withPin={withPin} flash={flash} />
      </div>
    </div>
  );
}
