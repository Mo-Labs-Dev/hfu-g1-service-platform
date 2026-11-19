"use client";

// G1 Studio - Dashboard
// Everything at a glance: battery, robot state, motor temperatures, today's tours,
// robot PC health, network, services and alerts. Updates every 2 seconds.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { apiBase, getJson, GuideStatus, ServiceHealth } from "@/lib/g1api";

type Motor = { joint: string; temp_c: number | null; voltage_v: number | null };
type Telemetry = {
  battery: {
    soc?: number | null;
    voltage_v?: number | null;
    current_a?: number | null;
    charging?: boolean;
    temperature_max_c?: number | null;
    cycles?: number | null;
    minutes_left?: number | null;
    fresh: boolean;
    age_s: number | null;
  };
  body: {
    motors?: Motor[];
    motor_groups_max_c?: Record<string, number | null>;
    motor_max_c?: number | null;
    imu_roll_deg?: number | null;
    imu_pitch_deg?: number | null;
    fresh: boolean;
  };
  history: [number, number, number | null][];
  thresholds: { motor_warn_c: number; motor_hot_c: number };
};
type Dashboard = {
  time: number;
  robot: {
    reachable: boolean;
    fsm_id: number | null;
    fsm_name: string;
    walking_mode: boolean;
    estop: boolean | null;
    teleop_active: boolean | null;
    operator: string | null;
  };
  guide: GuideStatus | null;
  services: ServiceHealth[];
  camera: { ok: boolean; detail: string };
  telemetry: Telemetry | null;
  host: {
    cpu_percent: number | null;
    cpu_count: number | null;
    temp_max_c: number | null;
    memory: { total_gb?: number; used_percent?: number };
    disk: { total_gb?: number; used_percent?: number };
    uptime_h: number | null;
    wifi: { ip?: string | null; ssid?: string | null; signal_dbm?: number | null };
  };
  today: {
    runs: number;
    done: number;
    success_rate: number | null;
    distance_m: number;
    avg_duration_s: number | null;
    last_run: { started: string; route: string; result: string; duration_s: number } | null;
  };
  alerts: { level: "critical" | "warning" | "info"; text: string }[];
  live_connections: number;
};

const ALERT_STYLE = {
  critical: "border-[#f3c6c6] bg-[#fdecec] text-[#b42020]",
  warning: "border-[#f3dfb5] bg-[#fff6e5] text-[#8a5c0c]",
  info: "border-[#d8dde1] bg-[#f4f6f7] text-[#566373]",
};

