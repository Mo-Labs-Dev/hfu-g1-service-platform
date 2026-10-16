from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient


HOST = "127.0.0.1"
PORT = 8767
INTERFACE = "enP2p1s0"

FSM_GET_ID_API = 7001

ALLOW_POSTURE_COMMANDS = (
    os.getenv("G1_ALLOW_POSTURE_COMMANDS") == "1"
)

ALLOW_LOCOMOTION_COMMANDS = (
    os.getenv("G1_ALLOW_LOCOMOTION_COMMANDS") == "1"
)

CONTROL_TOKEN = os.getenv("G1_BRIDGE_TOKEN", "")


MODES = {
    "damp": {
        "source": 0,
        "target": 1,
        "permission": "posture",
    },
    "stand_up": {
        "source": 1,
        "target": 4,
        "permission": "posture",
    },
    "start_locomotion": {
        "source": 4,
        "target": 500,
        "permission": "locomotion",
    },
}


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("g1-status-bridge")

client_lock = threading.Lock()


def posture_available() -> bool:
    return (
        ALLOW_POSTURE_COMMANDS
        and bool(CONTROL_TOKEN)
    )


def locomotion_available() -> bool:
    return (
        ALLOW_LOCOMOTION_COMMANDS
        and bool(CONTROL_TOKEN)
    )


def create_client() -> LocoClient:
    ChannelFactoryInitialize(0, INTERFACE)

    client = LocoClient()
    client.SetTimeout(3.0)
    client.Init()

    return client


robot_client = create_client()


def _extract_fsm_id(data) -> int:
    """
    Parse the response returned by G1 GET FSM ID API 7001.

    The installed G1 SDK registers API 7001 but does not expose
    a GetFsmId() convenience method, so the bridge calls _Call()
    directly.
    """

    if data is None:
        raise RuntimeError(
            "GET FSM ID returned no data"
        )

    if isinstance(data, bool):
        raise RuntimeError(
            f"Unexpected boolean FSM response: {data}"
        )

    if isinstance(data, int):
        return int(data)

    if isinstance(data, float):
        return int(data)

    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError(
                "Unable to decode FSM response bytes"
            ) from error

    if isinstance(data, str):
        text = data.strip()

        if not text:
            raise RuntimeError(
                "GET FSM ID returned an empty response"
            )

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                return int(text)
            except ValueError as error:
                raise RuntimeError(
                    f"Unable to parse FSM response: {text!r}"
                ) from error

        return _extract_fsm_id(parsed)

    if isinstance(data, dict):
        possible_keys = (
            "data",
            "fsm_id",
            "fsmId",
            "id",
            "value",
        )

        for key in possible_keys:
            if key in data:
                return _extract_fsm_id(
                    data[key]
                )

        raise RuntimeError(
            "FSM response object did not contain "
            f"a known FSM field: {data!r}"
        )

    if isinstance(data, (list, tuple)):
        if len(data) == 0:
            raise RuntimeError(
                "GET FSM ID returned an empty sequence"
            )

        # Some RPC responses may wrap the useful value.
        for item in data:
            try:
                return _extract_fsm_id(item)
            except RuntimeError:
                continue

        raise RuntimeError(
            f"Unable to parse FSM response: {data!r}"
        )

    raise RuntimeError(
        f"Unsupported FSM response type: "
        f"{type(data).__name__}: {data!r}"
    )


def read_fsm() -> int:
    """
    Read the physical G1 FSM using the registered
    GET FSM ID RPC API (7001).

    The installed LocoClient has no GetFsmId()
    convenience method, but it registers API 7001
    during Init().
    """

    code, data = robot_client._Call(
        FSM_GET_ID_API,
        "{}",
    )

    if code != 0:
        raise RuntimeError(
            f"GET FSM ID failed: code={code}"
        )

    return _extract_fsm_id(data)


