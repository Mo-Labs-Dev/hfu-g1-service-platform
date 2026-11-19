"""
Battery warnings: G1 speaks (EN + DE) and the apps show a warning.

  < 50 %  low       -> "My battery is low, 45 percent."    reminder every 20 min
  < 20 %  critical  -> "Please charge my battery now ..."   reminder every 5 min
Hysteresis (+3 %) so the level does not flicker. Silent while charging.
A "low" announcement waits until a running tour/guide is finished; "critical"
is always spoken. Runs once in the Studio backend, so G1 speaks only once even
with several tablets.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

LOW = float(os.getenv("G1_BATTERY_LOW", "50"))
CRITICAL = float(os.getenv("G1_BATTERY_CRITICAL", "20"))
HYSTERESIS = 3.0
REMIND_LOW_S = 20 * 60
REMIND_CRITICAL_S = 5 * 60
VOICE_LANGS = [x for x in os.getenv("G1_BATTERY_VOICE", "en,de").split(",") if x in ("en", "de")]

TEXT = {
    "low": {"en": "My battery is low, {soc} percent. Please plan to charge me soon.",
            "de": "Mein Akku ist schwach, noch {soc} Prozent. Bitte laden Sie mich bald auf."},
    "critical": {"en": "Please charge my battery now. Only {soc} percent left.",
                 "de": "Bitte laden Sie jetzt meinen Akku. Nur noch {soc} Prozent."},
}


@dataclass
class BatteryWatch:
    clock: callable = time.monotonic
    level: str = "unknown"            # unknown / ok / low / critical
    soc: float | None = None
    charging: bool = False
    updated: float | None = None
    _last_spoken: dict = field(default_factory=dict)
    _pending: str | None = None

    def classify(self, soc: float) -> str:
        cur = self.level
        if soc < CRITICAL or (cur == "critical" and soc < CRITICAL + HYSTERESIS):
            return "critical"
        if soc < LOW or (cur in ("low", "critical") and soc < LOW + HYSTERESIS):
            return "low"
        return "ok"

    def update(self, soc: float | None, charging: bool, guide_active: bool) -> list[tuple]:
        """Returns actions: ("broadcast", level) and/or ("speak", level)."""
        actions: list[tuple] = []
        if soc is None:
            return actions
        now = self.clock()
        new = self.classify(soc)
        changed = new != self.level
        self.soc, self.charging, self.updated = soc, charging, now
        prev, self.level = self.level, new
        if changed:
            actions.append(("broadcast", new))
            if new in ("low", "critical") and (prev in ("ok", "unknown") or new == "critical"):
                self._pending = new
        if new == "ok":
            self._pending = None
            return actions
        if charging:
            self._pending = None                   # nobody needs to be told while charging
            return actions
        last = self._last_spoken.get(new)
        remind = REMIND_CRITICAL_S if new == "critical" else REMIND_LOW_S
        due = self._pending == new or last is None or now - last >= remind
        if due and (new == "critical" or not guide_active):
            actions.append(("speak", new))
            self._last_spoken[new] = now
            self._pending = None
        return actions

    def state(self) -> dict:
        return {"soc": self.soc, "level": self.level, "charging": self.charging,
                "low_threshold": LOW, "critical_threshold": CRITICAL}

    def texts(self, level: str) -> list[tuple[str, str]]:
        soc = int(round(self.soc or 0))
        return [(TEXT[level][lang].format(soc=soc), lang) for lang in VOICE_LANGS]


watch = BatteryWatch()


async def run_forever(period_s: float = 10.0) -> None:
    """Background loop in the Studio backend."""
    from fastapi.concurrency import run_in_threadpool
    from app.api.websocket import manager
    from app.services import content_service, robot_hub

    def read():
        tel = robot_hub.telemetry()
        b = (tel or {}).get("battery") or {}
        if not b.get("fresh"):
            return None, False, False
        try:
            g = robot_hub.get_json(f"{robot_hub.GUIDE}/api/guide/status", timeout=1.5) or {}
            active = g.get("state") not in (None, "idle", "done", "aborted", "cancelled")
        except Exception:
            active = False
        return b.get("soc"), bool(b.get("charging")), active

    while True:
        try:
            soc, charging, guide_active = await run_in_threadpool(read)
            for kind, level in watch.update(soc, charging, guide_active):
                if kind == "broadcast":
                    await manager.broadcast({"type": "battery", "data": watch.state()})
                elif kind == "speak":
                    for text, lang in watch.texts(level):
                        try:
                            await run_in_threadpool(content_service.say_on_g1, text, lang)
                        except Exception as exc:
                            print(f"[battery] could not speak: {exc}")
                    print(f"[battery] {level} {watch.soc} % announced")
        except asyncio.CancelledError:
            raise
        except Exception:
            pass                                   # telemetry not running yet
        await asyncio.sleep(period_s)
