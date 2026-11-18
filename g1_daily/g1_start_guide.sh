#!/usr/bin/env bash
# =====================================================================
#  G1 guide mode: LiDAR driver + live FAST-LIO + guide service.
#  Run on the Ubuntu host AFTER g1_start_all.sh.
#
#  G1 MUST stand on the HOME tape (walking mode) when FAST-LIO starts:
#  the routes are taught relative to that spot.
# =====================================================================
set -u
CONTAINER=g1pilot-dev
TR=/ros2_ws/src/g1pilot/hfu_nav/teach_repeat
PIN_FILE=~/.g1_teleop_pin
ROS="source /opt/ros/humble/setup.bash && source /ros2_ws/install/setup.bash && export ROS_DOMAIN_ID=1 && export ROS_LOCALHOST_ONLY=0"
GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; NC='\033[0m'

running() { docker exec "$CONTAINER" pgrep -f "$1" >/dev/null 2>&1; }

echo; echo "=== 1/3  Livox MID-360 driver ==="
if running "livox_launcher"; then
  echo -e "  ${YEL}•${NC} already running"
else
  docker exec -d "$CONTAINER" bash -lc "$ROS && ros2 launch g1pilot livox_launcher.launch.py > /tmp/g1_livox.log 2>&1"
  echo -e "  ${GREEN}✔${NC} started (log /tmp/g1_livox.log)"; sleep 6
fi

echo; echo "=== 2/3  Live FAST-LIO (origin = HOME) ==="
if running "fastlio_mapping"; then
  echo -e "  ${YEL}•${NC} already running - origin is where it was started."
  echo "     To reset HOME: put G1 on the tape, run g1_stop_guide.sh, then this script again."
else
  read -r -p "  Is G1 standing on the HOME tape, facing the marked direction? [y/N] " ok
  if [ "${ok,,}" != "y" ]; then echo "  Put G1 on HOME first. Nothing started."; exit 1; fi
  docker exec -d "$CONTAINER" bash -lc "bash $TR/start_fastlio_live.sh > /tmp/g1_fastlio.log 2>&1"
  echo -e "  ${GREEN}✔${NC} started (log /tmp/g1_fastlio.log)"; sleep 8
fi

echo; echo "=== 3/3  Guide service (port 8002) ==="
if running "guide_service.py"; then
  echo -e "  ${YEL}•${NC} already running"
elif [ -f "$PIN_FILE" ]; then
  # Optional tuning: export G1_GUIDE_OBSTACLE_HALF_WIDTH=0.15 before running this script.
  docker exec -d -e G1_TELEOP_PIN="$(cat "$PIN_FILE")" \
    -e G1_GUIDE_OBSTACLE_HALF_WIDTH="${G1_GUIDE_OBSTACLE_HALF_WIDTH:-}" "$CONTAINER" \
    bash -lc "$ROS && python3 -u $TR/guide_service.py > /tmp/g1_guide.log 2>&1"
  echo -e "  ${GREEN}✔${NC} started (log /tmp/g1_guide.log)"; sleep 4
else
  echo -e "  ${RED}✘${NC} $PIN_FILE missing"; exit 1
fi

echo
curl -s -m 3 http://127.0.0.1:8002/api/guide/routes && echo
curl -s -m 3 http://127.0.0.1:8002/api/guide/status && echo
echo
echo "Ready. Visitors: Talk to G1 -> \"Guide me to the coffee machine\"."
echo "Teach a new route:  docker exec -it $CONTAINER bash -lc '$ROS && python3 $TR/route_tool.py record NAME --title-en \"...\" --title-de \"...\"'"
