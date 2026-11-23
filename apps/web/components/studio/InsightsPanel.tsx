"use client";

// Visitor questions -> better answers.
// Left: what visitors ask most + where G1 had to say "I don't know" (from the conversation log).
// Right: the lab knowledge G1 may use (edit facts, test which facts a question finds).
// One click turns a question into a speaking card (optionally with a fixed answer) or a new fact.

import { useCallback, useEffect, useState } from "react";
import { getJson, postJson, sendJson } from "@/lib/g1api";

type Q = {
  question: string;
  count: number;
  sources: Record<string, number>;
  langs: Record<string, number>;
  last: string;
  answer: string;
  weak: number;
  weak_last: boolean;
  avg_s: number | null;
};
type Questions = { days: number; total: number; distinct: number; weak_count: number; top: Q[]; weak: Q[] };
type Entry = { id?: string; title: string; keywords: string[] | string; facts: string };

const SRC: Record<string, string> = { app: "App", mic: "Mic", studio: "Studio" };

export default function InsightsPanel({
  ensurePin,
  forgetPin,
  flash,
}: {
  ensurePin: () => Promise<string | null>;
  forgetPin: () => void;
  flash: (text: string, error?: boolean) => void;
}) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Questions | null>(null);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [savedEntries, setSavedEntries] = useState<string>("");
  const [test, setTest] = useState("");
  const [matches, setMatches] = useState<{ title: string; facts: string }[] | null>(null);
  const [card, setCard] = useState<{ en: string; answer_en: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getJson<Questions>(`/api/insights/questions?days=${days}`));
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    }
  }, [days, flash]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    getJson<{ entries: Entry[] }>("/api/knowledge")
      .then((r) => {
        setEntries(r.entries);
        setSavedEntries(JSON.stringify(r.entries));
      })
      .catch((e) => flash(e instanceof Error ? e.message : String(e), true));
  }, [flash]);

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

  const kwText = (k: Entry["keywords"]) => (Array.isArray(k) ? k.join(", ") : k);
  const dirty = entries !== null && JSON.stringify(entries) !== savedEntries;

  function addFact(question: string) {
    const words = question.toLowerCase().match(/[\wäöüß]{4,}/g) || [];
    setEntries((e) => [{ title: question.replace(/\?$/, "").slice(0, 80), keywords: Array.from(new Set(words)).slice(0, 6), facts: "" }, ...(e || [])]);
    flash("New fact added at the top of “Lab knowledge” – write the facts and save.");
  }

  async function saveKnowledge() {
    if (!entries) return;
    await withPin(async (pin) => {
      const r = await sendJson<{ entries: Entry[] }>("PUT", "/api/knowledge", {
        pin,
        entries: entries.map((e) => ({ ...e, keywords: kwText(e.keywords).split(",").map((k) => k.trim()).filter(Boolean) })),
      });
      setEntries(r.entries);
      setSavedEntries(JSON.stringify(r.entries));
      flash(`Knowledge saved (${r.entries.length} entries) – G1 uses it from the next question on.`);
    });
  }

  async function runTest() {
    if (!test.trim()) return;
    try {
      setMatches((await postJson<{ matches: { title: string; facts: string }[] }>("/api/knowledge/match", { question: test })).matches);
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    }
  }

  async function saveCard() {
    if (!card?.en.trim()) return;
    await withPin(async (pin) => {
      const all = await getJson<{ cards: unknown[] }>("/api/interaction/cards");
      const fresh = { id: `q${Date.now()}`, category: "Visitor questions", en: card.en.trim(), de: "",
        answer_en: card.answer_en.trim(), answer_de: "", enabled: true, builtin: false };
      await sendJson("PUT", "/api/interaction/cards", { pin, cards: [...all.cards, fresh] });
      setCard(null);
      flash("Speaking card created and shown in the app (Interaction → Speaking cards to add German / reorder).");
    });
  }

  const Row = ({ q, weak }: { q: Q; weak?: boolean }) => (
    <div className={`rounded-lg border p-3 ${weak ? "border-[#f2e2c4] bg-[#fffaf0]" : "border-[#e0e3e1] bg-white"}`}>
      <div className="flex items-start gap-2">
        <span className="mt-0.5 rounded bg-[#292f33] px-1.5 text-[11px] font-bold text-white">{q.count}×</span>
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-bold text-[#292f33]">“{q.question}”</div>
          <div className="mt-1 line-clamp-2 text-[12px] text-[#566373]"><b>G1:</b> {q.answer}</div>
          <div className="mt-1 text-[11px] text-[#8a949c]">
            {Object.entries(q.sources).map(([k, v]) => `${SRC[k] || k} ${v}`).join(" · ")}
            {q.avg_s != null && ` · ${q.avg_s} s`} · last {q.last.slice(5, 16).replace("T", " ")}
          </div>
        </div>
      </div>
      <div className="mt-2 flex justify-end gap-3 text-[11px] font-bold">
        <button onClick={() => addFact(q.question)} className="text-[#36414b] underline">Add lab fact</button>
        <button onClick={() => setCard({ en: q.question, answer_en: weak ? "" : q.answer })} className="text-[#00866a] underline">
          Make speaking card
        </button>
      </div>
    </div>
  );

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
      {/* ---------------- questions ---------------- */}
      <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Visitor questions</h2>
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`rounded-full px-3 py-1 text-[11px] font-bold ${days === d ? "bg-[#292f33] text-white" : "bg-[#f0f2f3] text-[#566373]"}`}>
              {d} days
            </button>
          ))}
          <button onClick={() => void load()} className="text-[11px] font-bold text-[#36414b] underline">Refresh</button>
        </div>
        {data && (
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <Kpi label="Questions" value={data.total} />
            <Kpi label="Different" value={data.distinct} />
            <Kpi label="Need better answer" value={data.weak_count} warn={data.weak_count > 0} />
          </div>
        )}

        <h3 className="mt-5 text-[11px] font-bold uppercase tracking-[0.08em] text-[#9a5b00]">G1 could not answer well</h3>
        <div className="mt-2 flex flex-col gap-2">
          {data?.weak.length === 0 && <div className="text-[12px] text-[#8a949c]">Nothing – every question got a real answer.</div>}
          {data?.weak.slice(0, 15).map((q) => <Row key={q.question + q.last} q={q} weak />)}
        </div>

        <h3 className="mt-5 text-[11px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Most asked</h3>
        <div className="mt-2 flex max-h-[600px] flex-col gap-2 overflow-y-auto">
          {data?.top.length === 0 && <div className="text-[12px] text-[#8a949c]">No questions yet.</div>}
          {data?.top.slice(0, 40).map((q) => <Row key={q.question + q.last} q={q} />)}
        </div>
      </section>

      {/* ---------------- knowledge ---------------- */}
      <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
        <div className="flex items-center gap-2">
          <h2 className="mr-auto text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">
            Lab knowledge <span className="text-[#8a949c]">({entries?.length ?? 0})</span>
          </h2>
          <button onClick={() => setEntries((e) => [{ title: "", keywords: [], facts: "" }, ...(e || [])])}
            className="rounded border border-[#c6ccd1] px-3 py-1.5 text-[12px] font-bold text-[#36414b]">+ Fact</button>
          <button disabled={!dirty || busy} onClick={() => void saveKnowledge()}
            className="rounded bg-[#009b77] px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-40">
            {dirty ? "Save knowledge" : "Saved"}
          </button>
        </div>
        <p className="mt-1 text-[12px] text-[#657078]">
          G1 only uses verified facts from here for lab questions. A fact is used when the question contains one of its keywords.
        </p>

        <div className="mt-3 flex gap-2">
          <input value={test} onChange={(e) => setTest(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void runTest(); }}
            placeholder="Test a question: which facts does G1 find?"
            className="flex-1 rounded border border-[#c6ccd1] px-3 py-1.5 text-[13px] outline-none focus:border-[#009b77]" />
          <button onClick={() => void runTest()} className="rounded border border-[#c6ccd1] px-3 text-[12px] font-bold text-[#36414b]">Test</button>
        </div>
        {matches && (
          <div className="mt-2 rounded border border-[#e0e3e1] bg-[#f7f8f7] p-2 text-[12px] text-[#36414b]">
            {matches.length === 0 ? "No fact found – G1 will say it does not know lab details. Add a fact or keywords." :
              matches.map((m) => <div key={m.title}>✓ <b>{m.title}</b></div>)}
          </div>
        )}

        <div className="mt-4 flex max-h-[760px] flex-col gap-3 overflow-y-auto pr-1">
          {entries?.map((e, i) => (
            <div key={i} className="rounded-lg border border-[#e0e3e1] p-3">
              <div className="flex gap-2">
                <input value={e.title} placeholder="Title (e.g. Opening hours)" maxLength={80}
                  onChange={(ev) => setEntries((all) => all!.map((x, j) => (j === i ? { ...x, title: ev.target.value } : x)))}
                  className="flex-1 rounded border border-[#c6ccd1] px-2 py-1 text-[13px] font-bold outline-none focus:border-[#009b77]" />
                <button onClick={() => setEntries((all) => all!.filter((_, j) => j !== i))} className="text-[11px] font-bold text-[#a33] underline">Delete</button>
              </div>
              <input value={kwText(e.keywords)} placeholder="keywords, comma separated (EN + DE)"
                onChange={(ev) => setEntries((all) => all!.map((x, j) => (j === i ? { ...x, keywords: ev.target.value } : x)))}
                className="mt-2 w-full rounded border border-[#c6ccd1] px-2 py-1 text-[12px] text-[#566373] outline-none focus:border-[#009b77]" />
              <textarea value={e.facts} placeholder="Facts G1 may say (short, verified)" maxLength={1500}
                onChange={(ev) => setEntries((all) => all!.map((x, j) => (j === i ? { ...x, facts: ev.target.value } : x)))}
                className="mt-2 h-[70px] w-full rounded border border-[#c6ccd1] px-2 py-1 text-[13px] outline-none focus:border-[#009b77]" />
            </div>
          ))}
        </div>
      </section>

      {card && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setCard(null)}>
          <div className="w-full max-w-[520px] rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-[16px] font-bold text-[#292f33]">New speaking card</h3>
            <label className="mt-3 block text-[12px] font-semibold text-[#566373]">Card text (English)
              <input value={card.en} maxLength={120} onChange={(e) => setCard({ ...card, en: e.target.value })}
                className="mt-1 w-full rounded border border-[#c6ccd1] px-3 py-2 text-[14px] outline-none focus:border-[#009b77]" />
            </label>
            <label className="mt-3 block text-[12px] font-semibold text-[#566373]">Fixed answer (optional – empty = AI answers)
              <textarea value={card.answer_en} maxLength={400} onChange={(e) => setCard({ ...card, answer_en: e.target.value })}
                className="mt-1 h-[90px] w-full rounded border border-[#c6ccd1] px-3 py-2 text-[14px] outline-none focus:border-[#009b77]" />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setCard(null)} className="rounded border border-[#c6ccd1] px-4 py-2 text-[13px] font-bold text-[#36414b]">Cancel</button>
              <button disabled={busy || !card.en.trim()} onClick={() => void saveCard()}
                className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40">Create &amp; show in app</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className={`rounded border px-2 py-2 ${warn ? "border-[#f2e2c4] bg-[#fffaf0]" : "border-[#e0e3e1] bg-[#f7f8f7]"}`}>
      <div className={`text-[20px] font-bold ${warn ? "text-[#9a5b00]" : "text-[#292f33]"}`}>{value}</div>
      <div className="text-[11px] font-semibold text-[#657078]">{label}</div>
    </div>
  );
}
