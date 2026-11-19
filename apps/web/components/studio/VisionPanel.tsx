"use client";

// G1 Vision in Mission Control: "What do you see?" (local vision AI) and
// "Find the …" (G1 turns on the spot, YOLO looks, faces the object, waves).

import { useEffect, useState } from "react";
import { getJson, postJson } from "@/lib/g1api";

type VisionStatus = {
  state: string;
  task: string;
  target: string;
  message: string;
  answer: string;
  step: number;
  turned_deg: number;
};

const OBJECT_NAMES: Record<string, string> = {
  person: "Person",
  bottle: "Bottle",
  cup: "Cup",
  chair: "Chair",
  laptop: "Laptop",
  keyboard: "Keyboard",
  mouse: "Computer mouse",
  "cell phone": "Phone",
  book: "Book",
  backpack: "Backpack",
  "potted plant": "Plant",
  tv: "Screen",
  clock: "Clock",
  scissors: "Scissors",
  "dining table": "Table",
  umbrella: "Umbrella",
  "sports ball": "Ball",
  "teddy bear": "Teddy bear",
};

const STATE_TEXT: Record<string, string> = {
  idle: "Ready",
  describing: "Looking…",
  searching: "Searching…",
  turning: "Turning…",
  found: "Found!",
  not_found: "Not found",
  cancelled: "Cancelled",
  error: "Error",
};

export default function VisionPanel({
  withPin,
  lang,
}: {
  withPin: (run: (pin: string) => Promise<void>) => Promise<void>;
  lang: "en" | "de";
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [describing, setDescribing] = useState(false);
  const [objects, setObjects] = useState<string[]>([]);
  const [target, setTarget] = useState("bottle");
  const [status, setStatus] = useState<VisionStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getJson<string[]>("/api/mission/vision/objects")
      .then((o) => {
        setObjects(o);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const s = await getJson<VisionStatus>("/api/mission/vision/status", 3000);
        if (alive) setStatus(s);
      } catch {
        if (alive) setStatus(null);
      }
    };
    void poll();
    const t = setInterval(poll, 1000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  async function describe() {
    setDescribing(true);
    setError("");
    setAnswer("");
    try {
      const r = await postJson<{ answer: string }>("/api/mission/vision/describe", { question, lang }, 160000);
      setAnswer(r.answer);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDescribing(false);
    }
  }

  async function find() {
    setError("");
    await withPin(async (pin) => {
      await postJson("/api/mission/vision/find", { pin, object: target, lang });
    });
  }

  async function cancel() {
    try {
      await postJson("/api/mission/vision/cancel");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const busy = !!status && ["describing", "searching", "turning"].includes(status.state);
  const finding = !!status && status.task === "find" && ["searching", "turning"].includes(status.state);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {error && <p className="rounded bg-[#fdecec] p-2 text-[12px] font-semibold text-[#b42020] lg:col-span-2">{error}</p>}

      <div>
        <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-[#566373]">Ask G1 what it sees</p>
        <div className="mt-2 flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !describing) void describe();
            }}
            placeholder={lang === "en" ? "What do you see?  /  What is this?" : "Was siehst du?  /  Was ist das?"}
            className="min-w-0 flex-1 rounded border border-[#c6ccd1] px-3 py-2 text-[14px] outline-none focus:border-[#009b77]"
          />
          <button
            onClick={() => void describe()}
            disabled={describing || busy}
            className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
          >
            {describing ? "Looking…" : "👁 Ask"}
          </button>
        </div>
        {answer && (
          <p className="mt-2 rounded-md bg-[#eaf7f2] p-3 text-[14px] leading-[20px] text-[#1f4d40]">
            <b>G1:</b> {answer}
          </p>
        )}
        {describing && (
          <p className="mt-2 text-[12px] text-[#87919c]">The first question after a restart takes up to a minute (the vision model loads).</p>
        )}
      </div>

      <div className="border-t border-[#e4e8eb] pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
        <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-[#566373]">Find an object</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="rounded border border-[#c6ccd1] bg-white px-3 py-2 text-[14px]"
          >
            {(objects.length ? objects : Object.keys(OBJECT_NAMES)).map((o) => (
              <option key={o} value={o}>
                {OBJECT_NAMES[o] || o}
              </option>
            ))}
          </select>
          <button
            onClick={() => void find()}
            disabled={busy}
            className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
          >
            🔍 Find
          </button>
          <button
            onClick={() => void cancel()}
            disabled={!finding}
            className="rounded border border-[#c6ccd1] px-4 py-2 text-[13px] font-bold text-[#36414b] disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
        {status && status.task === "find" && (
          <p className="mt-2 text-[13px] text-[#36414b]">
            <b>{STATE_TEXT[status.state] || status.state}</b>
            {status.target ? ` · ${OBJECT_NAMES[status.target] || status.target}` : ""}
            {finding ? ` · look ${status.step}/12 · turned ${Math.round(status.turned_deg)}°` : ""}
            {status.message && !finding ? ` · ${status.message}` : ""}
          </p>
        )}
        <p className="mt-2 text-[11px] text-[#87919c]">
          G1 turns on the spot (up to a full circle) – keep 1 m free around it. Needs walking mode and the joystick locked.
        </p>
      </div>
    </div>
  );
}
