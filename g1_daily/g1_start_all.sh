#!/usr/bin/env bash
# =====================================================================
#  G1 daily start - starts everything the G1 Remote app needs.
#  Run on the Ubuntu host (NOT inside Docker):
#      ~/Documents/Projekte/g1pilot-main/g1_daily/g1_start_all.sh
#  Safe to run twice: services that are already running are skipped.
# =====================================================================
set -u

STUDIO=~/Documents/Projekte/hfu-g1-studio
CONTAINER=g1pilot-dev
PLATFORM=/ros2_ws/src/g1pilot/hfu-g1-service-platform-main
VOICE=/ros2_ws/src/g1pilot/hfu_voice/g1_voice_bridge.py
LOGS=~/g1_logs
PIN_FILE=~/.g1_teleop_pin
TOKEN_FILE=~/.g1_bridge_token

# Robot settings (change here if needed)
MAX_FORWARD=0.25
MAX_YAW=0.8      # joystick turn speed (server max 0.8); the guide keeps its own tested 0.21-0.30 rad/s
VOICE_EN=en_US-ryan-medium.onnx

GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✔${NC} $*"; }
bad()  { echo -e "  ${RED}✘${NC} $*"; }
info() { echo -e "  ${YEL}•${NC} $*"; }

mkdir -p "$LOGS"

running_in_container() {   # $1 = pattern
  docker exec "$CONTAINER" pgrep -f "$1" >/dev/null 2>&1
}

echo
echo "=== 1/7  Docker containers ==="
docker start g1-postgres "$CONTAINER" >/dev/null && ok "g1-postgres and $CONTAINER running" \
  || { bad "Docker containers could not start"; exit 1; }

echo
echo "=== 2/7  Voice bridge (Piper, port 8766) ==="
if running_in_container "g1_voice_bridge.py"; then
  info "already running - skipped"
else
  docker exec "$CONTAINER" pkill -f g1_speech_bridge.py >/dev/null 2>&1   # old bridge uses the same port
  docker exec -d -e G1_VOICE_EN="$VOICE_EN" "$CONTAINER" \
    bash -lc "python3 -u $VOICE > /tmp/g1_voice.log 2>&1"
  ok "started (log: docker exec $CONTAINER cat /tmp/g1_voice.log)"
fi

echo
echo "=== 3/7  Camera bridge (port 8770) ==="
if running_in_container "g1_camera_bridge.py"; then
  info "already running - skipped"
else
  docker exec -d "$CONTAINER" \
    bash -lc "python3 -u /ros2_ws/g1_camera_bridge.py > /tmp/g1_camera.log 2>&1"
  ok "started (log: docker exec $CONTAINER cat /tmp/g1_camera.log)"
fi

echo
echo "=== 4/7  Status bridge (port 8767, read-only: no FSM flags) ==="
if running_in_container "g1_status_bridge.py"; then
  info "already running - skipped"
elif [ -f "$TOKEN_FILE" ]; then
  docker exec -d -e G1_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")" -e ROS_DOMAIN_ID=1 "$CONTAINER" \
    bash -lc "cd /ros2_ws && python3 -u g1_status_bridge.py > /tmp/g1_status.log 2>&1"
  ok "started (log: docker exec $CONTAINER cat /tmp/g1_status.log)"
else
  bad "token file $TOKEN_FILE missing - status bridge not started"
fi

echo
echo "=== 5/7  Teleop / joystick / Robot Show server (port 8001) ==="
if running_in_container "run_teleop_server.py"; then
  info "already running - skipped"
elif [ -f "$PIN_FILE" ]; then
  docker exec -d -e G1_TELEOP_PIN="$(cat "$PIN_FILE")" "$CONTAINER" \
    bash -lc "cd $PLATFORM && python3 -u scripts/run_teleop_server.py --interface enP2p1s0 \
      --max-forward $MAX_FORWARD --max-yaw $MAX_YAW > /tmp/g1_teleop.log 2>&1"
  ok "started (log: docker exec $CONTAINER cat /tmp/g1_teleop.log)"
else
  bad "PIN file $PIN_FILE missing. Create it once with:  echo 4821 > $PIN_FILE && chmod 600 $PIN_FILE"
fi

echo
echo "=== 6/7  G1 Vision service (port 8003: describe scene / find object) ==="
if running_in_container "vision_service.py"; then
  info "already running - skipped"
elif [ -f "$PIN_FILE" ]; then
  docker exec -d -e G1_TELEOP_PIN="$(cat "$PIN_FILE")" "$CONTAINER" \
    bash -lc "python3 -u /ros2_ws/src/g1pilot/hfu_vision/vision_service.py > /tmp/g1_vision.log 2>&1"
  ok "started (log: docker exec $CONTAINER cat /tmp/g1_vision.log; model loads in the background)"
else
  bad "PIN file $PIN_FILE missing - vision service not started"
fi

echo
echo "=== 7/7  G1 Studio backend (port 8000) ==="
if pgrep -f "uvicorn app.main:app" >/dev/null; then
  info "already running - skipped"
else
  (
    cd "$STUDIO" || exit 1
    [ -f "$TOKEN_FILE" ] && export G1_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"
    export G1_BRIDGE_URL=http://127.0.0.1:8767
    # Automatic camera welcome stays OFF (add G1_AUTO_WELCOME=1 to enable).
    nohup services/api/.venv/bin/python -m uvicorn app.main:app \
      --app-dir services/api --host 0.0.0.0 --port 8000 > "$LOGS/backend.log" 2>&1 &
  )
  ok "started (log: $LOGS/backend.log)"
fi

echo
echo "Waiting 12 s for everything to come up..."
sleep 12
"$(dirname "$0")/g1_status.sh"
