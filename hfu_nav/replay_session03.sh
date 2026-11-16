#!/usr/bin/env bash
# =====================================================================
#  Offline localization test: replay the Session 03 walk through the lab
#  and check that FAST_LIO_LOCALIZATION stays localized the whole way.
#
#  Run INSIDE g1pilot-dev:
#      bash /ros2_ws/src/g1pilot/hfu_nav/replay_session03.sh
#  Options (environment variables):
#      RATE=2.0            play the bag 2x faster (default 1.0 = 24 min)
#      START_OFFSET=300    start 300 s into the bag (needs a matching INIT_POSE)
#      INIT_POSE="0 0 0 0 0 0"   x y z yaw pitch roll in the map (PCD) frame
#
#  Safety: uses ROS_DOMAIN_ID=77, so nothing here talks to the live robot
#  (domain 1). Session 03 map and bag are only READ.
# =====================================================================
set +u   # ROS setup.bash does not support 'set -u'

MAP=/ros2_ws/maps/hfu_lab_full/session_03/hfu_lab_static.pcd
BAG=/ros2_ws/maps/hfu_lab_full/session_03/rosbag/full_lab_session_03
NAV2D=/ros2_ws/maps/hfu_lab_full/nav2d_session03
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=/ros2_ws/maps/hfu_lab_full/localization_tests/replay_$(date +%Y%m%d_%H%M%S)
RATE=${RATE:-1.0}
START_OFFSET=${START_OFFSET:-0}
INIT_POSE=${INIT_POSE:-"0 0 0 0 0 0"}
DIAG=${DIAG:-0}          # DIAG=1: relaxed correction limits (test only)
LOC=${LOC:-1}            # LOC=0: FAST-LIO only (no localizer) - compare odometry
PFN=${PFN:-1}            # point_filter_num (mapping day: 1)
SHARED=/ros2_ws/src/g1pilot/localization_results   # visible on the host

mkdir -p "$OUT"
echo "Results will be written to: $OUT"

export ROS_DOMAIN_ID=77          # isolated from the live robot
export ROS_LOCALHOST_ONLY=1
# Bag has /livox/lidar as sensor_msgs/PointCloud2 -> FAST-LIO lidar_type 5
# (the value in fast_lio/config/mid360.yaml, same as during mapping).
unset G1_SENSOR_BACKEND
export PYTHONNOUSERSITE=1
source /opt/ros/humble/setup.bash
source /ros2_ws/install/setup.bash
source /ros2_ws/.venv-localization/bin/activate

copy_results() {
  mkdir -p "$SHARED/$(basename "$OUT")"
  cp "$OUT"/localization_summary.json "$OUT"/localization_route.png \
     "$OUT"/odometry_compare.json "$OUT"/odometry_compare.png "$SHARED/$(basename "$OUT")/" 2>/dev/null
  echo "Copied summary + route picture to the host folder:"
  echo "  ~/Documents/Projekte/g1pilot-main/localization_results/$(basename "$OUT")/"
}

cleanup() {
  echo; echo "Stopping..."
  [ -n "${BAG_PID:-}" ] && kill -INT "$BAG_PID" 2>/dev/null
  [ -n "${MON_PID:-}" ] && kill -INT "$MON_PID" 2>/dev/null && wait "$MON_PID" 2>/dev/null
  [ -n "${CMP_PID:-}" ] && kill -INT "$CMP_PID" 2>/dev/null && wait "$CMP_PID" 2>/dev/null
  [ -f "$OUT/odometry_compare.log" ] && sed -n '/TODAY vs MAPPING DAY/,$p' "$OUT/odometry_compare.log"
  # Stop only the process group we started (never a live FAST-LIO).
  [ -n "${LOC_PID:-}" ] && kill -INT -- "-$LOC_PID" 2>/dev/null
  sleep 3
  [ -n "${LOC_PID:-}" ] && kill -TERM -- "-$LOC_PID" 2>/dev/null
  copy_results
}
trap cleanup EXIT

