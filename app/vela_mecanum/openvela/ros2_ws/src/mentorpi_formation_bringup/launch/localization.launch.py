from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = Path(get_package_share_directory("mentorpi_formation_bringup"))
    default_amcl = str(package_share / "config" / "amcl.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument("namespace", default_value=""),
            DeclareLaunchArgument("map", description="Saved YAML occupancy map"),
            DeclareLaunchArgument("map_topic", default_value="map"),
            DeclareLaunchArgument("scan_topic", default_value="scan_raw"),
            DeclareLaunchArgument("map_frame", default_value="map"),
            DeclareLaunchArgument("odom_frame", default_value="odom"),
            DeclareLaunchArgument("base_frame", default_value="base_link"),
            DeclareLaunchArgument("amcl_params_file", default_value=default_amcl),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("start_map_server", default_value="true"),
            DeclareLaunchArgument("start_lifecycle_manager", default_value="true"),
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                namespace=LaunchConfiguration("namespace"),
                output="screen",
                condition=IfCondition(LaunchConfiguration("start_map_server")),
                parameters=[
                    {
                        "yaml_filename": LaunchConfiguration("map"),
                        "frame_id": LaunchConfiguration("map_frame"),
                        "topic_name": "map",
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                    }
                ],
            ),
            Node(
                package="nav2_amcl",
                executable="amcl",
                name="amcl",
                namespace=LaunchConfiguration("namespace"),
                output="screen",
                parameters=[
                    LaunchConfiguration("amcl_params_file"),
                    {
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                        "global_frame_id": LaunchConfiguration("map_frame"),
                        "odom_frame_id": LaunchConfiguration("odom_frame"),
                        "base_frame_id": LaunchConfiguration("base_frame"),
                        "scan_topic": LaunchConfiguration("scan_topic"),
                    },
                ],
                remappings=[
                    ("map", LaunchConfiguration("map_topic")),
                    ("scan", LaunchConfiguration("scan_topic")),
                ],
            ),
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_localization",
                namespace=LaunchConfiguration("namespace"),
                output="screen",
                condition=IfCondition(LaunchConfiguration("start_lifecycle_manager")),
                parameters=[
                    {
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                        "autostart": True,
                        "node_names": ["map_server", "amcl"],
                    }
                ],
            ),
        ]
    )
