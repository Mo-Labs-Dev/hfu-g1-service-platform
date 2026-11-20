"use client";

// G1 Studio - Lab Map (digital twin)
// Session 03 map with taught routes, tour stops, HOME and the live G1 position.

import { useCallback, useEffect, useMemo, useState } from "react";
import LabMapCanvas, { MapInfo, MapRoute, Pose, ROUTE_COLORS } from "@/components/studio/LabMapCanvas";
import { apiBase, getJson, postJson, sendJson } from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";
import TourEditor from "@/components/studio/TourEditor";

type Alignment = {
  home: { x: number; y: number; yaw: number } | null;
  routes: Record<string, { fit: number; ok: boolean }>;
};

type LocInfo = {
  map: [number, number, number] | null;
  quality: "good" | "weak" | "lost" | "none";
  fitness: number;
  rmse: number | null;
  fix_age_s: number | null;
  init_source: string;
  message: string;
  total_correction_m?: number;
};

type Destination = {
  name: string;
  title_en: string;
  title_de: string;
  x: number;
  y: number;
  yaw: number | null;
};

type GuideSnap = {
  state: string;
  kind?: string;
  route?: string;
  message?: string;
  path?: [number, number][] | null;
  goal?: [number, number] | null;
  replans?: number;
  blocking?: [number, number][] | null;
};