def get_live_status() -> dict:
    with client_lock:
        fsm_id = read_fsm()

    return {
        "connected": True,
        "source": "physical_g1",
        "fsm_id": fsm_id,
        "locomotion_mode": fsm_id == 500,
        "motion_enabled": False,
        "posture_control_available": (
            posture_available()
        ),
        "locomotion_control_available": (
            locomotion_available()
        ),
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def request_control(
    action: str,
    confirmed: bool,
) -> tuple[int, dict]:

    if not isinstance(action, str):
        return 400, {
            "status": "blocked",
            "error": "Invalid action",
        }

    mode = MODES.get(action)

    if mode is None:
        return 400, {
            "status": "blocked",
            "error": "Unsupported control action",
        }

    if mode["permission"] == "posture":
        authorized = posture_available()
    else:
        authorized = locomotion_available()

    if not authorized:
        return 403, {
            "status": "blocked",
            "action": action,
            "error": (
                "Requested physical control "
                "is not armed"
            ),
        }

    if not confirmed:
        return 400, {
            "status": "blocked",
            "action": action,
            "error": (
                "Operator confirmation required"
            ),
        }

    if not client_lock.acquire(
        blocking=False
    ):
        return 409, {
            "status": "busy",
            "action": action,
            "error": "Robot SDK is busy",
        }

    try:
        before = read_fsm()

        expected_source = mode["source"]
        target = mode["target"]

        if before != expected_source:
            return 409, {
                "status": "blocked",
                "action": action,
                "before_fsm": before,
                "expected_fsm": expected_source,
                "target_fsm": target,
                "error": (
                    "Unexpected source FSM"
                ),
            }

        logger.warning(
            "Operator-confirmed physical control: "
            "%s, FSM %s -> %s",
            action,
            before,
            target,
        )

        # IMPORTANT:
        #
        # This only requests an FSM transition.
        #
        # No SetVelocity()
        # No Move()
        # No gait command
        # No trajectory command
        #
        code = robot_client.SetFsmId(
            target
        )

        if code != 0:
            return 502, {
                "status": "rejected",
                "action": action,
                "sdk_code": code,
                "before_fsm": before,
                "target_fsm": target,
                "error": (
                    "SDK rejected FSM transition"
                ),
            }

        deadline = (
            time.monotonic() + 8.0
        )

        last_fsm = before

        while time.monotonic() < deadline:
            current = read_fsm()
            last_fsm = current

            if current == target:
                logger.warning(
                    "FSM transition confirmed: "
                    "%s -> %s",
                    before,
                    current,
                )

                return 200, {
                    "status": "fsm_confirmed",
                    "action": action,
                    "before_fsm": before,
                    "after_fsm": current,
                    "physical_posture_verified": (
                        False
                    ),
                    "physical_motion_verified": (
                        False
                    ),
                }

            time.sleep(0.25)

        return 504, {
            "status": "unverified",
            "action": action,
            "before_fsm": before,
            "after_fsm": last_fsm,
            "target_fsm": target,
            "error": (
                "Target FSM was not confirmed"
            ),
        }

    except Exception as error:
        logger.exception(
            "Physical control request failed"
        )

        return 503, {
            "status": "error",
            "action": action,
            "error": str(error),
        }

    finally:
        client_lock.release()


class Handler(BaseHTTPRequestHandler):

    def respond(
        self,
        status: int,
        payload: dict,
    ) -> None:

        body = json.dumps(
            payload
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()

        self.wfile.write(body)

    def do_GET(self) -> None:

        if self.path == "/health":
            self.respond(
                200,
                {
                    "status": "ok",
                    "service": (
                        "g1-status-bridge"
                    ),
                    "posture_control_available": (
                        posture_available()
                    ),
                    "locomotion_control_available": (
                        locomotion_available()
                    ),
                },
            )

            return

        if self.path != "/status":
            self.respond(
                404,
                {"error": "Not found"},
            )

            return

        try:
            self.respond(
                200,
                get_live_status(),
            )

        except Exception as error:
            logger.exception(
                "Unable to read G1 FSM"
            )

            self.respond(
                503,
                {
                    "connected": False,
                    "source": "physical_g1",
                    "fsm_id": None,
                    "locomotion_mode": False,
                    "motion_enabled": False,
                    "posture_control_available": (
                        posture_available()
                    ),
                    "locomotion_control_available": (
                        locomotion_available()
                    ),
                    "error": str(error),
                },
            )

    def do_POST(self) -> None:

        if self.path != "/posture":
            self.respond(
                404,
                {"error": "Not found"},
            )

            return

        provided_token = self.headers.get(
            "X-G1-Bridge-Token",
            "",
        )

        if (
            not CONTROL_TOKEN
            or not hmac.compare_digest(
                provided_token,
                CONTROL_TOKEN,
            )
        ):
            self.respond(
                403,
                {
                    "error": (
                        "Unauthorized control request"
                    )
                },
            )

            return

        try:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

            if length <= 0 or length > 1024:
                raise ValueError(
                    "Invalid request size"
                )

            payload = json.loads(
                self.rfile.read(length)
            )

            if not isinstance(
                payload,
                dict,
            ):
                raise ValueError(
                    "Invalid JSON payload"
                )

            action = payload.get(
                "action"
            )

            confirmed = (
                payload.get("confirmed")
                is True
            )

            code, result = request_control(
                action,
                confirmed,
            )

            self.respond(
                code,
                result,
            )

        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ):
            self.respond(
                400,
                {
                    "error": (
                        "Invalid request"
                    )
                },
            )


if __name__ == "__main__":

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    logger.info(
        "G1 bridge listening on %s:%s",
        HOST,
        PORT,
    )

    logger.info(
        "Posture commands armed: %s",
        posture_available(),
    )

    logger.info(
        "Locomotion commands armed: %s",
        locomotion_available(),
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()