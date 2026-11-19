#!/usr/bin/env bash
# G1 daily status check - read-only. Run on the Ubuntu host.
set -u
GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

check() {   # name, url, text-that-must-appear
  local body
  body=$(curl -s -m 3 "$2" 2>/dev/null)
  if [ -n "$body" ] && echo "$body" | grep -Eq "$3"; then
    echo -e "  ${GREEN}✔${NC} $1"
  else
    echo -e "  ${RED}✘${NC} $1   ($2 → ${body:0:120})"
  fi
}

echo
echo "=== G1 status ==="
check "Voice bridge   :8766  (Piper voices loaded)" http://127.0.0.1:8766/health '"engine": *"piper"'
check "Camera bridge  :8770  (frames arriving)"     http://127.0.0.1:8770/status '"camera_connected": *true'
check "Status bridge  :8767"                        http://127.0.0.1:8767/health '.'
check "Teleop server  :8001  (robot FSM readable)"  http://127.0.0.1:8001/api/teleop/status '"fsm_id": *[0-9]'
check "Vision service :8003  (describe / find)"     http://127.0.0.1:8003/api/vision/health '"ok"'
check "Backend        :8000"                        http://127.0.0.1:8000/api/visitor-speech/status 'speech_bridge'
check "Local AI (Ollama) :11434"                    http://127.0.0.1:11434/api/tags 'g1-assistant'
echo
FSM=$(curl -s -m 3 http://127.0.0.1:8001/api/teleop/status | grep -Eo '"fsm_id": *[0-9]+' | grep -Eo '[0-9]+$')
echo "  Robot FSM: ${FSM:-unknown}   (500 = walking mode; Robot Show + joystick need 500)"
IP=$(ip -4 -o addr show wlP1p1s0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
echo "  App address: http://${IP:-?}  (backend 8000, joystick 8001, camera 8770) - set it in the app's operator screen if it changed"
echo
