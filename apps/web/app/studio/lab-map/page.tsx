"use client";

// G1 Studio - Lab Map (digital twin)
// Session 03 map with taught routes, tour stops, HOME and the live G1 position.

import { useCallback, useEffect, useMemo, useState } from "react";
import LabMapCanvas, { MapInfo, MapRoute, Pose, ROUTE_COLORS } from "@/components/studio/LabMapCanvas";
import { apiBase, getJson, postJson } from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";
import TourEditor from "@/components/studio/TourEditor";

type Alignment = {
  home: { x: number; y: number; yaw: number } | null;
  routes: Record<string, { fit: number; ok: boolean }>;
};

type LiveResponse = {
  pose: (Pose & { source: string; age_s: number | null; route: string | null; state: string }) | null;
  detail?: string;
};

export default function LabMapPage() {
  const { ensurePin, forgetPin, pinDialog } = usePin();
  const [info, setInfo] = useState<(MapInfo & { alignment: Alignment }) | null>(null);
  const [error, setError] = useState("");
  const [routes, setRoutes] = useState<MapRoute[]>([]);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [live, setLive] = useState<LiveResponse["pose"]>(null);
  const [liveDetail, setLiveDetail] = useState("");
  const [showLabels, setShowLabels] = useState(true);
  const [placingHome, setPlacingHome] = useState(false);
  const [draftHome, setDraftHome] = useState<Pose | null>(null);
  const [selectedRoute, setSelectedRoute] = useState<string | null>(null);
  const [selectedStop, setSelectedStop] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [showBlocked, setShowBlocked] = useState(false);
  const [blockedSpots, setBlockedSpots] = useState<[number, number][]>([]);

  const flash = useCallback((text: string, isError = false) => {
    setMessage({ text, error: isError });
    setTimeout(() => setMessage(null), 7000);
  }, []);

  const load = useCallback(async () => {
    try {
      const [i, r] = await Promise.all([
        getJson<MapInfo & { alignment: Alignment }>("/api/map/info"),
        getJson<MapRoute[]>("/api/map/routes"),
      ]);
      setInfo(i);
      setRoutes(r);
      setVisible((v) => {
        const next = { ...v };
        r.forEach((route) => {
          if (next[route.name] === undefined) next[route.name] = true;
        });
        return next;
      });
      setSelectedRoute((s) => s || r.find((x) => x.kind === "tour")?.name || r[0]?.name || null);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Map not available");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const res = await getJson<LiveResponse>("/api/map/live", 3000);
        if (!alive) return;
        setLive(res.pose);
        setLiveDetail(res.pose ? "" : res.detail || "Place HOME on the map to see G1");
      } catch {
        if (alive) {
          setLive(null);
          setLiveDetail("Studio backend offline");
        }
      }
    }
    void poll();
    const t = setInterval(poll, 1000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!showBlocked) {
      setBlockedSpots([]);
      return;
    }
    getJson<{ runs: { blocked_map?: [number, number][]; excluded?: boolean }[] }>("/api/runs")
      .then((d) => setBlockedSpots(d.runs.filter((r) => !r.excluded).flatMap((r) => r.blocked_map || [])))
      .catch(() => setBlockedSpots([]));
  }, [showBlocked]);

  async function withPin(run: (pin: string) => Promise<void>) {
    const pin = await ensurePin();
    if (!pin) return;
    try {
      await run(pin);
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      if (/PIN/i.test(text)) forgetPin();
      flash(text, true);
    }
  }

  async function saveHome() {
    if (!draftHome) return;
    await withPin(async (pin) => {
      await postJson("/api/map/home", { pin, ...draftHome });
      setPlacingHome(false);
      setDraftHome(null);
      await load();
      flash("HOME saved. Now press “Align to map” for each route with a HOME scan.");
    });
  }

  async function alignRoute(name: string) {
    await withPin(async (pin) => {
      setBusy(name);
      try {
        const r = await postJson<{ fit: number; ok: boolean }>(`/api/map/align/${encodeURIComponent(name)}`, { pin }, 180000);
        await load();
        flash(
          r.ok
            ? `'${name}' aligned to the map (match ${Math.round(r.fit * 100)}%).`
            : `'${name}': weak match (${Math.round(r.fit * 100)}%) – move HOME closer to the real spot and try again.`,
          !r.ok,
        );
      } finally {
        setBusy(null);
      }
    });
  }

  const home = info?.alignment?.home ?? null;
  const route = useMemo(() => routes.find((r) => r.name === selectedRoute) || null, [routes, selectedRoute]);
  const routeColor = (name: string) => ROUTE_COLORS[Math.max(0, routes.findIndex((r) => r.name === name)) % ROUTE_COLORS.length];

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {pinDialog}
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1700px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Lab Map</h1>
          </div>
          <p className="text-[13px] text-[#657078]">
            Session 03 map · routes, tour stops, HOME and live G1 position
          </p>
          <div className="ml-auto flex items-center gap-4 text-[13px]">
            {live ? (
              <span className="rounded-full bg-[#eaf7f2] px-3 py-1.5 font-semibold text-[#00866a]">
                G1 live · {live.source === "route" ? `on ${live.route}` : "since guide start"}
                {live.age_s !== null && live.age_s > 2 ? ` · ${live.age_s.toFixed(0)} s old` : ""}
              </span>
            ) : (
              <span className="rounded-full bg-[#f0f2f3] px-3 py-1.5 font-semibold text-[#566373]">{liveDetail}</span>
            )}
            <label className="flex items-center gap-2 font-semibold text-[#566373]">
              <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />
              Labels
            </label>
            <label className="flex items-center gap-2 font-semibold text-[#566373]" title="Where G1 had to wait (from the run log)">
              <input type="checkbox" checked={showBlocked} onChange={(e) => setShowBlocked(e.target.checked)} />
              Blocked spots{showBlocked ? ` (${blockedSpots.length})` : ""}
            </label>
          </div>
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

      <div className="mx-auto grid max-w-[1700px] grid-cols-1 gap-6 px-6 py-6 md:px-10 xl:grid-cols-[1fr_380px]">
        <div className="h-[calc(100vh-230px)] min-h-[520px] rounded-lg border border-[#d8dde1] bg-white p-2">
          {error ? (
            <div className="flex h-full items-center justify-center text-[14px] text-[#b42020]">{error}</div>
          ) : info ? (
            <LabMapCanvas
              info={info}
              imageUrl={`${apiBase()}/api/map/image.png`}
              routes={routes}
              visible={visible}
              home={home}
              live={live}
              showLabels={showLabels}
              placingHome={placingHome}
              draftHome={draftHome}
              onDraftHome={setDraftHome}
              selectedStop={selectedStop}
              blockedSpots={blockedSpots}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-[14px] text-[#657078]">Loading map…</div>
          )}
        </div>

        <aside className="space-y-6">
          {/* HOME */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">HOME on the map</h2>
            <p className="mt-2 text-[12px] leading-[18px] text-[#657078]">
              {home
                ? `x ${home.x.toFixed(2)} m, y ${home.y.toFixed(2)} m, facing ${((home.yaw * 180) / Math.PI).toFixed(0)}°`
                : "Not placed yet. Place the HOME tape spot once – routes and the live G1 then appear in the right place."}
            </p>
            {!placingHome ? (
              <button
                onClick={() => {
                  setPlacingHome(true);
                  setDraftHome(home);
                }}
                className="mt-3 rounded border border-[#c6ccd1] px-4 py-2 text-[13px] font-bold text-[#36414b] hover:border-[#009b77]"
              >
                {home ? "Move HOME" : "Place HOME"}
              </button>
            ) : (
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => void saveHome()}
                  disabled={!draftHome}
                  className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
                >
                  Save HOME
                </button>
                <button
                  onClick={() => {
                    setPlacingHome(false);
                    setDraftHome(null);
                  }}
                  className="rounded px-4 py-2 text-[13px] font-semibold text-[#566373] hover:bg-[#f0f2f3]"
                >
                  Cancel
                </button>
              </div>
            )}
          </section>

          {/* routes */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Routes & tours</h2>
              <button onClick={() => void load()} className="text-[12px] font-semibold text-[#00866a] hover:underline">
                Reload
              </button>
            </div>
            <ul className="mt-3 space-y-3">
              {routes.map((r) => (
                <li
                  key={r.name}
                  className={`rounded-md border p-3 ${selectedRoute === r.name ? "border-[#009b77] bg-[#f4fbf8]" : "border-[#e4e8eb]"}`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={!!visible[r.name]}
                      onChange={(e) => setVisible({ ...visible, [r.name]: e.target.checked })}
                    />
                    <span className="h-3 w-3 rounded-full" style={{ background: routeColor(r.name) }} />
                    <button onClick={() => setSelectedRoute(r.name)} className="min-w-0 flex-1 text-left">
                      <p className="truncate text-[13px] font-bold text-[#292f33]">
                        {r.kind === "tour" ? "Tour · " : ""}
                        {r.title_en || r.name}
                      </p>
                      <p className="text-[11px] text-[#657078]">
                        {r.length_m} m{r.stops.length ? ` · ${r.stops.length} stops` : ""} · {r.created.slice(0, 10)}
                      </p>
                    </button>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span
                      className={`text-[11px] font-semibold ${
                        r.alignment.source === "scan" ? "text-[#00866a]" : r.alignment.source === "home" ? "text-[#9a6812]" : "text-[#87919c]"
                      }`}
                    >
                      {r.alignment.source === "scan"
                        ? `Aligned to map (${Math.round((r.alignment.fit ?? 0) * 100)}%)`
                        : r.alignment.source === "home"
                          ? "Approximate (from HOME) – dashed"
                          : "Place HOME first"}
                    </span>
                    {r.home_scan ? (
                      <button
                        onClick={() => void alignRoute(r.name)}
                        disabled={!home || busy !== null}
                        className="rounded border border-[#c6ccd1] px-2.5 py-1 text-[11px] font-bold text-[#36414b] hover:border-[#009b77] disabled:opacity-40"
                      >
                        {busy === r.name ? "Aligning…" : "Align to map"}
                      </button>
                    ) : (
                      <span className="text-[11px] text-[#87919c]">no HOME scan</span>
                    )}
                  </div>
                </li>
              ))}
              {!routes.length && !error && <li className="text-[13px] text-[#657078]">No routes found.</li>}
            </ul>
          </section>

          {/* tour editor for the selected route */}
          {route && (
            <TourEditor
              key={route.name}
              route={route}
              color={routeColor(route.name)}
              withPin={withPin}
              onSaved={load}
              flash={flash}
              onHoverStop={setSelectedStop}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
