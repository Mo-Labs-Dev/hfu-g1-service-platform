"""
Destinations for autonomous walking: named points on the Session 03 map
("Coffee machine", "Yaskawa robot", ...). Placed in G1 Studio by clicking the map -
no walking or teaching needed. G1 plans its own way there.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
FILE = os.path.expanduser(os.getenv("G1_DESTINATIONS_FILE", os.path.join(_DATA, "destinations.json")))
TEXT_FIELDS = ("title_en", "title_de", "arrival_en", "arrival_de")
MAX_TEXT = 400

_lock = threading.Lock()


def _load(path: str | None = None) -> list[dict]:
    try:
        with open(path or FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict], path: str | None = None) -> None:
    path = path or FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s[:40] or "destination"


def list_all(path: str | None = None) -> list[dict]:
    return _load(path)


def get(name: str, path: str | None = None) -> dict:
    for d in _load(path):
        if d["name"] == name:
            return d
    raise KeyError(name)


def upsert(body: dict, path: str | None = None) -> dict:
    title = str(body.get("title_en") or body.get("name") or "").strip()
    if not title:
        raise ValueError("A title is needed.")
    try:
        x, y = float(body["x"]), float(body["y"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("x and y are needed.")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("Invalid position.")
    yaw = body.get("yaw")
    item = {"name": slug(body.get("name") or title), "x": round(x, 3), "y": round(y, 3),
            "yaw": None if yaw is None else round(float(yaw), 4)}
    for k in TEXT_FIELDS:
        item[k] = str(body.get(k) or "").strip()[:MAX_TEXT]
    if not item["title_de"]:
        item["title_de"] = item["title_en"] or title
    if not item["title_en"]:
        item["title_en"] = title
    with _lock:
        items = _load(path)
        old = next((d for d in items if d["name"] == item["name"]), None)
        item["created"] = (old or {}).get("created") or time.strftime("%Y-%m-%d %H:%M:%S")
        items = [d for d in items if d["name"] != item["name"]] + [item]
        items.sort(key=lambda d: d["title_en"].lower())
        _save(items, path)
    return item


def delete(name: str, path: str | None = None) -> None:
    with _lock:
        items = _load(path)
        keep = [d for d in items if d["name"] != name]
        if len(keep) == len(items):
            raise KeyError(name)
        _save(keep, path)
