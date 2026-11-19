"""Jetson (robot PC) health for the dashboard: CPU, temperature, memory, disk, Wi-Fi."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time

WIFI_IF = os.getenv("G1_WIFI_INTERFACE", "wlP1p1s0")
_cpu_prev: tuple[float, float] | None = None
_wifi_cache: tuple[float, dict] | None = None


def _cpu_percent() -> float | None:
    global _cpu_prev
    try:
        with open("/proc/stat") as f:
            parts = [float(x) for x in f.readline().split()[1:]]
    except OSError:
        return None
    idle, total = parts[3] + (parts[4] if len(parts) > 4 else 0), sum(parts)
    prev, _cpu_prev = _cpu_prev, (idle, total)
    if prev is None:
        return None
    d_total, d_idle = total - prev[1], idle - prev[0]
    return round(100.0 * (1 - d_idle / d_total), 1) if d_total > 0 else None


def _temps() -> dict:
    out = {}
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            name = open(os.path.join(zone, "type")).read().strip()
            val = int(open(os.path.join(zone, "temp")).read().strip()) / 1000.0
            if -20 < val < 150:
                out[name] = round(val, 1)
        except (OSError, ValueError):
            continue
    return out


def _memory() -> dict:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0]) * 1024
    except OSError:
        return {}
    total, avail = info.get("MemTotal"), info.get("MemAvailable")
    if not total or avail is None:
        return {}
    return {"total_gb": round(total / 1e9, 1), "used_percent": round(100 * (1 - avail / total), 1)}


def _wifi() -> dict:
    global _wifi_cache
    now = time.monotonic()
    if _wifi_cache and now - _wifi_cache[0] < 10:
        return _wifi_cache[1]
    out: dict = {"interface": WIFI_IF}
    try:
        ip = subprocess.run(["ip", "-4", "-o", "addr", "show", WIFI_IF], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip)
        out["ip"] = m.group(1) if m else None
        link = subprocess.run(["iw", "dev", WIFI_IF, "link"], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"SSID: (.+)", link)
        out["ssid"] = m.group(1).strip() if m else None
        m = re.search(r"signal: (-?\d+)", link)
        out["signal_dbm"] = int(m.group(1)) if m else None
    except Exception as exc:
        out["error"] = str(exc)
    _wifi_cache = (now, out)
    return out


def snapshot() -> dict:
    temps = _temps()
    try:
        du = shutil.disk_usage("/")
        disk = {"total_gb": round(du.total / 1e9), "used_percent": round(100 * du.used / du.total, 1)}
    except OSError:
        disk = {}
    try:
        uptime_s = float(open("/proc/uptime").read().split()[0])
    except (OSError, ValueError):
        uptime_s = None
    try:
        load1 = os.getloadavg()[0]
    except OSError:
        load1 = None
    return {
        "cpu_percent": _cpu_percent(),
        "cpu_count": os.cpu_count(),
        "load1": round(load1, 2) if load1 is not None else None,
        "temp_max_c": max(temps.values()) if temps else None,
        "temps": temps,
        "memory": _memory(),
        "disk": disk,
        "uptime_h": round(uptime_s / 3600, 1) if uptime_s else None,
        "wifi": _wifi(),
    }
