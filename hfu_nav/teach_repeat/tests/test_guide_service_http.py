import json, sys, threading, time, urllib.request, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guide_service as gs
from test_route_core import l_route
from test_guide_runner import World, runner

def call(base, method, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())

def test_http_api(tmp_path):
    l_route().save(str(tmp_path))
    w = World(); g = runner(w)
    g.sleep = lambda dt: (w.sleep(dt), time.sleep(0.0005))     # run fast, but in a thread
    svc = gs.GuideService(g, str(tmp_path))
    srv = gs.ThreadingHTTPServer(("127.0.0.1", 0), gs.make_handler(svc))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    code, routes = call(base, "GET", "/api/guide/routes")
    assert code == 200 and routes[0]["name"] == "coffee_machine" and routes[0]["length_m"] == 10.0
    assert call(base, "POST", "/api/guide/start", {"route": "nope"})[0] == 409
    w.fsm = 4
    code, body = call(base, "POST", "/api/guide/start", {"route": "coffee_machine"})
    assert code == 409 and "walking mode" in body["detail"]
    w.fsm = 500
    code, body = call(base, "POST", "/api/guide/start", {"route": "coffee_machine", "wait_s": 1})
    assert code == 200
    assert call(base, "POST", "/api/guide/start", {"route": "coffee_machine"})[0] == 409   # already running
    svc.thread.join(timeout=20)
    code, st = call(base, "GET", "/api/guide/status")
    assert st["state"] == "done" and st["route"] == "coffee_machine"
    srv.shutdown()
