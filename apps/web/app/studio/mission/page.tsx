"use client";

// G1 Studio - Mission Control
// Live robot state, camera (+ AI boxes), tours, all services with start/stop buttons,
// STOP / E-STOP. Replaces the daily terminal commands.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActionInfo,
  ActionStatus,
  GuideRoute,
  Overview,
  apiBase,
  getJson,
  postJson,
} from "@/lib/g1api";
import { usePin } from "@/components/studio/usePin";
import VisionPanel from "@/components/studio/VisionPanel";

type Detection = {
  label: string;
  confidence: number;
  bbox: { x1: number; y1: number; x2: number; y2: number };
};

const GUIDE_LABEL: Record<string, string> = {
  idle: "Ready",
  starting: "Starting",
  guiding: "Walking",
  explaining: "Explaining",
  blocked: "Blocked",
  arrived: "Arrived",
  returning: "Returning home",
  done: "Finished",
  aborted: "Aborted",
  cancelled: "Cancelled",
};

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  const color = ok ? "bg-[#009b77]" : warn ? "bg-[#d79616]" : "bg-[#d62828]";
  return <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${color}`} />;
}

function Card({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-[#d8dde1] bg-white ${className}`}>
      <div className="flex items-center justify-between border-b border-[#e4e8eb] px-5 py-3">
        <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#36414b]">{title}</h2>
        {right}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

