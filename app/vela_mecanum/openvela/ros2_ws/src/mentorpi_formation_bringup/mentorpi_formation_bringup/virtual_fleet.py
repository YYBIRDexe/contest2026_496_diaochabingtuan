#!/usr/bin/env python3
"""Deterministic four-MentorPi ROS2 hardware/localization stand-in for QEMU."""

import json
import math
import time
from dataclasses import dataclass

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


ROBOT_NAMES = ("robot01", "robot02", "robot03", "robot04")
INITIAL_POSES = ((-1.4, -1.0), (-1.4, 1.0), (1.4, 1.0), (1.4, -1.0))


@dataclass
class RobotState:
    x: float
    y: float
    yaw: float = 0.0
    body_vx: float = 0.0
    body_vy: float = 0.0
    wz: float = 0.0
    command_time: float = 0.0


def _quaternion(yaw: float):
    from geometry_msgs.msg import Quaternion

    value = Quaternion()
    value.z = math.sin(yaw * 0.5)
    value.w = math.cos(yaw * 0.5)
    return value


class VirtualFleet(Node):
    def __init__(self):
        super().__init__("mentorpi_virtual_fleet")
        self.states = {
            name: RobotState(x, y, command_time=time.monotonic())
            for name, (x, y) in zip(ROBOT_NAMES, INITIAL_POSES)
        }
        self.odom_publishers = {name: self.create_publisher(Odometry, f"/{name}/odom", 10) for name in ROBOT_NAMES}
        self.pose_publishers = {
            name: self.create_publisher(PoseWithCovarianceStamped, f"/{name}/amcl_pose", 10)
            for name in ROBOT_NAMES
        }
        self.scan_publishers = {name: self.create_publisher(LaserScan, f"/{name}/scan_raw", 10) for name in ROBOT_NAMES}
        self.state_publisher = self.create_publisher(String, "/virtual_fleet/state", 10)
        self.command_subscriptions = [
            self.create_subscription(Twist, f"/{name}/controller/cmd_vel", self._command_callback(name), 10)
            for name in ROBOT_NAMES
        ]
        self.tf_broadcaster = TransformBroadcaster(self)
        self.static_broadcaster = StaticTransformBroadcaster(self)
        self._publish_static_transforms()
        self.previous_time = time.monotonic()
        self.create_timer(0.05, self._tick)
        self.get_logger().info("four virtual MentorPi M1 mecanum robots are active")

    def _command_callback(self, name):
        def callback(message):
            state = self.states[name]
            state.body_vx = max(-0.65, min(0.65, float(message.linear.x)))
            state.body_vy = max(-0.65, min(0.65, float(message.linear.y)))
            state.wz = max(-1.5, min(1.5, float(message.angular.z)))
            state.command_time = time.monotonic()

        return callback

    def _publish_static_transforms(self):
        stamp = self.get_clock().now().to_msg()
        transforms = []
        for name in ROBOT_NAMES:
            map_to_odom = TransformStamped()
            map_to_odom.header.stamp = stamp
            map_to_odom.header.frame_id = "map"
            map_to_odom.child_frame_id = f"{name}/odom"
            map_to_odom.transform.rotation.w = 1.0
            transforms.append(map_to_odom)

            base_to_laser = TransformStamped()
            base_to_laser.header.stamp = stamp
            base_to_laser.header.frame_id = f"{name}/base_link"
            base_to_laser.child_frame_id = f"{name}/laser"
            base_to_laser.transform.translation.z = 0.15
            base_to_laser.transform.rotation.w = 1.0
            transforms.append(base_to_laser)
        self.static_broadcaster.sendTransform(transforms)

    def _tick(self):
        now_mono = time.monotonic()
        dt = min(0.1, max(0.0, now_mono - self.previous_time))
        self.previous_time = now_mono
        stamp = self.get_clock().now().to_msg()
        dynamic_transforms = []
        snapshot = {}
        for name, state in self.states.items():
            if now_mono - state.command_time > 0.5:
                state.body_vx = state.body_vy = state.wz = 0.0
            cosine, sine = math.cos(state.yaw), math.sin(state.yaw)
            state.x += (cosine * state.body_vx - sine * state.body_vy) * dt
            state.y += (sine * state.body_vx + cosine * state.body_vy) * dt
            state.yaw = math.atan2(math.sin(state.yaw + state.wz * dt), math.cos(state.yaw + state.wz * dt))
            rotation = _quaternion(state.yaw)

            odom = Odometry()
            odom.header.stamp = stamp
            odom.header.frame_id = f"{name}/odom"
            odom.child_frame_id = f"{name}/base_link"
            odom.pose.pose.position.x = state.x
            odom.pose.pose.position.y = state.y
            odom.pose.pose.orientation = rotation
            odom.twist.twist.linear.x = state.body_vx
            odom.twist.twist.linear.y = state.body_vy
            odom.twist.twist.angular.z = state.wz
            self.odom_publishers[name].publish(odom)

            pose = PoseWithCovarianceStamped()
            pose.header.stamp = stamp
            pose.header.frame_id = "map"
            pose.pose.pose.position.x = state.x
            pose.pose.pose.position.y = state.y
            pose.pose.pose.orientation = rotation
            pose.pose.covariance[0] = 0.01
            pose.pose.covariance[7] = 0.01
            pose.pose.covariance[35] = 0.01
            self.pose_publishers[name].publish(pose)

            scan = LaserScan()
            scan.header.stamp = stamp
            scan.header.frame_id = f"{name}/laser"
            scan.angle_min = -math.pi
            scan.angle_max = math.pi
            scan.angle_increment = math.pi / 36.0
            scan.time_increment = 0.0
            scan.scan_time = 0.05
            scan.range_min = 0.05
            scan.range_max = 8.0
            scan.ranges = [3.0] * 73
            self.scan_publishers[name].publish(scan)

            transform = TransformStamped()
            transform.header.stamp = stamp
            transform.header.frame_id = f"{name}/odom"
            transform.child_frame_id = f"{name}/base_link"
            transform.transform.translation.x = state.x
            transform.transform.translation.y = state.y
            transform.transform.rotation = rotation
            dynamic_transforms.append(transform)
            snapshot[name] = {"x": round(state.x, 6), "y": round(state.y, 6), "yaw": round(state.yaw, 6)}
        self.tf_broadcaster.sendTransform(dynamic_transforms)
        message = String()
        message.data = json.dumps(snapshot, separators=(",", ":"))
        self.state_publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = VirtualFleet()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
