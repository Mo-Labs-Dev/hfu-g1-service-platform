# Day 02 - G1 Locomotion

## Goal
Establish a safe and reusable locomotion interface for the Unitree G1 that can later be connected to the thesis navigation module.

## Environment
- Robot: Unitree G1 EDU
- Network interface: `enP2p1s0`
- Motion service: `sport`
- Unitree Python SDK: current official version
- Execution environment: `g1pilot-dev` Docker container

## Verified Robot State
The robot was successfully detected in locomotion state:

```text
Current FSM: 500
Locomotion ready: True
