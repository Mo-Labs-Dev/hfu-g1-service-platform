"use client";

// Visitor feedback from the G1 Remote app: stars, recommendation, SUS (System Usability Scale).

import { useEffect, useState } from "react";
import { apiBase, getJson } from "@/lib/g1api";

type Item = {
  time: string;
  lang: string;
  context: string;
  rating: number | null;
  recommend: string | null;
  sus_score: number | null;
  comment: string;
};
type Stats = {
  count: number;
  avg_rating: number | null;
  ratings: Record<string, number>;
  sus_count: number;
  sus_mean: number | null;
  sus_sd: number | null;
  recommend_yes_pct: number | null;
  recommend: { yes: number; maybe: number; no: number };
};

function susGrade(score: number) {
  // Bangor et al. / Sauro: 68 = average
  if (score >= 80.3) return { label: "Excellent (A)", color: "#00866a" };
  if (score >= 68) return { label: "Good (above average)", color: "#009b77" };
  if (score >= 51) return { label: "OK (below average)", color: "#b7790f" };
  return { label: "Poor", color: "#d62828" };
}

export default function FeedbackSection() {
  const [data, setData] = useState<{ items: Item[]; stats: Stats } | null>(null);

  useEffect(() => {
    const load = () =>
      getJson<{ items: Item[]; stats: Stats }>("/api/feedback")
        .then(setData)
        .catch(() => setData(null));
    void load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const s = data?.stats;
  const maxR = Math.max(1, ...Object.values(s?.ratings || { "1": 0 }));
  const comments = (data?.items || []).filter((i) => i.comment).slice(0, 8);

  return (
    <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Visitor feedback</h2>
        <a href={`${apiBase()}/api/feedback/export.csv`} className="rounded bg-[#009b77] px-3 py-1.5 text-[12px] font-bold text-white">
          ⬇ CSV
        </a>
      </div>
      {!s || s.count === 0 ? (
        <p className="mt-3 text-[13px] text-[#657078]">
          No feedback yet. After each tour the app asks visitors for stars, a recommendation and (optionally) the 10 SUS questions.
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="space-y-3">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">Responses</p>
              <p className="text-[28px] font-bold text-[#292f33]">{s.count}</p>
            </div>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">Average rating</p>
              <p className="text-[28px] font-bold text-[#292f33]">
                {s.avg_rating ?? "—"} <span className="text-[18px] text-[#d79616]">★</span>
              </p>
            </div>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">Would recommend G1</p>
              <p className="text-[28px] font-bold text-[#292f33]">{s.recommend_yes_pct != null ? `${s.recommend_yes_pct} %` : "—"}</p>
              <p className="text-[11px] text-[#87919c]">
                yes {s.recommend.yes} · maybe {s.recommend.maybe} · no {s.recommend.no}
              </p>
            </div>
          </div>

          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">SUS score (usability, 0–100)</p>
            {s.sus_mean != null ? (
              <>
                <p className="mt-1 text-[40px] font-bold leading-none" style={{ color: susGrade(s.sus_mean).color }}>
                  {s.sus_mean}
                </p>
                <p className="mt-1 text-[13px] font-semibold" style={{ color: susGrade(s.sus_mean).color }}>
                  {susGrade(s.sus_mean).label}
                </p>
                <p className="mt-1 text-[11px] text-[#87919c]">
                  n = {s.sus_count}
                  {s.sus_sd != null ? ` · SD ${s.sus_sd}` : ""} · 68 = average usability
                </p>
              </>
            ) : (
              <p className="mt-2 text-[13px] text-[#657078]">No SUS answers yet.</p>
            )}
            <p className="mt-4 text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">Stars</p>
            <div className="mt-2 space-y-1">
              {[5, 4, 3, 2, 1].map((k) => (
                <div key={k} className="flex items-center gap-2 text-[12px]">
                  <span className="w-6 text-[#566373]">{k}★</span>
                  <div className="h-2 flex-1 rounded-full bg-[#e9edef]">
                    <div className="h-full rounded-full bg-[#d79616]" style={{ width: `${((s.ratings[String(k)] || 0) / maxR) * 100}%` }} />
                  </div>
                  <span className="w-6 text-right text-[#566373]">{s.ratings[String(k)] || 0}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">Latest comments</p>
            <ul className="mt-2 space-y-2">
              {comments.map((c, i) => (
                <li key={i} className="rounded-md bg-[#f4f6f7] p-2.5 text-[12px] leading-[17px] text-[#36414b]">
                  “{c.comment}”
                  <span className="mt-1 block text-[10px] text-[#87919c]">
                    {c.time.replace("T", " ").slice(0, 16)} · {c.context} · {c.lang.toUpperCase()}
                    {c.rating ? ` · ${c.rating}★` : ""}
                  </span>
                </li>
              ))}
              {!comments.length && <li className="text-[12px] text-[#87919c]">No comments yet.</li>}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
