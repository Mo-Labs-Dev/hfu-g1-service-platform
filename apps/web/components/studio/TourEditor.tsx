"use client";

// Tour editor: route title + intro and every stop's title / explanation in EN + DE.
// Saved straight into the route file on the robot PC - the next tour uses it.

import { useEffect, useState } from "react";
import { postJson, sendJson } from "@/lib/g1api";
import type { MapRoute, MapStop } from "@/components/studio/LabMapCanvas";

const GESTURES: [string, string][] = [
  ["none", "No gesture"],
  ["high_wave", "Wave"],
  ["face_wave", "Wave (near face)"],
  ["clap", "Clap"],
  ["heart", "Heart"],
  ["two_hand_kiss", "Kiss"],
];

type Props = {
  route: MapRoute & { intro_en?: string; intro_de?: string; gesture_start?: string; gesture_end?: string };
  color: string;
  withPin: (run: (pin: string) => Promise<void>) => Promise<void>;
  onSaved: () => Promise<void> | void;
  flash: (text: string, error?: boolean) => void;
  onHoverStop: (key: string | null) => void;
};

const FIELD = "w-full rounded border border-[#c6ccd1] px-2.5 py-1.5 text-[13px] text-[#292f33] outline-none focus:border-[#009b77]";
const SMALL_BTN =
  "rounded border border-[#c6ccd1] px-2 py-1 text-[11px] font-bold text-[#36414b] hover:border-[#009b77] disabled:opacity-40";

function useTranslate(flash: Props["flash"]) {
  const [busy, setBusy] = useState(false);
  async function translate(text: string, source: "en" | "de", target: "en" | "de"): Promise<string | null> {
    if (!text.trim()) return null;
    setBusy(true);
    try {
      const r = await postJson<{ text: string }>("/api/map/translate", { text, source, target }, 120000);
      return r.text;
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
      return null;
    } finally {
      setBusy(false);
    }
  }
  return { translate, busy };
}

