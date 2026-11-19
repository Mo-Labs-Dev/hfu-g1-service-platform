import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fake_server(routes):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, obj, code=200):
            b = json.dumps(obj).encode(); self.send_response(code)
            self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            r = routes.get(("GET", self.path)); self._send(*r) if r else self._send({"detail": "nf"}, 404)
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n)
            routes.setdefault("posts", []).append(self.path)
            r = routes.get(("POST", self.path)); self._send(*r) if r else self._send({"detail": "nf"}, 404)
    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


def test_overview_and_stop(monkeypatch):
    routes = {("GET", "/api/teleop/status"): ({"fsm_id": 500, "estop": False, "teleop_active": False,
                                               "operator": None, "stop_count": 3},),
              ("GET", "/api/guide/status"): ({"state": "idle"},),
              ("POST", "/api/teleop/stop"): ({"ok": True},),
              ("POST", "/api/guide/cancel"): ({"state": "cancelled"},)}
    srv, url = fake_server(routes)
    from app.services import robot_hub as hub
    monkeypatch.setattr(hub, "TELEOP", url); monkeypatch.setattr(hub, "GUIDE", url)
    monkeypatch.setattr(hub, "SERVICES", [
        ("teleop", "Teleop", 8001, f"{url}/api/teleop/status", hub._teleop, True),
        ("guide", "Guide", 8002, f"{url}/api/guide/status", hub._guide, False),
        ("camera", "Camera", 8770, "http://127.0.0.1:9/status", hub._camera, True)])
    o = hub.overview()
    assert o["robot"]["fsm_name"] == "Walking" and o["robot"]["walking_mode"]
    cam = [s for s in o["services"] if s["id"] == "camera"][0]
    assert not cam["ok"] and "not reachable" in cam["detail"]
    hub.stop()
    assert "/api/teleop/stop" in routes["posts"] and "/api/guide/cancel" in routes["posts"]
    srv.shutdown()


def test_actions_need_pin_and_home(tmp_path, monkeypatch):
    from app.services import system_control as sc
    (tmp_path / "pin").write_text("9464\n")
    daily = tmp_path / "daily"; daily.mkdir()
    for n in ("g1_start_all.sh", "g1_start_guide.sh", "g1_stop_guide.sh"):
        (daily / n).write_text(f'echo "{n} $@ home=$G1_ASSUME_HOME"\n')
    monkeypatch.setattr(sc, "PIN_FILE", str(tmp_path / "pin"))
    acts = {k: (v[0], v[1], v[2], [[c[0], str(daily / Path(c[1]).name), *c[2:]] if c[0] == "bash" else c
                                   for c in v[3]]) for k, v in sc.ACTIONS.items()}
    monkeypatch.setattr(sc, "ACTIONS", acts)
    ctl = sc.SystemControl()
    with pytest.raises(PermissionError):
        ctl.start("stop_guide", "1111", False)
    with pytest.raises(ValueError):
        ctl.start("start_guide", "9464", False)          # HOME not confirmed
    ctl.start("restart_guide", "9464", True)
    for _ in range(50):
        if ctl.running is None: break
        time.sleep(0.05)
    out = "\n".join(ctl.output)
    assert ctl.last["ok"] and "g1_stop_guide.sh" in out and "g1_start_guide.sh --yes home=1" in out


def test_pin_lockout(tmp_path, monkeypatch):
    from app.services import system_control as sc
    (tmp_path / "pin").write_text("9464")
    monkeypatch.setattr(sc, "PIN_FILE", str(tmp_path / "pin"))
    ctl = sc.SystemControl()
    for _ in range(5):
        with pytest.raises(PermissionError):
            ctl.check_pin("0000")
    with pytest.raises(PermissionError, match="wait"):
        ctl.check_pin("9464")
