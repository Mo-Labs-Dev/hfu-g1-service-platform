import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from g1_walk_safety import G1WalkSafety


command_log = []


def simulated_sdk(vx, vy, yaw):
    command_log.append({
        "time": round(time.monotonic(), 3),
        "vx": vx,
        "vy": vy,
        "yaw": yaw,
    })
    print(f"SIMULATED SDK: vx={vx}, vy={vy}, yaw={yaw}")


controller = G1WalkSafety(simulated_sdk)

threading.Thread(
    target=controller.watchdog,
    daemon=True,
).start()


class Handler(BaseHTTPRequestHandler):

    def respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/status":
            return self.respond(404, {"error": "Not found"})

        self.respond(200, {
            "mode": "simulation_only",
            "armed": controller.armed,
            "fault": controller.fault,
            "commands": command_log[-10:],
            "real_robot_connected": False,
        })

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1024:
                raise ValueError("Invalid payload length")

            payload = json.loads(self.rfile.read(length) or b"{}")

            if self.path == "/arm":
                success = controller.arm(
                    payload.get("confirmed") is True
                )
                return self.respond(
                    200 if success else 403,
                    {"armed": success},
                )

            if self.path == "/move":
                controller.command(
                    float(payload.get("vx", 0)),
                    float(payload.get("vy", 0)),
                    float(payload.get("yaw", 0)),
                )
                return self.respond(200, {
                    "status": "simulated_command_accepted"
                })

            if self.path == "/stop":
                controller.stop()
                return self.respond(200, {
                    "status": "simulated_stop_sent"
                })

            return self.respond(404, {"error": "Not found"})

        except (ValueError, TypeError, RuntimeError) as error:
            self.respond(409, {"error": str(error)})


if __name__ == "__main__":
    print("G1 walking API simulator: http://127.0.0.1:8771")
    print("REAL ROBOT MOVEMENT: DISABLED")
    ThreadingHTTPServer(
        ("127.0.0.1", 8771),
        Handler,
    ).serve_forever()
