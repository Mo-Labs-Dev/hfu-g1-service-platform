import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():
    cfg=os.path.join(get_package_share_directory('g1_velocity_bridge'),'config','bridge.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('dry_run',default_value='true'),
        DeclareLaunchArgument('prepare_walkrun_on_enable',default_value='false'),
        DeclareLaunchArgument('auto_enable_motion',default_value='false'),
        DeclareLaunchArgument('input_topic',default_value='/cmd_vel_preview'),
        DeclareLaunchArgument('yaw_sign',default_value=os.environ.get('G1_YAW_SIGN','1.0')),
        Node(package='g1_velocity_bridge',executable='nav_velocity_bridge',output='screen',
             additional_env={'RMW_IMPLEMENTATION':'rmw_fastrtps_cpp'},
             parameters=[cfg,{'dry_run':LaunchConfiguration('dry_run'),
                             'input_topic':LaunchConfiguration('input_topic'),
                             'yaw_sign':ParameterValue(LaunchConfiguration('yaw_sign'),value_type=float),
                             'auto_enable_motion':LaunchConfiguration('auto_enable_motion'),
                             'prepare_walkrun_on_enable':LaunchConfiguration('prepare_walkrun_on_enable')}]),
    ])