export default function MissionControlPage() {
  const { ensurePin, forgetPin, pinDialog } = usePin();

  const [overview, setOverview] = useState<Overview | null>(null);
  const [backendOnline, setBackendOnline] = useState(true);
  const [routes, setRoutes] = useState<GuideRoute[]>([]);
  const [routesError, setRoutesError] = useState("");
  const [selectedRoute, setSelectedRoute] = useState("");
  const [lang, setLang] = useState<"en" | "de">("en");
  const [actions, setActions] = useState<ActionInfo[]>([]);
  const [actionStatus, setActionStatus] = useState<ActionStatus | null>(null);
  const [homeConfirm, setHomeConfirm] = useState<ActionInfo | null>(null);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [cameraTick, setCameraTick] = useState(0);
  const [cameraOk, setCameraOk] = useState(true);
  const [aiBoxes, setAiBoxes] = useState(false);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [imageSize, setImageSize] = useState<{ w: number; h: number }>({ w: 1920, h: 1080 });
  const [estopConfirm, setEstopConfirm] = useState(false);
  const logRef = useRef<HTMLPreElement | null>(null);
  const inFlight = useRef(false);

  const flash = useCallback((text: string, error = false) => {
    setMessage({ text, error });
    setTimeout(() => setMessage(null), 6000);
  }, []);

  // ---------------------------------------------------------- polling
  useEffect(() => {
    let alive = true;
    async function poll() {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const data = await getJson<Overview>("/api/mission/overview", 5000);
        if (alive) {
          setOverview(data);
          setBackendOnline(true);
        }
      } catch {
        if (alive) setBackendOnline(false);
      } finally {
        inFlight.current = false;
      }
    }
    void poll();
    const t = setInterval(poll, 1500);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const loadRoutes = useCallback(async () => {
    try {
      const data = await getJson<GuideRoute[]>("/api/mission/routes");
      setRoutes(data);
      setRoutesError("");
      setSelectedRoute((current) => current || data.find((r) => r.kind === "tour")?.name || data[0]?.name || "");
    } catch (e) {
      setRoutes([]);
      setRoutesError(e instanceof Error ? e.message : "Guide mode not running");
    }
  }, []);

  useEffect(() => {
    void loadRoutes();
    const t = setInterval(loadRoutes, 15000);
    return () => clearInterval(t);
  }, [loadRoutes]);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await getJson<{ actions: ActionInfo[] } & ActionStatus>("/api/mission/actions");
        if (!alive) return;
        setActions(data.actions);
        setActionStatus({ running: data.running, last: data.last, output: data.output });
      } catch {
        /* backend offline - shown elsewhere */
      }
    }
    void load();
    const t = setInterval(load, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [actionStatus?.output?.length]);

  // camera: new snapshot every second
  useEffect(() => {
    const t = setInterval(() => setCameraTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  // AI boxes: YOLO every 3 s while enabled
  useEffect(() => {
    if (!aiBoxes) {
      setDetections([]);
      return;
    }
    let alive = true;
    async function detect() {
      try {
        const res = await getJson<{ image: { width: number; height: number }; detections: Detection[] }>(
          "/api/mission/camera/detect",
          10000,
        );
        if (!alive) return;
        setDetections(res.detections || []);
        if (res.image?.width) setImageSize({ w: res.image.width, h: res.image.height });
      } catch {
        if (alive) setDetections([]);
      }
    }
    void detect();
    const t = setInterval(detect, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [aiBoxes]);

  // ---------------------------------------------------------- actions
  async function stopRobot() {
    try {
      await postJson("/api/mission/stop");
      flash("STOP sent - G1 stands still, guide cancelled.");
    } catch (e) {
      flash(`STOP failed: ${e instanceof Error ? e.message : e}`, true);
    }
  }

  async function estopRobot() {
    setEstopConfirm(false);
    try {
      await postJson("/api/mission/estop");
      flash("E-STOP active. Reset it in the G1 Remote app (operator screen).");
    } catch (e) {
      flash(`E-STOP failed: ${e instanceof Error ? e.message : e}`, true);
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
      flash(text, true);
    }
  }

  async function startTour() {
    if (!selectedRoute) return;
    await withPin(async (pin) => {
      await postJson("/api/mission/guide/start", { pin, route: selectedRoute, lang });
      flash(`Started '${selectedRoute}'. G1 checks HOME for ~3 s, then walks.`);
    });
  }

  async function cancelTour() {
    try {
      await postJson("/api/mission/guide/cancel");
      flash("Guide cancelled.");
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true);
    }
  }

  async function runAction(action: ActionInfo, homeConfirmed = false) {
    if (action.confirm_home && !homeConfirmed) {
      setHomeConfirm(action);
      return;
    }
    setHomeConfirm(null);
    await withPin(async (pin) => {
      const st = await postJson<ActionStatus>(`/api/mission/actions/${action.id}`, {
        pin,
        home_confirmed: homeConfirmed,
      });
      setActionStatus(st);
      flash(`${action.label} started - see the log below.`);
      if (action.id.includes("guide")) setTimeout(loadRoutes, 15000);
    });
  }

  // ---------------------------------------------------------- derived
  const robot = overview?.robot;
  const guide = overview?.guide;
  const guideActive = !!guide && !["idle", "done", "aborted", "cancelled"].includes(guide.state);
  const requiredDown = (overview?.services || []).filter((s) => s.required && !s.ok);
  const progress = Math.round((guide?.progress || 0) * 100);
  const selected = routes.find((r) => r.name === selectedRoute);

  const robotChip = !backendOnline
    ? { text: "Studio backend offline", cls: "bg-[#fdecec] text-[#b42020]" }
    : !robot?.reachable
      ? { text: "Robot not reachable", cls: "bg-[#fdecec] text-[#b42020]" }
      : robot.estop
        ? { text: "E-STOP ACTIVE", cls: "bg-[#d62828] text-white" }
        : robot.walking_mode
          ? { text: "Walking mode · FSM 500", cls: "bg-[#eaf7f2] text-[#00866a]" }
          : { text: `${robot.fsm_name} · FSM ${robot.fsm_id ?? "?"}`, cls: "bg-[#fff6e5] text-[#9a6812]" };

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {pinDialog}

      {/* ---------------- header strip ---------------- */}
      <section className="sticky top-[88px] z-40 border-b border-[#e0e3e1] bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-6 py-4 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[24px] font-bold tracking-[-0.03em] text-[#292f33]">Mission Control</h1>
          </div>

          <span className={`rounded-full px-3 py-1.5 text-[12px] font-bold ${robotChip.cls}`}>{robotChip.text}</span>

          {robot?.reachable && (
            <span className="rounded-full bg-[#f0f2f3] px-3 py-1.5 text-[12px] font-semibold text-[#566373]">
              {robot.teleop_active ? `Joystick: ${robot.operator || "in use"}` : "Joystick locked"}
            </span>
          )}

          {guide && (
            <span
              className={`rounded-full px-3 py-1.5 text-[12px] font-semibold ${
                guide.state === "blocked" || guide.state === "aborted"
                  ? "bg-[#fff6e5] text-[#9a6812]"
                  : guideActive
                    ? "bg-[#eaf7f2] text-[#00866a]"
                    : "bg-[#f0f2f3] text-[#566373]"
              }`}
            >
              Guide: {GUIDE_LABEL[guide.state] || guide.state}
            </span>
          )}

          {requiredDown.length > 0 && backendOnline && (
            <span className="rounded-full bg-[#fdecec] px-3 py-1.5 text-[12px] font-semibold text-[#b42020]">
              {requiredDown.length} service{requiredDown.length > 1 ? "s" : ""} down
            </span>
          )}

          <div className="ml-auto flex gap-3">
            <button
              onClick={() => void stopRobot()}
              className="rounded-md bg-[#d62828] px-7 py-3 text-[15px] font-black tracking-[0.06em] text-white shadow hover:bg-[#b81f1f]"
            >
              ■ STOP
            </button>
            <button
              onClick={() => setEstopConfirm(true)}
              className="rounded-md border-2 border-[#8f1010] bg-[#8f1010] px-5 py-3 text-[13px] font-black tracking-[0.06em] text-white hover:bg-[#6f0b0b]"
            >
              E-STOP
            </button>
          </div>
        </div>
        {message && (
          <div
            className={`border-t px-6 py-2 text-center text-[13px] font-semibold md:px-10 ${
              message.error ? "border-[#f3c6c6] bg-[#fdecec] text-[#b42020]" : "border-[#cfe9df] bg-[#eaf7f2] text-[#00866a]"
            }`}
          >
            {message.text}
          </div>
        )}
      </section>

      <div className="mx-auto grid max-w-[1600px] grid-cols-1 gap-6 px-6 py-6 md:px-10 xl:grid-cols-3">
        {/* ---------------- camera ---------------- */}
        <Card
          title="G1 camera"
          className="xl:col-span-2"
          right={
            <label className="flex cursor-pointer items-center gap-2 text-[12px] font-semibold text-[#566373]">
              <input type="checkbox" checked={aiBoxes} onChange={(e) => setAiBoxes(e.target.checked)} />
              AI detection (YOLO)
            </label>
          }
        >
          <div className="relative aspect-video overflow-hidden rounded-md bg-[#172126]">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${apiBase()}/api/mission/camera/snapshot?t=${cameraTick}`}
              alt="G1 head camera"
              className="h-full w-full object-contain"
              onLoad={() => setCameraOk(true)}
              onError={() => setCameraOk(false)}
            />
            {aiBoxes &&
              detections.map((d, i) => (
                <div
                  key={i}
                  className="pointer-events-none absolute border-2 border-[#00e0a8]"
                  style={{
                    left: `${(d.bbox.x1 / imageSize.w) * 100}%`,
                    top: `${(d.bbox.y1 / imageSize.h) * 100}%`,
                    width: `${((d.bbox.x2 - d.bbox.x1) / imageSize.w) * 100}%`,
                    height: `${((d.bbox.y2 - d.bbox.y1) / imageSize.h) * 100}%`,
                  }}
                >
                  <span className="absolute -top-5 left-0 whitespace-nowrap bg-[#00e0a8] px-1.5 text-[11px] font-bold text-[#0b2a22]">
                    {d.label} {Math.round(d.confidence * 100)}%
                  </span>
                </div>
              ))}
            {!cameraOk && (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                <p className="text-[14px] font-bold text-white">Camera offline</p>
                <p className="mt-1 text-[12px] text-[#9aa6ab]">{overview?.camera?.detail || "no picture"}</p>
                <p className="mt-1 text-[11px] text-[#9aa6ab]">Try “Restart camera bridge” below.</p>
              </div>
            )}
          </div>
          {aiBoxes && (
            <p className="mt-2 text-[12px] text-[#657078]">
              {detections.length
                ? `Detected: ${detections.map((d) => d.label).join(", ")}`
                : "No objects detected (updates every 3 s)."}
            </p>
          )}
        </Card>

        {/* ---------------- robot ---------------- */}
        <Card title="Robot">
          <dl className="grid grid-cols-2 gap-y-3 text-[13px]">
            <dt className="text-[#657078]">Mode</dt>
            <dd className="font-bold text-[#292f33]">
              {robot?.reachable ? `${robot.fsm_name} (FSM ${robot.fsm_id ?? "?"})` : "—"}
            </dd>
            <dt className="text-[#657078]">E-stop</dt>
            <dd className={`font-bold ${robot?.estop ? "text-[#d62828]" : "text-[#292f33]"}`}>
              {robot?.estop ? `ACTIVE ${robot.estop_reason ? `(${robot.estop_reason})` : ""}` : "off"}
            </dd>
            <dt className="text-[#657078]">Control</dt>
            <dd className="font-bold text-[#292f33]">
              {robot?.teleop_active ? robot.operator || "joystick" : "nobody (locked)"}
            </dd>
            <dt className="text-[#657078]">Gesture</dt>
            <dd className="font-bold text-[#292f33]">{robot?.gesture || "—"}</dd>
            <dt className="text-[#657078]">Stops so far</dt>
            <dd className="font-bold text-[#292f33]">{robot?.stop_count ?? "—"}</dd>
          </dl>
          {robot?.reachable && !robot.walking_mode && (
            <p className="mt-4 rounded bg-[#fff6e5] p-3 text-[12px] text-[#9a6812]">
              Guide, tours and Robot Show need walking mode. In the G1 Remote app: unlock → Damp → Stand up →
              Walking mode.
            </p>
          )}
        </Card>

        {/* ---------------- guide / tours ---------------- */}
        <Card
          title="Guide & tours"
          className="xl:col-span-2"
          right={
            <button onClick={() => void loadRoutes()} className="text-[12px] font-semibold text-[#00866a] hover:underline">
              Reload routes
            </button>
          }
        >
          {routesError ? (
            <p className="rounded bg-[#f0f2f3] p-3 text-[13px] text-[#566373]">
              {routesError}. Use <b>Start guide mode</b> below (G1 on HOME, walking mode).
            </p>
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col text-[12px] font-semibold text-[#566373]">
                Route / tour
                <select
                  value={selectedRoute}
                  onChange={(e) => setSelectedRoute(e.target.value)}
                  className="mt-1 min-w-[260px] rounded border border-[#c6ccd1] bg-white px-3 py-2 text-[14px] text-[#292f33]"
                >
                  {routes.map((r) => (
                    <option key={r.name} value={r.name}>
                      {r.kind === "tour" ? "Tour: " : "Route: "}
                      {r.title_en || r.name} · {r.length_m} m{r.stops?.length ? ` · ${r.stops.length} stops` : ""}
                      {r.home_scan === false ? " · no HOME scan" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex overflow-hidden rounded border border-[#c6ccd1]">
                {(["en", "de"] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => setLang(l)}
                    className={`px-4 py-2 text-[13px] font-bold ${lang === l ? "bg-[#009b77] text-white" : "bg-white text-[#566373]"}`}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
              <button
                onClick={() => void startTour()}
                disabled={!selectedRoute || guideActive}
                className="rounded bg-[#009b77] px-5 py-2 text-[14px] font-bold text-white disabled:opacity-40"
              >
                ▶ Start
              </button>
              <button
                onClick={() => void cancelTour()}
                disabled={!guideActive}
                className="rounded border border-[#c6ccd1] px-5 py-2 text-[14px] font-bold text-[#36414b] disabled:opacity-40"
              >
                Cancel
              </button>
              {selected?.home_scan === false && (
                <span className="text-[12px] text-[#9a6812]">
                  This route has no HOME scan – re-record it for automatic HOME correction.
                </span>
              )}
            </div>
          )}

          {guide && (
            <div className="mt-5">
              <div className="flex items-baseline justify-between">
                <p className="text-[16px] font-bold text-[#292f33]">
                  {GUIDE_LABEL[guide.state] || guide.state}
                  {guide.route ? ` · ${guide.route}` : ""}
                  {guide.kind === "tour" && guide.stop_count ? ` · stop ${guide.stop_index}/${guide.stop_count}` : ""}
                  {guide.stop_title ? ` · ${guide.stop_title}` : ""}
                </p>
                <span className="text-[13px] font-bold text-[#00866a]">{progress}%</span>
              </div>
              <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-[#e4e8eb]">
                <div className="h-full bg-[#009b77] transition-all" style={{ width: `${progress}%` }} />
              </div>
              {guide.message && <p className="mt-2 text-[13px] text-[#566373]">{guide.message}</p>}
              {guide.alignment?.used && (
                <p className="mt-2 text-[12px] text-[#657078]">
                  HOME correction: {((guide.alignment.dx ?? 0) * 100).toFixed(0)} cm /{" "}
                  {((guide.alignment.dy ?? 0) * 100).toFixed(0)} cm / {guide.alignment.dyaw_deg?.toFixed(1)}° · match{" "}
                  {Math.round((guide.alignment.fit ?? 0) * 100)}%
                </p>
              )}
            </div>
          )}
          <p className="mt-4 text-[12px] text-[#87919c]">
            Before starting: G1 in walking mode on HOME (roughly), joystick locked in the app, path clear.
          </p>
        </Card>

        {/* ---------------- services ---------------- */}
        <Card title="Services">
          <ul className="space-y-2.5">
            {(overview?.services || []).map((s) => (
              <li key={s.id} className="flex items-start gap-3">
                <span className="mt-1">
                  <Dot ok={s.ok} warn={!s.required} />
                </span>
                <div className="min-w-0">
                  <p className="text-[13px] font-semibold text-[#292f33]">
                    {s.name} <span className="font-normal text-[#87919c]">:{s.port}</span>
                  </p>
                  <p className="truncate text-[11px] text-[#657078]" title={s.detail}>
                    {s.detail}
                  </p>
                </div>
              </li>
            ))}
            {!overview && <li className="text-[13px] text-[#657078]">Loading…</li>}
          </ul>
        </Card>

        {/* ---------------- G1 vision ---------------- */}
        <Card title="G1 Vision" className="xl:col-span-3">
          <VisionPanel withPin={withPin} lang={lang} />
        </Card>

        {/* ---------------- system actions ---------------- */}
        <Card
          title="System control"
          className="xl:col-span-3"
          right={
            actionStatus?.running ? (
              <span className="text-[12px] font-bold text-[#9a6812]">Running: {actionStatus.running}</span>
            ) : actionStatus?.last?.label ? (
              <span className={`text-[12px] font-bold ${actionStatus.last.ok ? "text-[#00866a]" : "text-[#d62828]"}`}>
                Last: {actionStatus.last.label} {actionStatus.last.ok ? "✔" : "✘"} ({actionStatus.last.finished})
              </span>
            ) : null
          }
        >
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {actions.map((a) => (
              <button
                key={a.id}
                onClick={() => void runAction(a)}
                disabled={!!actionStatus?.running}
                className="flex flex-col items-start rounded-md border border-[#d8dde1] bg-[#fafbfb] p-3 text-left hover:border-[#009b77] hover:bg-[#eaf7f2] disabled:opacity-40"
              >
                <span className="text-[13px] font-bold text-[#292f33]">{a.label}</span>
                <span className="mt-1 text-[11px] leading-[15px] text-[#657078]">{a.description}</span>
              </button>
            ))}
          </div>
          <pre
            ref={logRef}
            className="mt-4 h-[220px] overflow-auto rounded-md bg-[#172126] p-4 text-[11px] leading-[16px] text-[#cfe9df]"
          >
            {(actionStatus?.output || []).join("\n") || "Output of the actions appears here."}
          </pre>
        </Card>
      </div>

      {/* ---------------- dialogs ---------------- */}
      {homeConfirm && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/40">
          <div className="w-[420px] rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-[18px] font-bold text-[#292f33]">{homeConfirm.label}</h2>
            <p className="mt-3 text-[14px] text-[#36414b]">
              FAST-LIO uses G1’s current position as HOME. Is G1 <b>standing on the HOME tape</b>, facing the marked
              direction, in <b>walking mode</b>, and standing still?
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setHomeConfirm(null)}
                className="rounded px-4 py-2 text-[13px] font-semibold text-[#566373] hover:bg-[#f0f2f3]"
              >
                No, not yet
              </button>
              <button
                onClick={() => void runAction(homeConfirm, true)}
                className="rounded bg-[#009b77] px-4 py-2 text-[13px] font-bold text-white"
              >
                Yes, G1 is on HOME
              </button>
            </div>
          </div>
        </div>
      )}

      {estopConfirm && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/40">
          <div className="w-[420px] rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-[18px] font-bold text-[#8f1010]">Software E-STOP</h2>
            <p className="mt-3 text-[14px] text-[#36414b]">
              Stops G1 and blocks all motion until an operator resets it in the G1 Remote app. For a normal stop use
              the red STOP button.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setEstopConfirm(false)}
                className="rounded px-4 py-2 text-[13px] font-semibold text-[#566373] hover:bg-[#f0f2f3]"
              >
                Cancel
              </button>
              <button onClick={() => void estopRobot()} className="rounded bg-[#8f1010] px-4 py-2 text-[13px] font-bold text-white">
                E-STOP now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