function Panel({ title, children, right, className = "" }: { title: string; children: React.ReactNode; right?: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-[#d8dde1] bg-white ${className}`}>
      <div className="flex items-center justify-between border-b border-[#e4e8eb] px-5 py-3">
        <h2 className="text-[12px] font-bold uppercase tracking-[0.08em] text-[#36414b]">{title}</h2>
        {right}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Row({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "bad" | "warn" | "good" }) {
  const color = tone === "bad" ? "text-[#d62828]" : tone === "warn" ? "text-[#b7790f]" : tone === "good" ? "text-[#00866a]" : "text-[#292f33]";
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-[13px]">
      <span className="text-[#657078]">{label}</span>
      <span className={`text-right font-bold ${color}`}>{value}</span>
    </div>
  );
}

function Bar({ value, max = 100, color }: { value: number | null | undefined; max?: number; color: string }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-2 overflow-hidden rounded-full bg-[#e9edef]">
      <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

function batteryColor(soc: number | null | undefined) {
  if (soc == null) return "#aab3ba";
  if (soc < 20) return "#d62828";
  if (soc < 35) return "#d79616";
  return "#009b77";
}

function tempColor(t: number | null | undefined, warn: number, hot: number) {
  if (t == null) return "#aab3ba";
  if (t >= hot) return "#d62828";
  if (t >= warn) return "#d79616";
  return "#009b77";
}

function BatteryRing({ soc, charging }: { soc: number | null | undefined; charging?: boolean }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const v = soc ?? 0;
  return (
    <svg viewBox="0 0 130 130" className="h-[130px] w-[130px]">
      <circle cx="65" cy="65" r={r} fill="none" stroke="#e9edef" strokeWidth="12" />
      <circle
        cx="65"
        cy="65"
        r={r}
        fill="none"
        stroke={batteryColor(soc)}
        strokeWidth="12"
        strokeLinecap="round"
        strokeDasharray={`${(v / 100) * c} ${c}`}
        transform="rotate(-90 65 65)"
      />
      <text x="65" y="66" textAnchor="middle" fontSize="28" fontWeight="700" fill="#292f33">
        {soc == null ? "—" : `${Math.round(soc)}%`}
      </text>
      <text x="65" y="86" textAnchor="middle" fontSize="11" fill="#657078">
        {soc == null ? "no data" : charging ? "charging" : "battery"}
      </text>
    </svg>
  );
}

function Sparkline({ points }: { points: [number, number, number | null][] }) {
  if (points.length < 2) return <p className="text-[11px] text-[#87919c]">History builds up (one point every 30 s).</p>;
  const t0 = points[0][0];
  const t1 = points[points.length - 1][0];
  const w = 260;
  const h = 50;
  const xs = (t: number) => ((t - t0) / Math.max(1, t1 - t0)) * w;
  const ys = (s: number) => h - (s / 100) * h;
  const d = points.map((p, i) => `${i ? "L" : "M"}${xs(p[0]).toFixed(1)},${ys(p[1]).toFixed(1)}`).join(" ");
  const hours = ((t1 - t0) / 3600).toFixed(1);
  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="h-[50px] w-full" preserveAspectRatio="none">
        <line x1="0" x2={w} y1={ys(20)} y2={ys(20)} stroke="#f3c6c6" strokeDasharray="3 3" />
        <path d={d} fill="none" stroke="#009b77" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="mt-1 text-[10px] text-[#87919c]">Last {hours} h · dashed line = 20 %</p>
    </div>
  );
}

function fmtDur(s: number | null | undefined) {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  return m ? `${m} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [online, setOnline] = useState(true);
  const [tick, setTick] = useState(0);
  const busy = useRef(false);

  useEffect(() => {
    let alive = true;
    async function poll() {
      if (busy.current) return;
      busy.current = true;
      try {
        const d = await getJson<Dashboard>("/api/dashboard", 6000);
        if (alive) {
          setData(d);
          setOnline(true);
        }
      } catch {
        if (alive) setOnline(false);
      } finally {
        busy.current = false;
      }
    }
    void poll();
    const t = setInterval(poll, 2000);
    const c = setInterval(() => setTick((n) => n + 1), 3000);
    return () => {
      alive = false;
      clearInterval(t);
      clearInterval(c);
    };
  }, []);

  const tel = data?.telemetry;
  const bat = tel?.battery;
  const body = tel?.body;
  const th = tel?.thresholds || { motor_warn_c: 60, motor_hot_c: 75 };
  const robot = data?.robot;
  const guide = data?.guide;
  const hottest = [...(body?.motors || [])].filter((m) => m.temp_c != null).sort((a, b) => (b.temp_c ?? 0) - (a.temp_c ?? 0)).slice(0, 5);
  const servicesOk = (data?.services || []).filter((s) => s.ok).length;
  const guideActive = !!guide && !["idle", "done", "aborted", "cancelled"].includes(guide.state);
  const wifi = data?.host.wifi;

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-6 py-5 md:px-10">
          <div>
            <div className="h-[3px] w-10 bg-[#009b77]" />
            <h1 className="mt-2 text-[26px] font-bold tracking-[-0.03em] text-[#292f33]">Dashboard</h1>
          </div>
          <p className="text-[13px] text-[#657078]">Unitree G1 · HFU IPSE lab · live</p>
          <div className="ml-auto flex flex-wrap gap-2 text-[13px] font-semibold">
            {[
              ["Mission Control", "/studio/mission"],
              ["Lab Map", "/studio/lab-map"],
              ["Simulation", "/studio/simulation"],
              ["Evaluation", "/studio/evaluation"],
              ["Visitor App", "/studio/app"],
            ].map(([label, href]) => (
              <Link key={href} href={href} className="rounded border border-[#d8dde1] px-3 py-1.5 text-[#36414b] hover:border-[#009b77] hover:text-[#00866a]">
                {label} →
              </Link>
            ))}
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-[1600px] space-y-6 px-6 py-6 md:px-10">
        {!online && (
          <p className="rounded border border-[#f3c6c6] bg-[#fdecec] p-3 text-[13px] font-semibold text-[#b42020]">
            Studio backend not reachable (port 8000). Start it with g1_start_all.sh on the robot PC.
          </p>
        )}

        {/* alerts */}
        {data && (
          <div className="space-y-2">
            {data.alerts.length === 0 ? (
              <p className="rounded border border-[#cfe9df] bg-[#eaf7f2] px-4 py-2.5 text-[13px] font-semibold text-[#00866a]">
                ✔ All good – no alerts.
              </p>
            ) : (
              data.alerts.map((a, i) => (
                <p key={i} className={`rounded border px-4 py-2.5 text-[13px] font-semibold ${ALERT_STYLE[a.level]}`}>
                  {a.level === "critical" ? "⛔ " : a.level === "warning" ? "⚠ " : "ℹ "}
                  {a.text}
                </p>
              ))
            )}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
          {/* battery */}
          <Panel title="Battery" right={bat && !bat.fresh ? <span className="text-[11px] font-semibold text-[#b7790f]">no live data</span> : null}>
            <div className="flex items-center gap-4">
              <BatteryRing soc={bat?.soc} charging={bat?.charging} />
              <div className="min-w-0 flex-1">
                <Row label="Voltage" value={bat?.voltage_v != null ? `${bat.voltage_v} V` : "—"} />
                <Row
                  label="Current"
                  value={bat?.current_a != null ? `${bat.current_a > 0 ? "+" : ""}${bat.current_a} A` : "—"}
                  tone={bat?.charging ? "good" : undefined}
                />
                <Row label="Time left" value={bat?.minutes_left != null ? `~${Math.floor(bat.minutes_left / 60)} h ${bat.minutes_left % 60} min` : "—"} />
                <Row label="Temperature" value={bat?.temperature_max_c != null ? `${bat.temperature_max_c} °C` : "—"} />
                <Row label="Cycles" value={bat?.cycles ?? "—"} />
              </div>
            </div>
            <div className="mt-3">
              <Sparkline points={tel?.history || []} />
            </div>
          </Panel>

          {/* robot */}
          <Panel title="Robot">
            <Row
              label="Mode"
              value={robot?.reachable ? `${robot.fsm_name} (FSM ${robot.fsm_id ?? "?"})` : "not reachable"}
              tone={!robot?.reachable ? "bad" : robot.walking_mode ? "good" : "warn"}
            />
            <Row label="E-stop" value={robot?.estop ? "ACTIVE" : "off"} tone={robot?.estop ? "bad" : undefined} />
            <Row label="Control" value={robot?.teleop_active ? robot.operator || "joystick" : "free (locked)"} />
            <Row label="Tilt (roll / pitch)" value={body?.imu_roll_deg != null ? `${body.imu_roll_deg}° / ${body.imu_pitch_deg}°` : "—"} />
            <Row label="Hottest motor" value={body?.motor_max_c != null ? `${body.motor_max_c} °C` : "—"} tone={(body?.motor_max_c ?? 0) >= th.motor_warn_c ? "warn" : undefined} />
            <div className="mt-3 rounded-md bg-[#f4f6f7] p-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">Guide</p>
              <p className="mt-1 text-[14px] font-bold text-[#292f33]">
                {guide ? (guideActive ? `${guide.state} · ${guide.route}` : "ready") : "guide mode off"}
              </p>
              {guideActive && (
                <div className="mt-2">
                  <Bar value={(guide?.progress || 0) * 100} color="#009b77" />
                </div>
              )}
            </div>
          </Panel>

          {/* today */}
          <Panel title="Today">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[30px] font-bold leading-none text-[#292f33]">{data?.today.runs ?? "—"}</p>
                <p className="mt-1 text-[11px] text-[#657078]">tours / guides</p>
              </div>
              <div>
                <p className="text-[30px] font-bold leading-none text-[#292f33]">
                  {data?.today.success_rate != null ? `${Math.round(data.today.success_rate * 100)}%` : "—"}
                </p>
                <p className="mt-1 text-[11px] text-[#657078]">success</p>
              </div>
              <div>
                <p className="text-[22px] font-bold leading-none text-[#292f33]">{data ? `${data.today.distance_m} m` : "—"}</p>
                <p className="mt-1 text-[11px] text-[#657078]">walked autonomously</p>
              </div>
              <div>
                <p className="text-[22px] font-bold leading-none text-[#292f33]">{fmtDur(data?.today.avg_duration_s)}</p>
                <p className="mt-1 text-[11px] text-[#657078]">avg duration</p>
              </div>
            </div>
            {data?.today.last_run && (
              <p className="mt-4 border-t border-[#eef0f2] pt-3 text-[12px] text-[#566373]">
                Last run: <b>{data.today.last_run.route}</b> · {data.today.last_run.result} ·{" "}
                {data.today.last_run.started.replace("T", " ").slice(5, 16)}
              </p>
            )}
          </Panel>

          {/* camera */}
          <Panel title="Camera" right={<Link href="/studio/mission" className="text-[11px] font-semibold text-[#00866a]">open →</Link>}>
            <div className="relative aspect-video overflow-hidden rounded-md bg-[#172126]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`${apiBase()}/api/mission/camera/snapshot?t=${tick}`}
                alt="G1 camera"
                className="h-full w-full object-contain"
                onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0")}
                onLoad={(e) => ((e.target as HTMLImageElement).style.opacity = "1")}
              />
              {!data?.camera.ok && (
                <span className="absolute inset-0 flex items-center justify-center text-[12px] font-semibold text-[#9aa6ab]">
                  {data?.camera.detail || "camera offline"}
                </span>
              )}
            </div>
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
          {/* motors */}
          <Panel title="Motor temperatures" className="xl:col-span-2" right={<span className="text-[11px] text-[#87919c]">warn {th.motor_warn_c} °C · hot {th.motor_hot_c} °C</span>}>
            {body?.motor_groups_max_c ? (
              <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                <div className="space-y-3">
                  {Object.entries(body.motor_groups_max_c).map(([g, t]) => (
                    <div key={g}>
                      <div className="flex justify-between text-[12px]">
                        <span className="font-semibold text-[#36414b]">{g}</span>
                        <span className="font-bold" style={{ color: tempColor(t, th.motor_warn_c, th.motor_hot_c) }}>
                          {t != null ? `${t} °C` : "—"}
                        </span>
                      </div>
                      <div className="mt-1">
                        <Bar value={t} max={th.motor_hot_c + 10} color={tempColor(t, th.motor_warn_c, th.motor_hot_c)} />
                      </div>
                    </div>
                  ))}
                </div>
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[#657078]">Hottest joints</p>
                  <ul className="mt-2 space-y-1.5">
                    {hottest.map((m) => (
                      <li key={m.joint} className="flex justify-between text-[13px]">
                        <span className="text-[#36414b]">{m.joint}</span>
                        <span className="font-bold" style={{ color: tempColor(m.temp_c, th.motor_warn_c, th.motor_hot_c) }}>
                          {m.temp_c} °C
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <p className="text-[13px] text-[#657078]">No motor data yet – the telemetry service starts with g1_start_all.sh.</p>
            )}
          </Panel>

          {/* robot pc */}
          <Panel title="Robot PC (Jetson)">
            <div className="space-y-3">
              <div>
                <Row label="CPU" value={data?.host.cpu_percent != null ? `${data.host.cpu_percent} %` : "—"} />
                <Bar value={data?.host.cpu_percent} color="#2f6fdb" />
              </div>
              <div>
                <Row label="Memory" value={data?.host.memory.used_percent != null ? `${data.host.memory.used_percent} % of ${data.host.memory.total_gb} GB` : "—"} />
                <Bar value={data?.host.memory.used_percent} color="#2f6fdb" />
              </div>
              <div>
                <Row label="Disk" value={data?.host.disk.used_percent != null ? `${data.host.disk.used_percent} % of ${data.host.disk.total_gb} GB` : "—"} />
                <Bar value={data?.host.disk.used_percent} color={(data?.host.disk.used_percent ?? 0) > 90 ? "#d62828" : "#2f6fdb"} />
              </div>
              <Row label="Temperature" value={data?.host.temp_max_c != null ? `${data.host.temp_max_c} °C` : "—"} tone={(data?.host.temp_max_c ?? 0) > 85 ? "warn" : undefined} />
              <Row label="Uptime" value={data?.host.uptime_h != null ? `${data.host.uptime_h} h` : "—"} />
            </div>
          </Panel>

          {/* network + services */}
          <Panel title="Network & services" right={<span className="text-[11px] font-bold text-[#00866a]">{servicesOk}/{data?.services.length ?? 0} up</span>}>
            <Row label="Wi-Fi" value={wifi?.ssid || "—"} />
            <Row label="Robot IP" value={wifi?.ip || "—"} />
            <Row
              label="Signal"
              value={wifi?.signal_dbm != null ? `${wifi.signal_dbm} dBm` : "—"}
              tone={wifi?.signal_dbm != null ? (wifi.signal_dbm < -75 ? "bad" : wifi.signal_dbm < -65 ? "warn" : "good") : undefined}
            />
            <Row label="Live app connections" value={data?.live_connections ?? "—"} />
            <ul className="mt-3 space-y-1.5 border-t border-[#eef0f2] pt-3">
              {(data?.services || []).map((s) => (
                <li key={s.id} className="flex items-center gap-2 text-[12px]" title={s.detail}>
                  <span className={`h-2 w-2 shrink-0 rounded-full ${s.ok ? "bg-[#009b77]" : s.required ? "bg-[#d62828]" : "bg-[#d79616]"}`} />
                  <span className="truncate text-[#36414b]">{s.name}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
