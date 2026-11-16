# Operator Joystick (Teleop)

Drive the G1 manually from the G1 Remote app.

## Architecture

```
G1 Remote app (OperatorJoystickScreen)
  │  WebSocket, normalized stick values (-1..1) at 10 Hz
  ▼
robot/teleop/teleop_api.py        FastAPI router  /api/teleop/*
  ▼
robot/teleop/teleop_controller.py TeleopController (single motion owner, 20 Hz loop)
  ▼
robot/teleop/motion_backends.py   UnitreeMotionBackend → LocoClient.SetVelocity()
  ▼
Unitree G1 (FSM 500)
```

The app never decides speeds. The robot server owns every safety check.

## Safety layers (software)

| Layer | Behaviour |
|---|---|
| PIN (server-side) | `G1_TELEOP_PIN` env var, constant-time compare, 5 wrong tries → 60 s lockout |
| Single operator lease | Only one app can drive; lease expires after 30 s of silence |
| Dead-man | No joystick message for 0.3 s → immediate stop |
| Short velocity duration | Each `SetVelocity` lasts 0.4 s, so the robot stops even if the server freezes |
| Speed clamps | forward 0.30, backward 0.15, sideways 0.20 m/s, yaw 0.40 rad/s; app "Slow" mode halves these |
| Acceleration limits | 0.5 m/s² accelerate, 1.0 m/s² decelerate |
| FSM gate | Moves only while FSM ∈ {500}, checked every 1 s |
| Latched E-stop | From app or `POST /api/teleop/estop`; needs explicit reset |
| RPC failure | Any SDK error latches the E-stop |
| Disconnect | WebSocket closed → stop |

**The physical E-stop / Unitree remote remains the primary safety device.**

Do not run another motion sender (e.g. G1Pilot's LocoClient node publishing
`/g1pilot/joy`) at the same time. Later, Nav2 `/cmd_vel` will be routed through
the same controller so teleop always overrides autonomy.

## Run

```bash
pip install fastapi uvicorn          # once, in the g1pilot-dev container

# 1) Mock (no robot)
G1_TELEOP_PIN=4821 python3 scripts/run_teleop_server.py --mock

# 2) Real robot - robot already in FSM 500, harness attached
G1_TELEOP_PIN=4821 python3 scripts/run_teleop_server.py --interface enP2p1s0 \
    --max-forward 0.15 --max-yaw 0.25
```

Server listens on port 8001. In the app, `G1TeleopConfig.BASE_URL` points to
`http://10.150.68.160:8001`.

To mount it in the main backend instead (port 8000):

```python
from robot.teleop.motion_backends import UnitreeMotionBackend
from robot.teleop.teleop_controller import TeleopController
from robot.teleop.teleop_api import create_teleop_router

teleop = TeleopController(UnitreeMotionBackend("enP2p1s0"),
                          pin=os.environ["G1_TELEOP_PIN"])
app.include_router(create_teleop_router(teleop))
# start teleop.start() on startup, teleop.shutdown() on shutdown
```

## Open the joystick in the app

Long-press the HFU logo in the header → PIN → drive.

- Left stick: walk (up = forward, sideways = step left/right)
- Right stick: turn
- STOP: always available, even when locked

## Test sequence on the real robot

1. Mock mode, check the `[MOCK] SetVelocity` output while moving the sticks.
2. Robot in harness, `--max-forward 0.10 --max-yaw 0.20`, Slow mode.
3. Verify: release stick → stops; turn Wi-Fi off on tablet → stops within ~0.4 s;
   kill the server → stops within 0.4 s; app E-STOP → stops and stays stopped.
4. Only then raise limits and remove the harness.
