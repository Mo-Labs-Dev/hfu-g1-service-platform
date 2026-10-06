# Day 02 - G1 Locomotion Integration

## Objective
Validate communication with the Unitree G1 locomotion controller and identify safe state transitions before enabling autonomous navigation.

## Environment
- Robot: Unitree G1
- Network interface: enP2p1s0
- Host IP: 192.168.123.51
- ROS 2: Humble in Docker
- Integration: G1Pilot + unitree_sdk2_python

## Verified State Transitions
FSM 1: Damp state.

FSM 4: Ready state.
SetFsmId(4) returned code 0.
The robot entered a crouched ready posture and announced "ready mode".

FSM 500: Standing state.
SetFsmId(500) returned code 0.
The robot successfully transitioned into a standing posture.
The FSM query confirmed ID 500.

## Velocity Test
A small forward velocity command of 0.05 m/s was sent for 0.5 seconds.

The command returned code 0, but the robot did not walk.

The explicit zero-velocity stop command also returned code 0.

## Gait Mode Test
SetBalanceMode(1) returned code 0 while the robot remained in FSM 500.

Physical observation:
The robot started repeated up-and-down movement instead of controlled forward walking.

The test was stopped and the robot was powered down.

IMPORTANT:
SetBalanceMode(1) must not be repeated until the correct locomotion startup sequence for this robot firmware is verified.

## G1Pilot Compatibility Finding
The local G1Pilot locomotion implementation does not match the behavior verified on the physical G1.

The physical robot currently confirms:
FSM 1 -> Damp
FSM 4 -> Ready
FSM 500 -> Standing

The G1Pilot locomotion startup must therefore be adapted and validated before it is allowed to control the physical robot.

## Navigation Progress
The following software chain has been validated independently:

MID360 -> Livox ROS -> MOLA -> pose_fixed -> Dijkstra Planner -> path -> nav2point -> auto_joy

nav2point successfully generated locomotion commands.

The final connection from generated commands to physical locomotion remains disabled for safety.

## Current Status
Working:
- G1 communication
- Robot telemetry
- FSM querying
- Ready state
- Standing state
- MID360 LiDAR
- MOLA localization
- Fixed odometry
- Dijkstra planning
- nav2point command generation

Pending:
- Correct walking-mode activation
- Controlled forward walking
- Safe G1Pilot locomotion adapter
- Autonomous waypoint navigation

## Safety Decision
Physical navigation remains locked until the G1 walking startup sequence is validated.
