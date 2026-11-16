"""
FAST-LIO + FAST_LIO_LOCALIZATION without the Unitree `lidar_pkg` bridge.

Same nodes and parameters as fast_lio_localization/localization_mid360.launch.py,
minus the lidar_pkg include (not installed here) and minus RViz.

    ros2 launch /ros2_ws/src/g1pilot/hfu_nav/localization_no_bridge.launch.py \
        map:=/path/map.pcd use_sim_time:=true start_fastlio:=true
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    share = get_package_share_directory("fast_lio_localization")
    fastlio = get_package_share_directory("fast_lio")
    use_sim_time = ParameterValue(LaunchConfiguration("use_sim_time"), value_type=bool)
    common = {k: LaunchConfiguration(k) for k in ("map_frame", "odom_frame", "body_frame", "odom_topic")}
    common["use_sim_time"] = use_sim_time

    defaults = dict(
        start_fastlio="true", use_sim_time="false",
        start_localization="true",
        # Mapping day used fast_lio mapping_mid360.launch.py with static_map:=true,
        # which sets point_filter_num = 1 (every LiDAR point). Same here.
        point_filter_num="1",
        map_frame="map", odom_frame="camera_init", body_frame="body",
        odom_topic="/Odometry", scan_topic="/cloud_registered",
        config=os.path.join(share, "config", "localization.yaml"),
        fastlio_config=os.path.join(fastlio, "config", "mid360.yaml"),
        # Optional extra YAML loaded AFTER config (test-only overrides).
        override_config=os.path.join(share, "config", "localization.yaml"),
    )
    args = [DeclareLaunchArgument("map", description="Absolute path to the PCD map")]
    args += [DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()]

    return LaunchDescription(args + [
        Node(
            package="fast_lio", executable="fastlio_mapping", name="laserMapping",
            condition=IfCondition(LaunchConfiguration("start_fastlio")), output="screen",
            parameters=[
                LaunchConfiguration("fastlio_config"),
                {
                    "use_sim_time": use_sim_time,
                    "pcd_save.pcd_save_en": False,   # never write a map during tests
                    "point_filter_num": ParameterValue(LaunchConfiguration("point_filter_num"), value_type=int),
                    "preprocess.lidar_type": ParameterValue(PythonExpression([
                        "1 if '", EnvironmentVariable("G1_SENSOR_BACKEND", default_value="dds"),
                        "' == 'livox' else 5"]), value_type=int),
                },
            ],
        ),
        Node(
            package="fast_lio_localization", executable="global_localization.py",
            name="global_localization", output="screen",
            condition=IfCondition(LaunchConfiguration("start_localization")),
            parameters=[
                LaunchConfiguration("config"), LaunchConfiguration("override_config"), common,
                {"map_path": ParameterValue(LaunchConfiguration("map"), value_type=str),
                 "scan_topic": LaunchConfiguration("scan_topic")},
            ],
        ),
        Node(
            package="fast_lio_localization", executable="transform_fusion.py",
            name="transform_fusion", output="screen", parameters=[common],
            condition=IfCondition(LaunchConfiguration("start_localization")),
        ),
    ])
