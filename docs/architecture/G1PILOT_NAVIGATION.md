# G1Pilot Navigation Architecture

## Overview

G1Pilot provides the underlying ROS 2 and Unitree SDK integration used to control the Unitree G1 humanoid robot.

The existing navigation pipeline was investigated before implementing the thesis navigation module.

## Navigation Pipeline

Navigation Goal
↓
Dijkstra Planner
↓
Path
↓
Nav2Point
↓
JoyMux
↓
LocoClient
↓
Unitree SDK
↓
Unitree G1

## ROS 2 Interfaces

### Navigation Goal

Topic:

`/g1pilot/goal`

Message:

`geometry_msgs/PoseStamped`

The goal is received by the Dijkstra planner.

### Planned Path

Topic:

`/g1pilot/path`

Message:

`nav_msgs/Path`

The Dijkstra planner generates a path from the current robot position to the requested goal.

### Localization

Topic:

`/lidar_odometry/pose_fixed`

Message:

`nav_msgs/Odometry`

This provides the current robot position and orientation.

### Autonomous Motion Command

Topic:

`/g1pilot/auto_joy`

Message:

`sensor_msgs/Joy`

Nav2Point converts the navigation path into velocity-related joystick commands.

### Command Multiplexer

JoyMux receives:

`/g1pilot/auto_joy`

and

`/g1pilot/joy_manual`

It publishes the selected command to:

`/g1pilot/joy`

### Robot Locomotion

LocoClient subscribes to:

`/g1pilot/joy`

and communicates with the Unitree locomotion controller using `unitree_sdk2py`.

Movement is ultimately executed using:

`LocoClient.Move(vx, vy, vyaw)`

Stopping is performed using:

`LocoClient.StopMove()`

## Thesis Integration Strategy

The thesis application should not directly depend on Unitree SDK locomotion commands.

Instead:

NavigationModule
↓
G1PilotAdapter
↓
G1Pilot navigation interface
↓
Unitree G1

This keeps the application modular and reduces coupling between high-level service logic and robot-specific control software.
