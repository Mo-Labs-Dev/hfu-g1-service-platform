#!/usr/bin/env bash
# =====================================================================
#  Live FAST-LIO for teach & repeat (inside g1pilot-dev).
#
#  IMPORTANT: start this ONLY when G1 stands on the HOME spot, facing the
#  marked direction. FAST-LIO's origin = where it starts = home.
#
#  Same settings as mapping day (point_filter_num 1, lidar_type 5), but
#  map saving is OFF and no localizer is started.
#
#  The Livox MID-360 driver must already be running and publishing
#  /livox/lidar + /livox/imu (start it the same way as on mapping day).
# =====================================================================
set +u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-1}
unset G1_SENSOR_BACKEND            # -> lidar_type 5 (PointCloud2), as on mapping day
source /opt/ros/humble/setup.bash
source /ros2_ws/install/setup.bash
HERE=$(cd "$(dirname "$0")/.." && pwd)

echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "Checking that the Livox driver publishes /livox/lidar ..."
if ! timeout 5 ros2 topic echo --once /livox/lidar --field header.frame_id >/dev/null 2>&1; then
  echo "No /livox/lidar data. Start the Livox MID-360 driver first (as on mapping day)."
  exit 1
fi
if pgrep -f fastlio_mapping >/dev/null; then
  echo "FAST-LIO is already running. Stop it first if you want a new origin (home)."
  exit 1
fi
echo "Starting FAST-LIO (no map saving). Make sure G1 is ON THE HOME SPOT."
exec ros2 launch "$HERE/localization_no_bridge.launch.py" \
  map:=/dev/null use_sim_time:=false start_fastlio:=true start_localization:=false \
  point_filter_num:=1
