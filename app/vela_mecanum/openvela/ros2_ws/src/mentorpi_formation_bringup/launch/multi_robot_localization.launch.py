from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


ROBOT_IDS = ("robot01", "robot02", "robot03", "robot04")


def generate_launch_description():
    package_share = Path(get_package_share_directory("mentorpi_formation_bringup"))
    localization_launch = str(package_share / "launch" / "localization.launch.py")
    default_amcl = str(package_share / "config" / "amcl.yaml")
    includes = []
    lifecycle_nodes = ["map_server"]
    for robot_id in ROBOT_IDS:
        includes.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(localization_launch),
                launch_arguments={
                    "namespace": robot_id,
                    "map": LaunchConfiguration("map"),
                    "map_topic": "/map",
                    "scan_topic": "scan_raw",
                    "map_frame": "map",
                    "odom_frame": f"{robot_id}/odom",
                    "base_frame": f"{robot_id}/base_link",
                    "amcl_params_file": LaunchConfiguration("amcl_params_file"),
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                    "start_map_server": "false",
                    "start_lifecycle_manager": "false",
                }.items(),
            )
        )
        # A lifecycle manager in the same namespace as AMCL avoids the bond
        # lookup ambiguity seen when one global manager addresses namespaced
        # nodes. The map server remains globally managed below.
        includes.append(
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_localization",
                namespace=robot_id,
                output="screen",
                parameters=[
                    {
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                        "autostart": True,
                        "node_names": ["amcl"],
                    }
                ],
            )
        )
    return LaunchDescription(
        [
            DeclareLaunchArgument("map", description="One shared saved YAML occupancy map"),
            DeclareLaunchArgument("amcl_params_file", default_value=default_amcl),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                output="screen",
                parameters=[
                    {
                        "yaml_filename": LaunchConfiguration("map"),
                        "frame_id": "map",
                        "topic_name": "map",
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                    }
                ],
            ),
            *includes,
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_multi_localization",
                output="screen",
                parameters=[
                    {
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                        "autostart": True,
                        "node_names": lifecycle_nodes,
                    }
                ],
            ),
        ]
    )