type LiveResponse = {
  pose: (Pose & { source: string; age_s: number | null; route: string | null; state: string; quality?: string }) | null;
  detail?: string;
  localizer?: LocInfo | null;
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
  const [placeFor, setPlaceFor] = useState<"home" | "g1" | "dest">("home");
  const [dests, setDests] = useState<Destination[]>([]);
  const [destTitle, setDestTitle] = useState({ en: "", de: "" });
  const [destFace, setDestFace] = useState(false);
  const [planPath, setPlanPath] = useState<{ name: string; path: [number, number][]; length: number } | null>(null);
  const [guide, setGuide] = useState<GuideSnap | null>(null);
  const [loc, setLoc] = useState<LocInfo | null>(null);
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

  const loadDests = useCallback(async () => {
    try {
      setDests(await getJson<Destination[]>("/api/map/destinations"));
    } catch {
      setDests([]);
    }
  }, []);

  useEffect(() => {
    void loadDests();
  }, [loadDests]);

  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const res = await getJson<LiveResponse>("/api/map/live", 3000);
        if (!alive) return;
        setLive(res.pose);
        setLoc(res.localizer ?? null);
        getJson<GuideSnap>("/api/map/guide", 2000)
          .then((gs) => alive && setGuide(gs))
          .catch(() => alive && setGuide(null));
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
    if (placeFor === "dest") {
      const title = destTitle.en.trim();
      if (!title) {
        flash("Give the destination a name first.", true);
        return;
      }
      await withPin(async (pin) => {
        await postJson("/api/map/destinations", {
          pin,
          title_en: title,
          title_de: destTitle.de.trim() || title,
          x: draftHome.x,
          y: draftHome.y,
          yaw: destFace ? draftHome.yaw : null,
        });
        setPlacingHome(false);
        setDraftHome(null);
        setDestTitle({ en: "", de: "" });
        await loadDests();
        flash(`Destination '${title}' saved - visitors can now choose it in the app.`);
      });
      return;
    }
    if (placeFor === "g1") {
      await withPin(async (pin) => {
        setBusy("loc");
        try {
          const r = await postJson<LocInfo>("/api/map/loc/init", { pin, ...draftHome }, 15000);
          setPlacingHome(false);
          setDraftHome(null);
          flash(`G1 position set (${r.quality}, match ${Math.round((r.fitness || 0) * 100)}%).`);
        } finally {
          setBusy(null);
        }
      });
      return;
    }
    await withPin(async (pin) => {
      await postJson("/api/map/home", { pin, ...draftHome });
      setPlacingHome(false);
      setDraftHome(null);
      await load();
      flash("HOME saved. Now press “Align to map” for each route with a HOME scan.");
    });
  }

  async function previewPlan(d: Destination) {
    setBusy(`plan:${d.name}`);
    try {
      const r = await postJson<{ path: [number, number][]; length_m: number }>("/api/map/plan", { x: d.x, y: d.y }, 20000);
      setPlanPath({ name: d.name, path: r.path, length: r.length_m });
      flash(`Planned way to '${d.title_en}': ${r.length_m.toFixed(1)} m.`);
    } catch (e) {
      setPlanPath(null);
      flash(e instanceof Error ? e.message : String(e), true);
    } finally {
      setBusy(null);
    }
  }

  async function gotoDest(d: Destination) {
    setBusy(`go:${d.name}`);
    try {
      await postJson("/api/map/goto", { destination: d.name, lang: "en" }, 20000);
      setPlanPath(null);
      flash(`G1 walks to '${d.title_en}' by itself. STOP is always in the header.`);
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    } finally {
      setBusy(null);
    }
  }

  async function deleteDest(d: Destination) {
    if (!window.confirm(`Delete destination '${d.title_en}'?`)) return;
    await withPin(async (pin) => {
      await sendJson("DELETE", `/api/map/destinations/${encodeURIComponent(d.name)}?pin=${encodeURIComponent(pin)}`);
      await loadDests();
    });
  }

  async function liveAsHome() {
    if (!live) return;
    await withPin(async (pin) => {
      await postJson("/api/map/home", { pin, x: live.x, y: live.y, yaw: live.yaw });
      await load();
      flash("HOME moved to G1's LiDAR position. (Only do this while G1 stands on the HOME tape.)");
    });
  }

  async function locAction(kind: "home" | "relocalize") {
    await withPin(async (pin) => {
      setBusy("loc");
      try {
        const r =
          kind === "home"
            ? await postJson<LocInfo>("/api/map/loc/init", { pin, home: true }, 15000)
            : await postJson<LocInfo>("/api/map/loc/relocalize", { pin }, 60000);
        flash(
          r.map
            ? `G1 found on the map (${r.quality}, match ${Math.round((r.fitness || 0) * 100)}%).`
            : r.message || "G1 not found - drive a few metres and try again.",
          !r.map,
        );
      } finally {
        setBusy(null);
      }
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
                G1 live ·{" "}
                {live.source === "lidar_localizer"
                  ? `LiDAR localization (${live.quality})`
                  : live.source === "route"
                    ? `on ${live.route}`
                    : "since guide start"}
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
              overlayPaths={[
                ...(planPath ? [{ points: planPath.path, color: "#2f6fdb", dash: true, width: 3 }] : []),
                ...(guide?.kind === "goto" && guide.path && !["done", "cancelled", "aborted", "idle"].includes(guide.state)
                  ? [{ points: guide.path, color: "#009b77", width: 4 }]
                  : []),
              ]}
              overlayCircles={[
                ...dests.map((d) => ({ x: d.x, y: d.y, r: 0.25, color: "#d79616", label: d.title_en })),
                ...(guide?.state === "blocked" && guide.blocking
                  ? guide.blocking.map(([bx, by]) => ({ x: bx, y: by, r: 0.05, color: "#b42020" }))
                  : []),
              ]}
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
            {!(placingHome && placeFor === "home") ? (
              <button
                onClick={() => {
                  setPlaceFor("home");
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

          {/* map localization (autonomous walking) */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">G1 localization</h2>
            <p className="mt-2 text-[12px] leading-[18px] text-[#657078]">
              LiDAR scan matched to the Session 03 map about once per second (map localizer, port 8006).
            </p>
            {loc ? (
              <div className="mt-3 space-y-1 text-[13px]">
                <div className="flex items-center gap-2 font-semibold">
                  <span
                    className={`inline-block h-2.5 w-2.5 rounded-full ${
                      loc.quality === "good" ? "bg-[#009b77]" : loc.quality === "weak" ? "bg-[#d79616]" : "bg-[#b42020]"
                    }`}
                  />
                  {loc.quality === "good"
                    ? "Localized"
                    : loc.quality === "weak"
                      ? "Weak - few matches"
                      : loc.quality === "lost"
                        ? "Lost - set the position again"
                        : "Not started"}
                </div>
                <div className="text-[12px] text-[#657078]">
                  match {Math.round(loc.fitness * 100)}%{loc.rmse !== null ? ` · rmse ${(loc.rmse * 100).toFixed(1)} cm` : ""}
                  {loc.fix_age_s !== null ? ` · last fix ${loc.fix_age_s.toFixed(0)} s ago` : ""}
                  {loc.init_source ? ` · start: ${loc.init_source}` : ""}
                  {loc.total_correction_m !== undefined ? ` · corrected ${(loc.total_correction_m * 100).toFixed(0)} cm since start` : ""}
                </div>
                {loc.message && <div className="text-[12px] text-[#657078]">{loc.message}</div>}
              </div>
            ) : (
              <p className="mt-3 text-[13px] font-semibold text-[#566373]">
                Localizer not running - start guide mode (g1_start_guide.sh).
              </p>
            )}
            {placingHome && placeFor === "g1" ? (
              <div className="mt-3 space-y-2">
                <p className="text-[12px] text-[#657078]">Click where G1 stands, drag towards where it looks.</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => void saveHome()}
                    disabled={!draftHome || busy === "loc"}
                    className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
                  >
                    Set G1 here
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
              </div>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  disabled={!loc || busy === "loc"}
                  onClick={() => void locAction("home")}
                  className="rounded border border-[#c6ccd1] px-3 py-2 text-[12px] font-bold text-[#36414b] hover:border-[#009b77] disabled:opacity-40"
                >
                  G1 is on HOME
                </button>
                <button
                  disabled={!loc || busy === "loc"}
                  onClick={() => {
                    setPlaceFor("g1");
                    setPlacingHome(true);
                    setDraftHome(live ? { x: live.x, y: live.y, yaw: live.yaw } : null);
                  }}
                  className="rounded border border-[#c6ccd1] px-3 py-2 text-[12px] font-bold text-[#36414b] hover:border-[#009b77] disabled:opacity-40"
                >
                  Set position…
                </button>
                <button
                  disabled={!loc || busy === "loc"}
                  onClick={() => void locAction("relocalize")}
                  className="rounded border border-[#c6ccd1] px-3 py-2 text-[12px] font-bold text-[#36414b] hover:border-[#009b77] disabled:opacity-40"
                >
                  {busy === "loc" ? "Searching…" : "Search whole map"}
                </button>
                {live?.source === "lidar_localizer" && loc?.quality === "good" && (
                  <button
                    onClick={() => void liveAsHome()}
                    title="G1 stands on the HOME tape: store its exact LiDAR position as HOME"
                    className="rounded border border-[#c6ccd1] px-3 py-2 text-[12px] font-bold text-[#36414b] hover:border-[#009b77]"
                  >
                    Save as HOME
                  </button>
                )}
              </div>
            )}
          </section>

          {/* destinations: autonomous walking */}
          <section className="rounded-lg border border-[#d8dde1] bg-white p-5">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">Destinations (autonomous)</h2>
            <p className="mt-2 text-[12px] leading-[18px] text-[#657078]">
              G1 plans its own way on the map - no recording needed. Visitors choose these in the app.
            </p>
            {guide?.kind === "goto" && !["done", "cancelled", "aborted", "idle", "offline"].includes(guide.state) && (
              <div className="mt-3 rounded bg-[#eaf7f2] px-3 py-2 text-[12px] font-semibold text-[#00866a]">
                {guide.state} · {guide.message || guide.route}
                {guide.replans ? ` · re-planned ${guide.replans}×` : ""}
              </div>
            )}
            <ul className="mt-3 space-y-2">
              {dests.length === 0 && <li className="text-[12px] text-[#657078]">No destinations yet.</li>}
              {dests.map((d) => (
                <li key={d.name} className="flex items-center gap-2 text-[13px]">
                  <span className="inline-block h-2.5 w-2.5 rounded-full bg-[#d79616]" />
                  <span className="flex-1 font-semibold text-[#36414b]">
                    {d.title_en}
                    {d.yaw !== null ? " ➝" : ""}
                    {planPath?.name === d.name ? ` · ${planPath.length.toFixed(1)} m` : ""}
                  </span>
                  <button
                    onClick={() => void previewPlan(d)}
                    disabled={busy !== null}
                    className="rounded px-2 py-1 text-[12px] font-bold text-[#2f6fdb] hover:bg-[#eef3fc] disabled:opacity-40"
                  >
                    Plan
                  </button>
                  <button
                    onClick={() => void gotoDest(d)}
                    disabled={busy !== null}
                    className="rounded bg-[#009b77] px-3 py-1 text-[12px] font-bold text-white disabled:opacity-40"
                  >
                    {busy === `go:${d.name}` ? "…" : "Go"}
                  </button>
                  <button
                    onClick={() => void deleteDest(d)}
                    className="rounded px-2 py-1 text-[12px] font-semibold text-[#b42020] hover:bg-[#fdecec]"
                    title="Delete"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
            {placingHome && placeFor === "dest" ? (
              <div className="mt-3 space-y-2">
                <p className="text-[12px] text-[#657078]">
                  Click the spot on the map. To make G1 face something on arrival (e.g. a machine), tick the box
                  and drag towards it.
                </p>
                <label className="flex items-center gap-2 text-[12px] font-semibold text-[#36414b]">
                  <input type="checkbox" checked={destFace} onChange={(e) => setDestFace(e.target.checked)} />
                  Face this direction on arrival (G1 walks the last 0.8 m straight that way)
                </label>
                <input
                  value={destTitle.en}
                  onChange={(e) => setDestTitle({ ...destTitle, en: e.target.value })}
                  placeholder="Name (English), e.g. Coffee machine"
                  className="w-full rounded border border-[#c6ccd1] px-3 py-2 text-[13px]"
                />
                <input
                  value={destTitle.de}
                  onChange={(e) => setDestTitle({ ...destTitle, de: e.target.value })}
                  placeholder="Name (Deutsch), z. B. Kaffeemaschine"
                  className="w-full rounded border border-[#c6ccd1] px-3 py-2 text-[13px]"
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => void saveHome()}
                    disabled={!draftHome || !destTitle.en.trim()}
                    className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white disabled:opacity-40"
                  >
                    Save destination
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
              </div>
            ) : (
              <button
                onClick={() => {
                  setPlaceFor("dest");
                  setPlacingHome(true);
                  setDraftHome(null);
                }}
                className="mt-3 rounded border border-[#c6ccd1] px-4 py-2 text-[13px] font-bold text-[#36414b] hover:border-[#009b77]"
              >
                + Add destination
              </button>
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
