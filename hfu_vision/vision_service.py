#!/usr/bin/env python3
"""
G1 Vision service - "What do you see?" and "Find the bottle!".

Run INSIDE g1pilot-dev (like the guide service):
    G1_TELEOP_PIN=9464 python3 /ros2_ws/src/g1pilot/hfu_vision/vision_service.py

HTTP API (port 8003):
    POST /api/vision/describe {"question": "What is this?", "lang": "en"}  -> {"answer": ...}
    POST /api/vision/find     {"object": "find the bottle", "lang": "de"}  -> starts, poll status
    GET  /api/vision/status
    POST /api/vision/cancel
    GET  /api/vision/objects  -> what G1 can find

Uses: camera bridge :8770 (snapshot), G1 Studio backend :8000 (YOLO /api/vision/detect),
Ollama :11434 (vision model, default qwen2.5vl:3b), voice bridge :8766,
teleop server :8001 for turning (all teleop safety applies; app STOP cancels).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "hfu_nav", "teach_repeat"))
from vision_core import NAMES, OBJECTS, VisionRunner, find_target  # noqa: E402
from guide_service import TeleopMotion, Voice, http_json  # noqa: E402


def http_get_bytes(url: str, timeout: float = 5.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def shrink_jpeg(jpeg: bytes, max_side: int = 768) -> bytes:
    """Smaller picture = much faster vision model. Uses cv2 or PIL if available."""
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        s = max_side / max(h, w)
        if s < 1:
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
    except Exception:
        pass
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(jpeg))
        im.thumbnail((max_side, max_side))
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:
        return jpeg


class Camera:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def snapshot(self) -> bytes:
        data = http_get_bytes(f"{self.base}/snapshot", timeout=5)
        if not data:
            raise RuntimeError("camera returned no picture")
        return data


class Detector:
    """YOLO11 in the G1 Studio backend (POST /api/vision/detect, multipart)."""

    def __init__(self, base):
        self.base = base.rstrip("/")

    def detect(self, jpeg: bytes) -> dict:
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"g1.jpg\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n").encode() + jpeg + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{self.base}/api/vision/detect", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())


class OllamaVLM:
    def __init__(self, base, model):
        self.base, self.model = base.rstrip("/"), model

    def ask(self, jpeg: bytes, prompt: str) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False, "keep_alive": "60m",
                           "images": [base64.b64encode(shrink_jpeg(jpeg)).decode()],
                           "options": {"temperature": 0.2, "num_predict": 80}}).encode()
        req = urllib.request.Request(f"{self.base}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("response", "")

    def warm_up(self) -> None:
        try:
            body = json.dumps({"model": self.model, "keep_alive": "60m"}).encode()
            urllib.request.urlopen(urllib.request.Request(
                f"{self.base}/api/generate", data=body,
                headers={"Content-Type": "application/json"}), timeout=180).read()
            print(f"[vision] {self.model} loaded")
        except Exception as exc:
            print(f"[vision] WARNING: could not load {self.model}: {exc}")


def make_handler(svc):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def _json(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/vision/status":
                self._json(200, svc.runner.snapshot())
            elif path == "/api/vision/objects":
                self._json(200, sorted(OBJECTS))
            elif path == "/api/vision/health":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"detail": "Not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                return self._json(400, {"detail": "Invalid JSON"})
            lang = str(body.get("lang", "en"))
            if path == "/api/vision/match":
                label = find_target(str(body.get("text", "")))
                return self._json(200, {"label": label,
                                        "name_en": NAMES["en"].get(label) if label else None,
                                        "name_de": NAMES["de"].get(label) if label else None})
            if path == "/api/vision/cancel":
                svc.runner.cancel()
                return self._json(200, svc.runner.snapshot())
            if svc.busy():
                return self._json(409, {"detail": "G1 is busy with another vision task.", **svc.runner.snapshot()})
            if path == "/api/vision/describe":
                try:
                    with svc.lock:
                        answer = svc.runner.describe(str(body.get("question", "")), lang)
                    return self._json(200, {"answer": answer})
                except Exception as exc:
                    return self._json(503, {"detail": f"Vision not available: {exc}"})
            if path == "/api/vision/find":
                svc.start_find(str(body.get("object", "")), lang)
                return self._json(200, {"detail": "started", **svc.runner.snapshot()})
            self._json(404, {"detail": "Not found"})
    return H


class Service:
    def __init__(self, runner):
        self.runner = runner
        self.lock = threading.Lock()
        self.thread = None

    def busy(self) -> bool:
        return self.lock.locked() or (self.thread is not None and self.thread.is_alive())

    def start_find(self, obj: str, lang: str):
        def job():
            with self.lock:
                self.runner.find(obj, lang)
        self.runner._set(state="searching", task="find", message="Starting ...")
        self.thread = threading.Thread(target=job, daemon=True)
        self.thread.start()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8003)
    ap.add_argument("--camera", default="http://127.0.0.1:8770")
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default=os.environ.get("G1_VISION_MODEL", "qwen2.5vl:3b"))
    ap.add_argument("--teleop", default="http://127.0.0.1:8001")
    ap.add_argument("--voice", default="http://127.0.0.1:8766")
    args = ap.parse_args()
    pin = os.environ.get("G1_TELEOP_PIN", "")
    if not pin:
        sys.exit("Set G1_TELEOP_PIN (same PIN as the teleop server).")
    vlm = OllamaVLM(args.ollama, args.model)
    threading.Thread(target=vlm.warm_up, daemon=True).start()
    runner = VisionRunner(Camera(args.camera), Detector(args.backend), vlm,
                          TeleopMotion(args.teleop, pin, operator="G1 vision"), Voice(args.voice))
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(Service(runner)))
    print(f"[vision] listening on http://0.0.0.0:{args.port}/api/vision/... (model {args.model})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.cancel()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
