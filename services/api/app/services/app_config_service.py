"""
Visitor-app configuration managed in G1 Studio and pushed live to the tablets.

Stored in services/api/data/app_config.json. Every change bumps `version` and is
broadcast over the backend WebSocket (/ws) as {"type": "app_config_changed"};
the G1 Remote app then reloads GET /api/app/config.
"""
from __future__ import annotations

import json
import os
import threading
import time

from app.services.lab_map_service import _DATA

CONFIG_FILE = os.path.expanduser(os.getenv("G1_APP_CONFIG_FILE", os.path.join(_DATA, "app_config.json")))

TILES = {
    "lab_guide": "Lab Guide",
    "demonstrations": "Demonstrations",
    "lab_map": "Lab Map",
    "lab_info": "Lab Info",
    "safety": "Safety Presentation",
    "robot_show": "Robot Show",
}

DEFAULT = {
    "version": 1,
    "updated": "",
    "announcement": {"active": False, "level": "info", "text_en": "", "text_de": ""},
    "tiles": {k: True for k in TILES},
}

_lock = threading.Lock()


def load() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    cfg = json.loads(json.dumps(DEFAULT))
    cfg.update({k: v for k, v in data.items() if k in ("version", "updated")})
    cfg["announcement"].update({k: v for k, v in (data.get("announcement") or {}).items()
                                if k in DEFAULT["announcement"]})
    cfg["tiles"].update({k: bool(v) for k, v in (data.get("tiles") or {}).items() if k in TILES})
    return cfg


def save(change: dict) -> dict:
    with _lock:
        cfg = load()
        ann = change.get("announcement")
        if isinstance(ann, dict):
            for k in ("text_en", "text_de"):
                if k in ann and ann[k] is not None:
                    cfg["announcement"][k] = str(ann[k]).strip()[:300]
            if ann.get("level") in ("info", "warning"):
                cfg["announcement"]["level"] = ann["level"]
            if "active" in ann and ann["active"] is not None:
                cfg["announcement"]["active"] = bool(ann["active"])
        tiles = change.get("tiles")
        if isinstance(tiles, dict):
            for k, v in tiles.items():
                if k in TILES and v is not None:
                    cfg["tiles"][k] = bool(v)
        if not any(cfg["tiles"].values()):
            raise ValueError("At least one home tile must stay visible.")
        cfg["version"] = int(cfg.get("version", 1)) + 1
        cfg["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=1, ensure_ascii=False)
        os.replace(tmp, CONFIG_FILE)
        return cfg
