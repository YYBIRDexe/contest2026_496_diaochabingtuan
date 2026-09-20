#!/usr/bin/env python3
"""Republish a laser scan with the beam ordering range-flow odometry assumes.

``rf2o_laser_odometry`` never reads ``angle_min``.  ``CLaserOdometry2D::init``
derives the field of view from ``|angle_max - angle_min|`` only, and
``calculateRangeFlow`` then places beam ``u`` at ``-fovh/2 + u * fovh/(cols-1)``:
an implicit assumption that the scan is centred on the x axis of its frame and
that beam 0 sits at ``-fovh/2``.

The vendor sclidar driver publishes ``angle_min = 0`` with 0 ... 2*pi of
coverage instead, so every azimuth rf2o assumes is off by half a turn.  rf2o
then integrates the motion of the robot in a frame rotated by pi relative to
``base_footprint``: ``linear.x``/``linear.y`` come out negated while
``angular.z`` is preserved.  Measured on the car for one forward run:
``/odom_raw`` +0.147 m (wheel encoders, physically correct) against
``/odom_rf2o`` -0.147 m, while an in-place +0.30 rad/s command produced
``+0.5505 rad`` on the IMU, ``+0.7487 rad`` on wheel odometry and ``+0.5232 rad``
on rf2o - same sign, hence a pure rotation error and not a mirrored scan.

This node re-parameterises the scan so the assumption holds again: the beam
array is rotated by half a turn and the declared angles are shifted by the same
half turn.  That is a pure re-indexing - the set of (angle, range) pairs is
unchanged - so the scan the rest of the stack consumes on ``/scan_raw`` stays
as it is.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Sequence

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


def normalize_to_pi(angle: float) -> float:
    """Wrap ``angle`` into [-pi, pi), unlike atan2 which returns +pi at the seam."""
    return ((angle + math.pi) % (2.0 * math.pi)) - math.pi


def half_turn_scan(
    ranges: Sequence[float],
    intensities: Sequence[float],
    angle_min: float,
    angle_max: float,
) -> tuple[list[float], list[float], float, float]:
    """Return ``ranges`` rotated by half a turn with matching angle bounds."""
    count = len(ranges)
    if count < 4 or count % 2 != 0:
        raise ValueError(f"need an even beam count of at least 4, got {count}")
    half = count // 2
    rotated = list(ranges[half:]) + list(ranges[:half])
    rotated_intensities = list(intensities[half:]) + list(intensities[:half]) if intensities else []
    shifted_min = normalize_to_pi(angle_min + math.pi)
    return rotated, rotated_intensities, shifted_min, shifted_min + (angle_max - angle_min)


class ScanSymmetric(Node):
    """Publish ``input_topic`` on ``output_topic`` with rf2o-compatible beams."""

    def __init__(self) -> None:
        super().__init__("scan_symmetric")
        self.declare_parameter("input_topic", "/scan_raw")
        self.declare_parameter("output_topic", "/scan_symmetric")
        input_topic = self.get_parameter("input_topic").get_parameter_value().string_value
        output_topic = self.get_parameter("output_topic").get_parameter_value().string_value
        self._publisher = self.create_publisher(LaserScan, output_topic, qos_profile_sensor_data)
        self._subscription = self.create_subscription(
            LaserScan, input_topic, self.publish_symmetric, qos_profile_sensor_data
        )
        self._skipped = 0
        self._reported = False
        self.get_logger().info(f"{input_topic} -> {output_topic}: half-turn re-parameterisation")

    def publish_symmetric(self, message: LaserScan) -> None:
        try:
            ranges, intensities, angle_min, angle_max = half_turn_scan(
                message.ranges, message.intensities, message.angle_min, message.angle_max
            )
        except ValueError as error:
            self._skipped += 1
            if self._skipped == 1 or self._skipped % 100 == 0:
                self.get_logger().warn(f"scan passed through unchanged: {error} ({self._skipped} so far)")
            self._publisher.publish(message)
            return
        symmetric = LaserScan()
        symmetric.header = message.header
        symmetric.angle_min = angle_min
        symmetric.angle_max = angle_max
        symmetric.angle_increment = message.angle_increment
        symmetric.time_increment = message.time_increment
        symmetric.scan_time = message.scan_time
        symmetric.range_min = message.range_min
        symmetric.range_max = message.range_max
        symmetric.ranges = ranges
        symmetric.intensities = intensities
        self._publisher.publish(symmetric)
        if not self._reported:
            self._reported = True
            self.get_logger().info(
                f"first scan: {len(ranges)} beams, angle_min "
                f"{message.angle_min:.4f} -> {angle_min:.4f} rad"
            )


def main() -> int:
    rclpy.init()
    node = ScanSymmetric()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