function StopCard({
  routeName,
  stop,
  n,
  color,
  withPin,
  onSaved,
  flash,
  onHoverStop,
}: {
  routeName: string;
  stop: MapStop;
  n: number;
  color: string;
} & Omit<Props, "route" | "color">) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({
    title_en: stop.title_en || "",
    title_de: stop.title_de || "",
    text_en: stop.text_en || "",
    text_de: stop.text_de || "",
  });
  const [saving, setSaving] = useState(false);
  const { translate, busy } = useTranslate(flash);

  useEffect(() => {
    setDraft({
      title_en: stop.title_en || "",
      title_de: stop.title_de || "",
      text_en: stop.text_en || "",
      text_de: stop.text_de || "",
    });
  }, [stop.title_en, stop.title_de, stop.text_en, stop.text_de]);

  const dirty =
    draft.title_en !== (stop.title_en || "") ||
    draft.title_de !== (stop.title_de || "") ||
    draft.text_en !== (stop.text_en || "") ||
    draft.text_de !== (stop.text_de || "");

  async function save() {
    await withPin(async (pin) => {
      setSaving(true);
      try {
        await sendJson("PUT", `/api/map/routes/${encodeURIComponent(routeName)}/stops/${encodeURIComponent(stop.name)}`, {
          pin,
          ...draft,
        });
        flash(`Stop “${draft.title_en || stop.name}” saved – used from the next tour.`);
        await onSaved();
      } finally {
        setSaving(false);
      }
    });
  }

  async function remove() {
    if (!window.confirm(`Delete stop “${stop.title_en || stop.name}” from ${routeName}?`)) return;
    await withPin(async (pin) => {
      await sendJson(
        "DELETE",
        `/api/map/routes/${encodeURIComponent(routeName)}/stops/${encodeURIComponent(stop.name)}?pin=${encodeURIComponent(pin)}`,
      );
      flash("Stop deleted.");
      await onSaved();
    });
  }

  async function say(lang: "en" | "de") {
    const text = lang === "en" ? draft.text_en || `Here you can see the ${draft.title_en}.` : draft.text_de || `Hier sehen Sie: ${draft.title_de}.`;
    await withPin(async (pin) => {
      await postJson("/api/map/say", { pin, text, lang });
      flash(`G1 is speaking (${lang.toUpperCase()}).`);
    });
  }

  async function fill(target: "en" | "de") {
    const source = target === "de" ? "en" : "de";
    const title = await translate(source === "en" ? draft.title_en : draft.title_de, source, target);
    const text = await translate(source === "en" ? draft.text_en : draft.text_de, source, target);
    setDraft((d) => ({
      ...d,
      ...(title !== null ? { [`title_${target}`]: title } : {}),
      ...(text !== null ? { [`text_${target}`]: text } : {}),
    }));
  }

  const key = `${routeName}/${stop.name}`;
  return (
    <li
      className="rounded-md border border-[#e4e8eb]"
      onMouseEnter={() => onHoverStop(key)}
      onMouseLeave={() => onHoverStop(null)}
    >
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <span
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
          style={{ background: color }}
        >
          {n + 1}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-bold text-[#292f33]">
            {stop.title_en || stop.name}
            {dirty && <span className="ml-2 text-[11px] font-semibold text-[#d79616]">unsaved</span>}
          </span>
          {!open && (
            <span className="block truncate text-[11px] text-[#657078]">
              {stop.text_en || "Default: “Here you can see the …”"}
            </span>
          )}
        </span>
        <span className="text-[12px] text-[#87919c]">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-[#e4e8eb] px-3 py-3">
          {(["en", "de"] as const).map((l) => (
            <div key={l} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#566373]">
                  {l === "en" ? "English" : "Deutsch"}
                </span>
                <div className="flex gap-1.5">
                  <button className={SMALL_BTN} disabled={busy} onClick={() => void fill(l)}>
                    {busy ? "…" : l === "de" ? "Translate EN → DE" : "Translate DE → EN"}
                  </button>
                  <button className={SMALL_BTN} onClick={() => void say(l)}>
                    🔊 Say on G1
                  </button>
                </div>
              </div>
              <input
                className={FIELD}
                placeholder={l === "en" ? "Title (e.g. 3D printer)" : "Titel (z. B. 3D-Drucker)"}
                value={l === "en" ? draft.title_en : draft.title_de}
                onChange={(e) => setDraft({ ...draft, [`title_${l}`]: e.target.value })}
              />
              <textarea
                className={`${FIELD} h-[84px] resize-y`}
                placeholder={l === "en" ? "What G1 says at this stop (2–3 sentences)" : "Was G1 hier erklärt (2–3 Sätze)"}
                value={l === "en" ? draft.text_en : draft.text_de}
                onChange={(e) => setDraft({ ...draft, [`text_${l}`]: e.target.value })}
              />
              <p className="text-right text-[10px] text-[#87919c]">
                {(l === "en" ? draft.text_en : draft.text_de).length}/600
              </p>
            </div>
          ))}
          <div className="flex items-center justify-between pt-1">
            <button onClick={() => void remove()} className="text-[12px] font-semibold text-[#d62828] hover:underline">
              Delete stop
            </button>
            <button
              onClick={() => void save()}
              disabled={!dirty || saving}
              className="rounded bg-[#009b77] px-4 py-1.5 text-[13px] font-bold text-white disabled:opacity-40"
            >
              {saving ? "Saving…" : "Save stop"}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

export default function TourEditor({ route, color, withPin, onSaved, flash, onHoverStop }: Props) {
  const [meta, setMeta] = useState({
    title_en: route.title_en || "",
    title_de: route.title_de || "",
    intro_en: route.intro_en || "",
    intro_de: route.intro_de || "",
    gesture_start: route.gesture_start || "high_wave",
    gesture_end: route.gesture_end || "face_wave",
  });
  const [open, setOpen] = useState(false);
  const { translate, busy } = useTranslate(flash);

  useEffect(() => {
    setMeta({
      title_en: route.title_en || "",
      title_de: route.title_de || "",
      intro_en: route.intro_en || "",
      intro_de: route.intro_de || "",
      gesture_start: route.gesture_start || "high_wave",
      gesture_end: route.gesture_end || "face_wave",
    });
  }, [route.name, route.title_en, route.title_de, route.intro_en, route.intro_de, route.gesture_start, route.gesture_end]);

  const dirty =
    meta.title_en !== (route.title_en || "") ||
    meta.title_de !== (route.title_de || "") ||
    meta.intro_en !== (route.intro_en || "") ||
    meta.intro_de !== (route.intro_de || "") ||
    meta.gesture_start !== (route.gesture_start || "high_wave") ||
    meta.gesture_end !== (route.gesture_end || "face_wave");

  async function saveMeta() {
    await withPin(async (pin) => {
      await sendJson("PUT", `/api/map/routes/${encodeURIComponent(route.name)}`, { pin, ...meta });
      flash("Tour details saved.");
      await onSaved();
    });
  }

  async function fillDe() {
    const t = await translate(meta.title_en, "en", "de");
    const i = await translate(meta.intro_en, "en", "de");
    setMeta((m) => ({ ...m, ...(t !== null ? { title_de: t } : {}), ...(i !== null ? { intro_de: i } : {}) }));
  }

  const isTour = route.kind === "tour";
  return (
    <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">
          {isTour ? "Tour editor" : "Route details"}
        </h2>
        <button onClick={() => setOpen(!open)} className="text-[12px] font-semibold text-[#00866a] hover:underline">
          {open ? "Hide details" : "Title & intro"}
          {dirty ? " •" : ""}
        </button>
      </div>

      {open && (
        <div className="mt-3 space-y-2 rounded-md bg-[#fafbfb] p-3">
          <input
            className={FIELD}
            placeholder="Title EN (e.g. HFU lab tour)"
            value={meta.title_en}
            onChange={(e) => setMeta({ ...meta, title_en: e.target.value })}
          />
          <input
            className={FIELD}
            placeholder="Titel DE (z. B. HFU Laborführung)"
            value={meta.title_de}
            onChange={(e) => setMeta({ ...meta, title_de: e.target.value })}
          />
          <textarea
            className={`${FIELD} h-[64px]`}
            placeholder={isTour ? "Welcome text EN (empty = default)" : "Arrival text EN (empty = default)"}
            value={meta.intro_en}
            onChange={(e) => setMeta({ ...meta, intro_en: e.target.value })}
          />
          <textarea
            className={`${FIELD} h-[64px]`}
            placeholder={isTour ? "Begrüßung DE (leer = Standard)" : "Ankunftstext DE (leer = Standard)"}
            value={meta.intro_de}
            onChange={(e) => setMeta({ ...meta, intro_de: e.target.value })}
          />
          {isTour && (
            <div className="grid grid-cols-2 gap-2">
              {(["gesture_start", "gesture_end"] as const).map((k) => (
                <label key={k} className="text-[11px] font-semibold text-[#566373]">
                  {k === "gesture_start" ? "Gesture at the welcome" : "Gesture at the goodbye"}
                  <select
                    value={meta[k]}
                    onChange={(e) => setMeta({ ...meta, [k]: e.target.value })}
                    className={`${FIELD} mt-1 bg-white`}
                  >
                    {GESTURES.map(([v, label]) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}
          <div className="flex justify-between">
            <button className={SMALL_BTN} disabled={busy} onClick={() => void fillDe()}>
              {busy ? "Translating…" : "Translate EN → DE"}
            </button>
            <button
              onClick={() => void saveMeta()}
              disabled={!dirty}
              className="rounded bg-[#009b77] px-4 py-1.5 text-[13px] font-bold text-white disabled:opacity-40"
            >
              Save
            </button>
          </div>
        </div>
      )}

      {isTour ? (
        <ol className="mt-3 space-y-2">
          {route.stops.map((st, n) => (
            <StopCard
              key={st.name}
              routeName={route.name}
              stop={st}
              n={n}
              color={color}
              withPin={withPin}
              onSaved={onSaved}
              flash={flash}
              onHoverStop={onHoverStop}
            />
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-[12px] text-[#657078]">This route has no stops. Record it with --tour to add stops.</p>
      )}
      <p className="mt-3 text-[11px] text-[#87919c]">
        Changes are saved on the robot PC and used from the next tour. The tablet app shows new titles the next time
        Talk to G1 is opened.
      </p>
    </section>
  );
}
