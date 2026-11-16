#!/usr/bin/env bash
# G1 daily stop. Run on the Ubuntu host.
# Make sure the robot is standing still (or in the harness) before stopping.
set -u
CONTAINER=g1pilot-dev

echo "Stopping teleop server first (it stops any robot motion on exit)..."
docker exec "$CONTAINER" pkill -INT -f run_teleop_server.py 2>/dev/null
sleep 2
echo "Stopping backend..."
pkill -f "uvicorn app.main:app" 2>/dev/null
echo "Stopping voice, camera and status bridges..."
docker exec "$CONTAINER" pkill -INT -f g1_voice_bridge.py 2>/dev/null
docker exec "$CONTAINER" pkill -INT -f g1_camera_bridge.py 2>/dev/null
docker exec "$CONTAINER" pkill -INT -f g1_status_bridge.py 2>/dev/null
sleep 1
echo "Done. Docker containers are left running."
