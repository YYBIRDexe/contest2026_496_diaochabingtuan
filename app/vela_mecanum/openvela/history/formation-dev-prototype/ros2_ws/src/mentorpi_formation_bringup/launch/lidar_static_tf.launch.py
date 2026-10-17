from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("parent", default_value="base_link"),
            DeclareLaunchArgument("child", default_value="laser"),
            DeclareLaunchArgument("x", default_value="0.0"),
            DeclareLaunchArgument("y", default_value="0.0"),
            DeclareLaunchArgument("z", default_value="0.15"),
            DeclareLaunchArgument("yaw", default_value="0.0"),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="lidar_static_tf",
                output="screen",
                arguments=[
                    "--x", LaunchConfiguration("x"),
                    "--y", LaunchConfiguration("y"),
                    "--z", LaunchConfiguration("z"),
                    "--yaw", LaunchConfiguration("yaw"),
                    "--frame-id", LaunchConfiguration("parent"),
                    "--child-frame-id", LaunchConfiguration("child"),
                ],
            ),
        ]
    )

