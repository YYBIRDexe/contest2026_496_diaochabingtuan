from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = Path(get_package_share_directory("mentorpi_formation_bringup"))
    default_params = str(package_share / "config" / "slam_toolbox_mapping.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument("namespace", default_value=""),
            DeclareLaunchArgument("scan_topic", default_value="scan_raw"),
            DeclareLaunchArgument("map_frame", default_value="map"),
            DeclareLaunchArgument("odom_frame", default_value="odom"),
            DeclareLaunchArgument("base_frame", default_value="base_link"),
            DeclareLaunchArgument("slam_params_file", default_value=default_params),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="slam_toolbox",
                namespace=LaunchConfiguration("namespace"),
                output="screen",
                parameters=[
                    LaunchConfiguration("slam_params_file"),
                    {
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                        "map_frame": LaunchConfiguration("map_frame"),
                        "odom_frame": LaunchConfiguration("odom_frame"),
                        "base_frame": LaunchConfiguration("base_frame"),
                        "scan_topic": LaunchConfiguration("scan_topic"),
                    },
                ],
                remappings=[("scan", LaunchConfiguration("scan_topic"))],
            ),
        ]
    )
