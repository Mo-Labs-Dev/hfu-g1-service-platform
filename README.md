# HFU G1 Service Platform

Modular software platform for the Unitree G1 humanoid robot developed as part of a Master's thesis at Hochschule Furtwangen University (HFU).

## Thesis

**Interactive Humanoid Robot for Customer Assistance and Autonomous Guidance and Demonstration Tasks**

## Objective

The goal of this project is to develop an extensible software platform that enables the Unitree G1 humanoid robot to perform service tasks in a laboratory environment.

The system is designed around reusable modules so that additional robot capabilities can be integrated in the future without redesigning the complete application.

## Core Modules

### Navigation
Autonomous robot movement, localization, path planning and guidance to predefined destinations.

### Communication
Human-robot interaction through touch and speech.

### Perception
Environment and object detection for robot tasks.

### Manipulation
Object interaction, picking and demonstration tasks.

## System Architecture

High-level architecture:

User Interface  
↓  
Backend / Task Manager  
↓  
Reusable Robot Modules  
↓  
G1Pilot Adapter  
↓  
G1Pilot / ROS 2  
↓  
Unitree G1

## G1Pilot Integration

The project uses G1Pilot as the underlying robot control platform.

Initial investigation identified the following navigation pipeline:

Navigation Goal  
→ Dijkstra Planner  
→ Path  
→ Nav2Point  
→ JoyMux  
→ LocoClient  
→ Unitree SDK  
→ Unitree G1

The thesis software will interact with G1Pilot through a dedicated adapter instead of directly coupling application logic to the Unitree SDK.

## Current Development Phase

Phase 1 focuses on:

- Understanding the existing G1Pilot environment
- Establishing the software architecture
- Implementing the G1Pilot adapter
- Implementing the Navigation module
- Testing safe robot locomotion
- Autonomous guidance to predefined destinations

## Project Structure

- `docs/` - architecture and technical documentation
- `backend/` - API and task management
- `modules/` - reusable robot capabilities
- `robot/g1pilot_adapter/` - interface between this platform and G1Pilot
- `config/` - system configuration
- `tests/` - automated and integration tests
- `scripts/` - development and deployment utilities

## Status

Development in progress.
