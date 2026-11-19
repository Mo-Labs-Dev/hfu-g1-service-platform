#!/usr/bin/env bash
# Stop guide mode (guide service, FAST-LIO, Livox driver). Run on the host.
# The robot should be standing still. Waits until everything is really gone,
# so a following g1_start_guide.sh never runs two FAST-LIOs / LiDAR drivers.
CONTAINER=g1pilot-dev
PATTERNS="guide_service.py|start_fastlio_live.sh|localization_no_bridge.launch|fastlio_mapping|livox_launcher|livox_ros_driver2"

curl -s -m 2 -X POST http://127.0.0.1:8002/api/guide/cancel >/dev/null 2>&1
sleep 1
docker exec "$CONTAINER" pkill -INT -f "$PATTERNS" 2>/dev/null

for i in $(seq 1 10); do
  docker exec "$CONTAINER" pgrep -f "$PATTERNS" >/dev/null 2>&1 || break
  sleep 1
done
if docker exec "$CONTAINER" pgrep -f "$PATTERNS" >/dev/null 2>&1; then
  echo "Some processes did not stop - forcing them."
  docker exec "$CONTAINER" pkill -KILL -f "$PATTERNS" 2>/dev/null
  sleep 1
fi
left=$(docker exec "$CONTAINER" pgrep -af "$PATTERNS" 2>/dev/null)
if [ -n "$left" ]; then
  echo "WARNING - still running:"; echo "$left"
else
  echo "Guide mode stopped. (Teleop, voice, camera, backend still running.)"
fi