OVERRIDE=/ros2_ws/install/fast_lio_localization/share/fast_lio_localization/config/localization.yaml
if [ "$DIAG" = 1 ]; then
  OVERRIDE="$OUT/diagnostic_overrides.yaml"
  cat > "$OVERRIDE" <<'YAML'
global_localization:
  ros__parameters:
    max_correction_xy: 0.5
    max_correction_z: 0.3
    max_correction_angle: 0.17453292519943295   # 10 degrees
    correction_alpha: 0.7
YAML
  echo "DIAGNOSTIC MODE: correction limits 0.5 m / 10 deg, smoothing 0.7 (test only)"
fi

echo "[1/4] Starting FAST-LIO + localization (log: $OUT/localization_launch.log)"
setsid ros2 launch "$HERE/localization_no_bridge.launch.py" \
  map:="$MAP" use_sim_time:=true start_fastlio:=true override_config:="$OVERRIDE" \
  start_localization:="$([ "$LOC" = 1 ] && echo true || echo false)" point_filter_num:="$PFN" \
  > "$OUT/localization_launch.log" 2>&1 &
LOC_PID=$!
sleep 20   # loading + downsampling the 1M-point map takes a moment
echo "      settings: point_filter_num=$PFN, localizer=$([ "$LOC" = 1 ] && echo on || echo OFF), rate=${RATE}x"
if ! kill -0 "$LOC_PID" 2>/dev/null || grep -q "Caught exception" "$OUT/localization_launch.log"; then
  echo "Localization did not start. Last log lines:"; tail -20 "$OUT/localization_launch.log"; exit 1
fi

if [ "$LOC" = 1 ]; then
  echo "[2/4] Starting monitor"
  python3 "$HERE/localization_monitor.py" --out "$OUT" --map-dir "$NAV2D" \
    --ros-args -p use_sim_time:=true > "$OUT/monitor.log" 2>&1 &
  MON_PID=$!
  sleep 3
else
  echo "[2/4] Localizer OFF - only FAST-LIO vs mapping day"
  : > "$OUT/monitor.log"
fi

echo "      + comparing today's FAST-LIO with the mapping-day odometry"
python3 "$HERE/odometry_compare.py" --out "$OUT" --map-dir "$NAV2D" \
  --ros-args -p use_sim_time:=true > "$OUT/odometry_compare.log" 2>&1 &
CMP_PID=$!

echo "[3/4] Playing Session 03 bag at ${RATE}x (/livox/lidar, /livox/imu, recorded /Odometry -> /recorded/Odometry)"
ros2 bag play "$BAG" --clock --rate "$RATE" --start-offset "$START_OFFSET" \
  --topics /livox/lidar /livox/imu /Odometry \
  --remap /Odometry:=/recorded/Odometry > "$OUT/bag_play.log" 2>&1 &
BAG_PID=$!
sleep 4

if [ "$LOC" = 1 ]; then
echo "[4/4] Initial pose: $INIT_POSE (retrying until the localizer confirms)"
SENT=0
for try in $(seq 1 24); do
  # shellcheck disable=SC2086
  if ros2 run fast_lio_localization publish_initial_pose.py $INIT_POSE \
       --ros-args -p use_sim_time:=true >> "$OUT/initial_pose.log" 2>&1; then
    sleep 2
    if grep -q "Initial pose received" "$OUT/localization_launch.log"; then
      echo "      localizer confirmed the initial pose (try $try)"
      SENT=1; break
    fi
  fi
  sleep 3
done
[ "$SENT" = 1 ] || echo "      WARNING: localizer did not confirm the initial pose - see $OUT/initial_pose.log"
else
  echo "[4/4] (no initial pose needed without localizer)"
fi

echo
echo "Running. Live progress (Ctrl+C to stop early):"
tail -f "$OUT/monitor.log" "$OUT/odometry_compare.log" --pid "$BAG_PID" &
wait "$BAG_PID"
sleep 5
kill -INT "$MON_PID" 2>/dev/null && wait "$MON_PID" 2>/dev/null
MON_PID=
echo
cat "$OUT/localization_summary.json" 2>/dev/null || echo "No summary - see $OUT/*.log"
echo
echo "Route picture: $OUT/localization_route.png"
