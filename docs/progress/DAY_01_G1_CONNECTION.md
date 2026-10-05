# Day 01 - G1 Connection and Locomotion Validation

## Goal

Establish communication with the Unitree G1 through G1Pilot and validate the first safe robot state transitions before locomotion testing.

## Environment

- Robot: Unitree G1
- Framework: G1Pilot
- Middleware: ROS 2 Humble
- SDK: unitree_sdk2_python
- Environment: Docker
- Network interface: enP2p1s0
- Connection: Ethernet
- Safety: G1 supported by laboratory crane/harness

## Control Architecture

Thesis Software
-> G1Pilot
-> unitree_sdk2_python
-> Unitree Sport RPC
-> G1 Locomotion Controller
-> Unitree G1

## SDK Compatibility Issue

The installed Unitree SDK used:

LOCO_SERVICE_NAME = "loco"

RPC communication failed with this service.

Newer Unitree SDK versions use:

LOCO_SERVICE_NAME = "sport"

After temporarily changing the service from "loco" to "sport" inside the Docker container, communication with the real G1 succeeded.

This compatibility change must later be made reproducible in the Docker/G1Pilot setup.

## Real Robot Tests

Initial state:

FSM ID = 0
FSM Mode = 0

FSM 0 corresponds to ZeroTorque.

### Damp

Command:

robot.Damp()

Result:

FSM ID = 1
FSM Mode = 0

The transition succeeded.

### StandUp

Command:

robot.SetFsmId(4)

Newer Unitree SDK versions define FSM 4 as StandUp.

Immediately after the command:

FSM ID = 4
FSM Mode = 1

After the robot settled:

FSM ID = 4
FSM Mode = 0

The robot entered a supported standing/crouched posture.

## Safety

No walking command was sent during Day 01.

The following were NOT tested:

- BalanceStand()
- Start() / FSM 200
- Move()
- Autonomous navigation

The robot remained attached to the safety crane/harness during physical testing.

## Open Issue

G1Pilot currently contains two different balance commands:

tools/test.py:
BalanceStand(0)

navigation/loco_client.py:
BalanceStand(1)

The correct balance mode must be verified before locomotion testing.

## Day 01 Result

- G1Pilot architecture inspected
- Docker and ROS 2 environment verified
- Real G1 telemetry confirmed
- Ethernet interface enP2p1s0 confirmed
- Unitree RPC communication confirmed
- loco vs sport compatibility issue identified
- ZeroTorque -> Damp validated
- Damp -> StandUp validated
- FSM 4 / Mode 0 stable state reached
- No walking command issued

## Day 02

1. Verify balance/start sequence
2. Validate locomotion-ready state
3. Validate STOP before movement
4. Perform smallest controlled walking test
5. Integrate locomotion into G1PilotAdapter
