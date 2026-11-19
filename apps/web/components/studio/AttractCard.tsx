"use client";

// Attract mode controls: G1 notices people walking past, waves and invites them.

import { useEffect, useState } from "react";
import { getJson, postJson, sendJson } from "@/lib/g1api";

type Settings = {
  enabled: boolean;
  cooldown_s: number;
  min_box_height: number;
  wave: boolean;
  text_en: string;
  text_de: string;
  languages: string[];
};
type Status = {
  settings: Settings;
  state: string;
  greetings_today: number;
  last_greet_s_ago: number | null;
  last_person_s_ago: number | null;
};

const FIELD = "w-full rounded border border-[#c6ccd1] px-3 py-2 text-[13px] text-[#292f33] outline-none focus:border-[#009b77]";

export default function AttractCard({
  withPin,
  flash,
}: {
  withPin: (run: (pin: string) => Promise<void>) => Promise<void>;
  flash: (text: string, error?: boolean) => void;
}) {
  const [st, setSt] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const s = await getJson<Status>("/api/attract", 3000);
        if (!alive) return;
        setSt(s);
        setDraft((d) => d ?? s.settings);
      } catch {
        if (alive) setSt(null);
      }
    };
    void poll();
    const t = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!draft) return null;
  const dirty = !!st && JSON.stringify(st.settings) !== JSON.stringify(draft);

  async function save(next: Settings, msg: string) {
    await withPin(async (pin) => {
      const s = await sendJson<Status>("PUT", "/api/attract", { pin, ...next });
      setSt(s);
      setDraft(s.settings);
      flash(msg);
    });
  }

  return (
    <section className="rounded-lg border border-[#d8dde1] bg-white p-5 lg:col-span-2">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Attract mode</h2>
        <span
          className={`rounded-full px-3 py-1 text-[12px] font-bold ${
            st?.settings.enabled ? "bg-[#eaf7f2] text-[#00866a]" : "bg-[#f0f2f3] text-[#566373]"
          }`}
        >
          {st?.settings.enabled ? `ON · ${st.state}` : "OFF"}
        </span>
        <span className="text-[12px] text-[#657078]">
          {st ? `${st.greetings_today} greeting${st.greetings_today === 1 ? "" : "s"} today` : ""}
          {st?.last_greet_s_ago != null ? ` · last ${Math.round(st.last_greet_s_ago / 60)} min ago` : ""}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => void withPin(async (pin) => {
              await postJson("/api/attract/greet", { pin });
              flash("G1 greets once (test).");
            })}
            className="rounded border border-[#c6ccd1] px-3 py-2 text-[12px] font-bold text-[#36414b]"
          >
            👋 Test greeting
          </button>
          <button
            onClick={() => void save({ ...draft, enabled: !st?.settings.enabled }, st?.settings.enabled ? "Attract mode off." : "Attract mode on – G1 watches for visitors.")}
            className={`rounded px-4 py-2 text-[13px] font-bold text-white ${st?.settings.enabled ? "bg-[#566373]" : "bg-[#009b77]"}`}
          >
            {st?.settings.enabled ? "Switch off" : "Switch on"}
          </button>
        </div>
      </div>
      <p className="mt-2 text-[12px] leading-[17px] text-[#657078]">
        When nobody uses G1 (walking mode, no tour, joystick free, battery OK), the head camera looks for people. A new visitor
        seen in two pictures in a row → G1 waves and invites them. People who stay in view are not greeted again.
      </p>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <label className="text-[12px] font-semibold text-[#566373]">
          What G1 says (English)
          <textarea className={`${FIELD} mt-1 h-[60px]`} value={draft.text_en} onChange={(e) => setDraft({ ...draft, text_en: e.target.value })} />
        </label>
        <label className="text-[12px] font-semibold text-[#566373]">
          Was G1 sagt (Deutsch)
          <textarea className={`${FIELD} mt-1 h-[60px]`} value={draft.text_de} onChange={(e) => setDraft({ ...draft, text_de: e.target.value })} />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-5 text-[12px] font-semibold text-[#566373]">
        <label className="flex items-center gap-2">
          Languages
          {(["en", "de"] as const).map((l) => (
            <span key={l} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={draft.languages.includes(l)}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    languages: e.target.checked ? [...draft.languages.filter((x) => x !== l), l].sort() : draft.languages.filter((x) => x !== l),
                  })
                }
              />
              {l.toUpperCase()}
            </span>
          ))}
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={draft.wave} onChange={(e) => setDraft({ ...draft, wave: e.target.checked })} />
          Wave
        </label>
        <label className="flex items-center gap-2">
          At most every
          <select className="rounded border border-[#c6ccd1] px-2 py-1" value={draft.cooldown_s} onChange={(e) => setDraft({ ...draft, cooldown_s: Number(e.target.value) })}>
            {[60, 120, 300, 600].map((s) => (
              <option key={s} value={s}>
                {s / 60} min
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          Distance
          <select className="rounded border border-[#c6ccd1] px-2 py-1" value={draft.min_box_height} onChange={(e) => setDraft({ ...draft, min_box_height: Number(e.target.value) })}>
            <option value={0.15}>far (more greetings)</option>
            <option value={0.25}>normal</option>
            <option value={0.4}>close only</option>
          </select>
        </label>
        <button
          disabled={!dirty}
          onClick={() => void save(draft, "Attract settings saved.")}
          className="ml-auto rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
        >
          Save
        </button>
      </div>
    </section>
  );
}
