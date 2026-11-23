"use client";

// Speaking cards: the "Try asking" buttons on the G1 Remote Talk screen.
// Pick from the library (or add your own), order them, Save -> pushed live to every app.
// A card with a fixed answer makes G1 say exactly that text (no AI, instant).

import { useCallback, useEffect, useMemo, useState } from "react";
import { getJson, postJson, sendJson } from "@/lib/g1api";

export type TalkCard = {
  id: string;
  category: string;
  en: string;
  de: string;
  answer_en: string;
  answer_de: string;
  enabled: boolean;
  builtin: boolean;
};

type CardsResponse = { version: number; updated: string; cards: TalkCard[]; max_in_app: number; clients?: number };

export default function TalkCardsPanel({
  ensurePin,
  forgetPin,
  flash,
}: {
  ensurePin: () => Promise<string | null>;
  forgetPin: () => void;
  flash: (text: string, error?: boolean) => void;
}) {
  const [saved, setSaved] = useState<TalkCard[] | null>(null);
  const [cards, setCards] = useState<TalkCard[]>([]);
  const [maxInApp, setMaxInApp] = useState(40);
  const [category, setCategory] = useState<string>("All");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<TalkCard | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewDe, setPreviewDe] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await getJson<CardsResponse>("/api/interaction/cards");
      setSaved(r.cards);
      setCards(r.cards);
      setMaxInApp(r.max_in_app);
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    }
  }, [flash]);

  useEffect(() => {
    void load();
  }, [load]);

  const categories = useMemo(() => Array.from(new Set(cards.map((c) => c.category))), [cards]);
  const inApp = cards.filter((c) => c.enabled);
  const dirty = saved !== null && JSON.stringify(saved) !== JSON.stringify(cards);

  const visible = cards.filter((c) => {
    if (category === "In app" && !c.enabled) return false;
    if (category !== "All" && category !== "In app" && c.category !== category) return false;
    const q = search.trim().toLowerCase();
    return !q || `${c.en} ${c.de} ${c.answer_en} ${c.answer_de}`.toLowerCase().includes(q);
  });

  function toggle(id: string) {
    setCards((prev) => {
      const card = prev.find((c) => c.id === id);
      if (!card) return prev;
      if (!card.enabled && prev.filter((c) => c.enabled).length >= maxInApp) {
        flash(`Max ${maxInApp} cards in the app at once.`, true);
        return prev;
      }
      // newly switched on -> goes to the end of the app list
      const rest = prev.filter((c) => c.id !== id);
      return card.enabled ? prev.map((c) => (c.id === id ? { ...c, enabled: false } : c)) : [...rest, { ...card, enabled: true }];
    });
  }

  function setCategoryAll(cat: string, on: boolean) {
    setCards((prev) => {
      let count = prev.filter((c) => c.enabled).length;
      return prev.map((c) => {
        if (c.category !== cat || c.enabled === on) return c;
        if (on) {
          if (count >= maxInApp) return c;
          count += 1;
        }
        return { ...c, enabled: on };
      });
    });
  }

  function move(id: string, dir: -1 | 1) {
    setCards((prev) => {
      const enabledIdx = prev.map((c, i) => (c.enabled ? i : -1)).filter((i) => i >= 0);
      const pos = enabledIdx.findIndex((i) => prev[i].id === id);
      const other = enabledIdx[pos + dir];
      if (pos < 0 || other === undefined) return prev;
      const next = [...prev];
      [next[enabledIdx[pos]], next[other]] = [next[other], next[enabledIdx[pos]]];
      return next;
    });
  }

  function saveEdit(card: TalkCard) {
    if (!card.en.trim()) {
      flash("The English text is needed.", true);
      return;
    }
    setCards((prev) => (prev.some((c) => c.id === card.id) ? prev.map((c) => (c.id === card.id ? card : c)) : [card, ...prev]));
    setEditing(null);
  }

  async function save() {
    const pin = await ensurePin();
    if (!pin) return;
    setBusy(true);
    try {
      const r = await sendJson<CardsResponse>("PUT", "/api/interaction/cards", { pin, cards });
      setSaved(r.cards);
      setCards(r.cards);
      flash(`Saved – ${r.cards.filter((c) => c.enabled).length} cards pushed live to ${r.clients ?? 0} connected app${r.clients === 1 ? "" : "s"}.`);
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      flash(text, true);
    } finally {
      setBusy(false);
    }
  }

  if (saved === null) return <div className="p-6 text-[13px] text-[#657078]">Loading speaking cards…</div>;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
      {/* ---------------- library ---------------- */}
      <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="mr-auto text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">
            Card library <span className="text-[#8a949c]">({cards.length})</span>
          </h2>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search…"
            className="w-[200px] rounded border border-[#c6ccd1] px-3 py-1.5 text-[13px] outline-none focus:border-[#009b77]" />
          <button onClick={() => setEditing({ id: `new${Date.now()}`, category: category !== "All" && category !== "In app" ? category : "My cards",
            en: "", de: "", answer_en: "", answer_de: "", enabled: true, builtin: false })}
            className="rounded bg-[#009b77] px-4 py-1.5 text-[12px] font-bold text-white">
            + New card
          </button>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {["All", "In app", ...categories].map((k) => (
            <button key={k} onClick={() => setCategory(k)}
              className={`rounded-full px-3 py-1 text-[11px] font-bold ${category === k ? "bg-[#292f33] text-white" : "bg-[#f0f2f3] text-[#566373]"}`}>
              {k}
              {k !== "All" && k !== "In app" && (
                <span className="ml-1 opacity-60">{cards.filter((c) => c.category === k && c.enabled).length}/{cards.filter((c) => c.category === k).length}</span>
              )}
            </button>
          ))}
        </div>
        {category !== "All" && category !== "In app" && (
          <div className="mt-2 flex gap-2 text-[11px] font-bold">
            <button onClick={() => setCategoryAll(category, true)} className="text-[#00866a] underline">Show all of “{category}” in app</button>
            <button onClick={() => setCategoryAll(category, false)} className="text-[#566373] underline">Hide all</button>
          </div>
        )}

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((c) => (
            <div key={c.id}
              className={`flex flex-col rounded-lg border p-3 transition ${c.enabled ? "border-[#009b77] bg-[#f2fbf8]" : "border-[#e0e3e1] bg-white"}`}>
              <div className="flex items-start gap-2">
                <button onClick={() => toggle(c.id)} aria-pressed={c.enabled} title={c.enabled ? "Hide in app" : "Show in app"}
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border text-[12px] font-bold ${
                    c.enabled ? "border-[#009b77] bg-[#009b77] text-white" : "border-[#c6ccd1] bg-white text-transparent"}`}>
                  ✓
                </button>
                <div className="min-w-0 flex-1 cursor-pointer" onClick={() => toggle(c.id)}>
                  <div className="text-[14px] font-bold leading-snug text-[#292f33]">“{c.en}”</div>
                  <div className="mt-0.5 text-[12px] text-[#657078]">{c.de}</div>
                </div>
              </div>
              <div className="mt-auto flex items-center gap-1.5 pt-3 text-[10px] font-bold uppercase tracking-[0.05em]">
                <span className="rounded bg-[#f0f2f3] px-1.5 py-0.5 text-[#566373]">{c.category}</span>
                {(c.answer_en || c.answer_de) ? (
                  <span className="rounded bg-[#fff4e0] px-1.5 py-0.5 text-[#9a5b00]" title={c.answer_en || c.answer_de}>Fixed answer</span>
                ) : (
                  <span className="rounded bg-[#e8f1fb] px-1.5 py-0.5 text-[#1d5fa8]">AI answers</span>
                )}
                <button onClick={() => setEditing({ ...c })} className="ml-auto text-[11px] normal-case text-[#36414b] underline">Edit</button>
                {!c.builtin && (
                  <button onClick={() => setCards((p) => p.filter((x) => x.id !== c.id))}
                    className="text-[11px] normal-case text-[#a33] underline">Delete</button>
                )}
              </div>
            </div>
          ))}
          {visible.length === 0 && <div className="col-span-full py-10 text-center text-[13px] text-[#8a949c]">No cards here.</div>}
        </div>
      </section>

      {/* ---------------- app list + preview ---------------- */}
      <section className="h-fit rounded-lg border border-[#d8dde1] bg-white p-5 lg:sticky lg:top-4">
        <div className="flex items-center justify-between">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">
            In the app <span className="text-[#8a949c]">({inApp.length}/{maxInApp})</span>
          </h2>
          <div className="flex overflow-hidden rounded border border-[#c6ccd1] text-[11px] font-bold">
            {[false, true].map((de) => (
              <button key={String(de)} onClick={() => setPreviewDe(de)}
                className={`px-2.5 py-1 ${previewDe === de ? "bg-[#009b77] text-white" : "bg-white text-[#36414b]"}`}>
                {de ? "DE" : "EN"}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-1 text-[12px] text-[#657078]">Order as visitors see them under “Try asking”.</p>

        <div className="mt-3 max-h-[52vh] overflow-y-auto rounded-xl border border-[#d8dde1] bg-[#f4f7f5] p-3">
          <div className="mb-2 text-[11px] font-semibold text-[#657078]">{previewDe ? "Probieren Sie" : "Try asking"}</div>
          {inApp.length === 0 && <div className="py-6 text-center text-[12px] text-[#8a949c]">No cards – the app shows its built-in examples.</div>}
          {inApp.map((c, i) => (
            <div key={c.id} className="mb-1.5 flex items-center gap-1 rounded-2xl bg-[#e3f4ee] py-1.5 pl-3 pr-1.5">
              <span className="flex-1 text-[13px] text-[#00664f]">“{previewDe ? c.de || c.en : c.en}”</span>
              <button disabled={i === 0} onClick={() => move(c.id, -1)} className="px-1 text-[12px] text-[#36414b] disabled:opacity-25" title="Up">▲</button>
              <button disabled={i === inApp.length - 1} onClick={() => move(c.id, 1)} className="px-1 text-[12px] text-[#36414b] disabled:opacity-25" title="Down">▼</button>
              <button onClick={() => toggle(c.id)} className="px-1 text-[12px] text-[#a33]" title="Remove from app">✕</button>
            </div>
          ))}
        </div>

        <div className="mt-4 flex gap-2">
          <button disabled={!dirty || busy} onClick={() => void save()}
            className="flex-1 rounded bg-[#009b77] py-2 text-[13px] font-bold text-white disabled:opacity-40">
            {busy ? "Saving…" : dirty ? "Save & push to app" : "Saved"}
          </button>
          <button disabled={!dirty || busy} onClick={() => setCards(saved)}
            className="rounded border border-[#c6ccd1] px-3 text-[12px] font-bold text-[#36414b] disabled:opacity-40">
            Undo
          </button>
        </div>
      </section>

      {editing && (
        <CardEditor card={editing} categories={categories} onCancel={() => setEditing(null)} onSave={saveEdit} flash={flash} />
      )}
    </div>
  );
}

function CardEditor({ card, categories, onCancel, onSave, flash }: {
  card: TalkCard;
  categories: string[];
  onCancel: () => void;
  onSave: (c: TalkCard) => void;
  flash: (text: string, error?: boolean) => void;
}) {
  const [c, setC] = useState<TalkCard>(card);
  const [translating, setTranslating] = useState<string | null>(null);

  async function translate(from: "en" | "answer_en", to: "de" | "answer_de") {
    if (!c[from].trim()) return;
    setTranslating(to);
    try {
      const r = await postJson<{ text: string }>("/api/map/translate", { text: c[from], source: "en", target: "de" }, 120000);
      setC((x) => ({ ...x, [to]: r.text }));
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    } finally {
      setTranslating(null);
    }
  }

  const field = "mt-1 w-full rounded border border-[#c6ccd1] px-3 py-2 text-[14px] text-[#292f33] outline-none focus:border-[#009b77]";
  const lbl = "mt-3 block text-[12px] font-semibold text-[#566373]";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onCancel}>
      <div className="max-h-[90vh] w-full max-w-[560px] overflow-y-auto rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[16px] font-bold text-[#292f33]">{card.en ? "Edit card" : "New speaking card"}</h3>

        <label className={lbl}>Card text – English (what the visitor asks)
          <input className={field} value={c.en} maxLength={120} onChange={(e) => setC({ ...c, en: e.target.value })} placeholder="What is this robot doing?" />
        </label>
        <label className={lbl}>
          <span className="flex items-center justify-between">German
            <button onClick={() => void translate("en", "de")} disabled={!c.en.trim() || translating !== null}
              className="text-[11px] font-bold text-[#00866a] underline disabled:opacity-40">
              {translating === "de" ? "Translating…" : "Translate from English"}
            </button>
          </span>
          <input className={field} value={c.de} maxLength={120} onChange={(e) => setC({ ...c, de: e.target.value })} placeholder="(empty = English text)" />
        </label>
        <label className={lbl}>Category
          <input className={field} list="talk-card-categories" value={c.category} maxLength={30} onChange={(e) => setC({ ...c, category: e.target.value })} />
          <datalist id="talk-card-categories">{categories.map((k) => <option key={k} value={k} />)}</datalist>
        </label>

        <div className="mt-5 rounded border border-[#f2e2c4] bg-[#fffaf0] p-3">
          <div className="text-[12px] font-bold text-[#9a5b00]">Fixed answer (optional)</div>
          <div className="text-[11px] text-[#8a6a2f]">Empty = the AI answers. Filled = G1 always says exactly this – instant and reliable for the demo.</div>
          <label className={lbl}>English answer
            <textarea className={`${field} h-[64px]`} value={c.answer_en} maxLength={400} onChange={(e) => setC({ ...c, answer_en: e.target.value })} />
          </label>
          <label className={lbl}>
            <span className="flex items-center justify-between">German answer
              <button onClick={() => void translate("answer_en", "answer_de")} disabled={!c.answer_en.trim() || translating !== null}
                className="text-[11px] font-bold text-[#00866a] underline disabled:opacity-40">
                {translating === "answer_de" ? "Translating…" : "Translate from English"}
              </button>
            </span>
            <textarea className={`${field} h-[64px]`} value={c.answer_de} maxLength={400} onChange={(e) => setC({ ...c, answer_de: e.target.value })} />
          </label>
        </div>

        <label className="mt-4 flex items-center gap-2 text-[13px] font-bold text-[#36414b]">
          <input type="checkbox" checked={c.enabled} onChange={(e) => setC({ ...c, enabled: e.target.checked })} />
          Show in the app
        </label>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded border border-[#c6ccd1] px-4 py-2 text-[13px] font-bold text-[#36414b]">Cancel</button>
          <button onClick={() => onSave({ ...c, en: c.en.trim(), de: c.de.trim(), category: c.category.trim() || "My cards" })}
            className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white">Done</button>
        </div>
        <p className="mt-2 text-right text-[11px] text-[#8a949c]">Then press “Save &amp; push to app”.</p>
      </div>
    </div>
  );
}
