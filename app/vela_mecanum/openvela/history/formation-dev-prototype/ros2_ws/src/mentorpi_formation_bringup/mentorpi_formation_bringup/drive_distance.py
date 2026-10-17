from __future__ import annotations

import argparse
import json
import math
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.duration import Duration
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformException, TransformListener

from .lidar_guard import clearance_speed_scale, directional_clearance
from .motion_math import normalize_angle, quaternion_yaw, validate_motion

# slam_toolbox stamps map -> odom slightly ahead of the receiver clock, so a
# small negative age still means a live transform instead of a stale one.
SLAM_FUTURE_TOLERANCE_S = 0.5
SLAM_STALE_TOLERANCE_S = 0.5


def stamp_seconds(stamp: object) -> float:
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def main() -> int:
    parser = argparse.ArgumentParser(description="Measured-lidar straight-line mission")
    parser.add_argument("--distance", type=float, default=1.0)
    parser.add_argument("--max-speed", type=float, default=0.10)
    parser.add_argument("--timeout", type=float, default=75.0)
    parser.add_argument("--tolerance", type=float, default=0.04)
    args, ros_args = parser.parse_known_args()
    if not 0.0 <= args.distance <= 3.0:
        raise SystemExit("distance must be between 0 and 3 m")
    if not 0.02 <= args.max_speed <= 0.10:
        raise SystemExit("max-speed must be between 0.02 and 0.10 m/s")

    rclpy.init(args=ros_args)
    node = rclpy.create_node("mentorpi_drive_distance")
    publisher = node.create_publisher(Twist, "/controller/cmd_vel", 10)
    scan_state: dict[str, object] = {}
    rf_state: dict[str, object] = {}
    buffer = Buffer(cache_time=Duration(seconds=10.0))
    listener = TransformListener(buffer, node)

    def receive_scan(message: LaserScan) -> None:
        scan_state.update(message=message, received=time.monotonic())

    def receive_rf(message: Odometry) -> None:
        rf_state.update(message=message, received=time.monotonic())

    scan_sub = node.create_subscription(LaserScan, "/scan_raw", receive_scan, qos_profile_sensor_data)
    rf_sub = node.create_subscription(Odometry, "/odom_rf2o", receive_rf, qos_profile_sensor_data)

    def stop() -> None:
        for _ in range(12):
            publisher.publish(Twist())
            rclpy.spin_once(node, timeout_sec=0.025)

    def rf_pose() -> tuple[float, float, float]:
        message = rf_state["message"]
        assert isinstance(message, Odometry)
        if message.header.frame_id.strip("/") != "odom" or message.child_frame_id.strip("/") != "base_footprint":
            raise RuntimeError("RF2O frame mismatch")
        p, q = message.pose.pose.position, message.pose.pose.orientation
        return float(p.x), float(p.y), quaternion_yaw(q.z, q.w)

    def map_pose() -> tuple[float, float, float]:
        correction = buffer.lookup_transform("map", "odom", Time())
        transform = buffer.lookup_transform("map", "base_footprint", Time())
        now = stamp_seconds(node.get_clock().now().to_msg())
        for tf in (correction, transform):
            age = now - stamp_seconds(tf.header.stamp)
            if not -SLAM_FUTURE_TOLERANCE_S <= age <= SLAM_STALE_TOLERANCE_S:
                raise RuntimeError(f"SLAM transform stale/future by {age:.3f}s")
        p, q = transform.transform.translation, transform.transform.rotation
        return float(p.x), float(p.y), quaternion_yaw(q.z, q.w)

    result = {"status": "aborted", "distance_requested_m": args.distance}
    started = time.monotonic()
    try:
        ready_until = time.monotonic() + 15.0
        start_rf = start_map = None
        last_reason = "no readiness sample yet"
        while time.monotonic() < ready_until:
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.monotonic() - float(scan_state.get("received", 0)) > 0.5:
                last_reason = "no fresh /scan_raw"
                continue
            if time.monotonic() - float(rf_state.get("received", 0)) > 0.5:
                last_reason = "no fresh /odom_rf2o"
                continue
            try:
                start_rf, start_map = rf_pose(), map_pose()
                break
            except (RuntimeError, TransformException) as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
                continue
        if start_rf is None or start_map is None:
            raise RuntimeError(
                f"fresh scan, RF2O and SLAM transforms required ({last_reason})")

        scan = scan_state["message"]
        assert isinstance(scan, LaserScan)
        initial_clearance = directional_clearance(
            scan.ranges, scan.angle_min, scan.angle_increment,
            scan.range_min, scan.range_max, 0.0, math.radians(25))
        if initial_clearance is None or initial_clearance < args.distance + 0.45:
            raise RuntimeError(f"front clearance {initial_clearance!r} m insufficient")
        if args.distance <= args.tolerance:
            result.update(status="completed", travelled_m=0.0)
        else:
            previous_rf, previous_map = start_rf, start_map
            previous_progress = 0.0
            motion_started = last_report = time.monotonic()
            while True:
                rclpy.spin_once(node, timeout_sec=0.04)
                now = time.monotonic()
                if now - motion_started > args.timeout:
                    raise RuntimeError("mission timeout")
                if now - float(scan_state.get("received", 0)) > 0.5:
                    raise RuntimeError("lidar stale")
                if now - float(rf_state.get("received", 0)) > 0.5:
                    raise RuntimeError("RF2O stale")
                rf, mapped = rf_pose(), map_pose()
                if math.hypot(rf[0] - previous_rf[0], rf[1] - previous_rf[1]) > 0.15:
                    raise RuntimeError("RF2O position jump")
                if math.hypot(mapped[0] - previous_map[0], mapped[1] - previous_map[1]) > 0.12:
                    raise RuntimeError("SLAM position jump")
                if abs(normalize_angle(rf[2] - previous_rf[2])) > 0.12:
                    raise RuntimeError("RF2O yaw jump")
                if abs(normalize_angle(mapped[2] - previous_map[2])) > 0.12:
                    raise RuntimeError("SLAM yaw jump")
                previous_rf, previous_map = rf, mapped
                try:
                    progress, map_progress, lateral = validate_motion(start_rf, start_map, rf, mapped)
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
                if progress - previous_progress > 0.15:
                    raise RuntimeError("progress jumped")
                previous_progress = progress
                remaining = args.distance - progress
                if remaining <= args.tolerance and abs(args.distance - map_progress) <= 0.12:
                    result.update(status="completed", travelled_m=progress,
                                  map_progress_m=map_progress, elapsed_s=now - motion_started)
                    break
                scan = scan_state["message"]
                assert isinstance(scan, LaserScan)
                clearance = directional_clearance(
                    scan.ranges, scan.angle_min, scan.angle_increment,
                    scan.range_min, scan.range_max, 0.0, math.radians(30))
                if clearance is None:
                    raise RuntimeError("invalid front lidar sector")
                scale = clearance_speed_scale(clearance, 0.45, 0.90)
                if scale < 0.15:
                    raise RuntimeError(f"obstacle stop at {clearance:.3f} m")
                command = Twist()
                command.linear.x = min(args.max_speed, max(0.025, 0.4 * remaining)) * scale
                command.linear.y = max(-0.02, min(0.02, -0.4 * lateral)) * scale
                # Mecanum slip correction uses lateral translation only; never
                # rotate autonomously before wheels-up yaw validation.
                command.angular.z = 0.0
                publisher.publish(command)
                if now - last_report >= 1.0:
                    node.get_logger().info(
                        f"RF2O={progress:.3f} SLAM={map_progress:.3f} lateral={lateral:.3f} "
                        f"yaw={normalize_angle(rf[2]-start_rf[2]):.3f} "
                        f"clearance={clearance:.3f} cmd_x={command.linear.x:.3f}")
                    last_report = now
    except Exception as exc:
        result.update(status="aborted", reason=str(exc))
        node.get_logger().error(str(exc))
    finally:
        stop()
        result["total_elapsed_s"] = time.monotonic() - started
        print(json.dumps(result, separators=(",", ":")), flush=True)
        del scan_sub, rf_sub, listener
        node.destroy_node()
        rclpy.shutdown()
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
