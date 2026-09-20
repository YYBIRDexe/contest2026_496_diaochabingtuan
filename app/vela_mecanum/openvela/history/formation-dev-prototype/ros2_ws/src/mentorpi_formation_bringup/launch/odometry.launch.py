"""Laser odometry as the vendor stacks it, fed a scan rf2o can actually use.

The vendor launch file (``controller/launch/rf2o_laser_odometry.launch.py``)
points rf2o straight at ``/scan_raw``.  That only works for a scan whose
declared angles are symmetric about the frame x axis; this car's sclidar driver
publishes ``angle_min = 0`` instead, which negated rf2o's ``linear.x``/``.y``.
See ``scan_symmetric`` for the measurements behind that.  Everything else here
keeps the vendor parameters unchanged.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("scan_topic", default_value="/scan_raw"),
            DeclareLaunchArgument("symmetric_scan_topic", default_value="/scan_symmetric"),
            DeclareLaunchArgument("odom_topic", default_value="/odom_rf2o"),
            DeclareLaunchArgument("base_frame", default_value="base_footprint"),
            DeclareLaunchArgument("odom_frame", default_value="odom"),
            Node(
                package="mentorpi_formation_bringup",
                executable="scan_symmetric",
                name="scan_symmetric",
                output="screen",
                parameters=[
                    {
                        "input_topic": LaunchConfiguration("scan_topic"),
                        "output_topic": LaunchConfiguration("symmetric_scan_topic"),
                    }
                ],
            ),
            Node(
                package="rf2o_laser_odometry",
                executable="rf2o_laser_odometry_node",
                name="rf2o_laser_odometry",
                output="screen",
                parameters=[
                    {
                        "laser_scan_topic": LaunchConfiguration("symmetric_scan_topic"),
                        "odom_topic": LaunchConfiguration("odom_topic"),
                        "publish_tf": False,
                        "base_frame_id": LaunchConfiguration("base_frame"),
                        "odom_frame_id": LaunchConfiguration("odom_frame"),
                        "init_pose_from_topic": "",
                        "freq": 10.0,
                    }
                ],
                arguments=["--ros-args", "--log-level", "WARN"],
            ),
        ]
    )
