"""Dashboard API: everything at a glance + alerts."""
from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.api.websocket import manager
from app.services import host_stats, robot_hub, runs_service
from app.services.robot_hub import HubError

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def build_alerts(robot: dict, services: list, tel: dict | None, host: dict) -> list[dict]:
    alerts = []

    def add(level, text):
        alerts.append({"level": level, "text": text})

    if robot.get("estop"):
        add("critical", "Software E-stop is active – reset it in the G1 Remote app.")
    b = (tel or {}).get("battery") or {}
    soc = b.get("soc")
    if soc is not None:
        if soc < 20:
            add("critical", f"Battery {soc:.0f} % – charge G1 now.")
        elif soc < 35:
            add("warning", f"Battery {soc:.0f} % – plan charging soon.")
    elif tel is not None:
        add("info", "No battery data from G1 yet.")
    body = (tel or {}).get("body") or {}
    th = (tel or {}).get("thresholds") or {"motor_warn_c": 60, "motor_hot_c": 75}
    hot = [m for m in body.get("motors", []) if m.get("temp_c") is not None and m["temp_c"] >= th["motor_warn_c"]]
    if hot:
        worst = max(hot, key=lambda m: m["temp_c"])
        level = "critical" if worst["temp_c"] >= th["motor_hot_c"] else "warning"
        add(level, f"Motor hot: {worst['joint']} {worst['temp_c']:.0f} °C"
                   + (f" (+{len(hot) - 1} more)" if len(hot) > 1 else "") + " – let G1 rest.")
    for key in ("imu_roll_deg", "imu_pitch_deg"):
        v = body.get(key)
        if v is not None and abs(v) > 25:
            add("critical", "G1 is strongly tilted – has it fallen?")
            break
    for s in services:
        if s.get("required") and not s.get("ok"):
            add("warning", f"{s['name']} is down ({s['detail']}).")
    if (host.get("temp_max_c") or 0) > 85:
        add("warning", f"Robot PC is hot ({host['temp_max_c']:.0f} °C).")
    if (host.get("disk") or {}).get("used_percent", 0) > 90:
        add("warning", "Robot PC disk almost full.")
    sig = (host.get("wifi") or {}).get("signal_dbm")
    if sig is not None and sig < -75:
        add("warning", f"Weak Wi-Fi ({sig} dBm) – the tablet may lose connection.")
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda a: order[a["level"]])


def _today(runs: list[dict]) -> dict:
    day = time.strftime("%Y-%m-%d")
    today = [r for r in runs if str(r.get("started", "")).startswith(day) and not r.get("excluded")]
    stats = runs_service.stats(today)
    last = max(runs, key=lambda r: r.get("started", ""), default=None)
    return {"runs": stats["runs"], "done": stats["done"], "success_rate": stats["success_rate"],
            "distance_m": stats["total_distance_m"], "avg_duration_s": stats["avg_duration_s"],
            "last_run": {k: last.get(k) for k in ("started", "route", "result", "duration_s")} if last else None}


def collect() -> dict:
    ov = robot_hub.overview()
    try:
        tel = robot_hub.telemetry()
    except HubError:
        tel = None
    host = host_stats.snapshot()
    runs = runs_service.load_runs()
    return {
        "time": time.time(),
        "robot": ov["robot"], "guide": ov["guide"], "services": ov["services"], "camera": ov["camera"],
        "telemetry": tel, "host": host, "today": _today(runs),
        "alerts": build_alerts(ov["robot"], ov["services"], tel, host),
    }


@router.get("")
async def dashboard():
    data = await run_in_threadpool(collect)
    data["live_connections"] = len(manager.active_connections)
    return data
