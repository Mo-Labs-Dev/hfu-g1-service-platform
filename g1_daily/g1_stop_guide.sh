#!/usr/bin/env bash
# Stop guide mode (guide service, FAST-LIO, Livox driver). Run on the host.
# The robot should be standing still.
CONTAINER=g1pilot-dev
curl -s -m 2 -X POST http://127.0.0.1:8002/api/guide/cancel >/dev/null 2>&1
sleep 1
docker exec "$CONTAINER" pkill -INT -f guide_service.py 2>/dev/null
docker exec "$CONTAINER" pkill -INT -f start_fastlio_live.sh 2>/dev/null
docker exec "$CONTAINER" pkill -INT -f fastlio_mapping 2>/dev/null
docker exec "$CONTAINER" pkill -INT -f livox_launcher 2>/dev/null
sleep 2
echo "Guide mode stopped. (Teleop, voice, camera, backend still running.)"
