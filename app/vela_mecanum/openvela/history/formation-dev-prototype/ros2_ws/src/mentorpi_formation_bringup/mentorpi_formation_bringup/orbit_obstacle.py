from __future__ import annotations

import argparse
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

from .lidar_guard import clearance_speed_scale, directional_clearance
from .motion_math import quaternion_yaw
from .orbit_math import (
    normalize_angle,
    orbit_command,
    orbits_completed,
    tracked_obstacle,
    unwrap_yaw_step,
)

# The guards below are the only reason the car is allowed to move at all: a
# fresh scan, fresh laser odometry, and a contact that stays inside a sane
# envelope.  Any of them failing stops the wheels and reports a fault.
STOP_DISTANCE_M = 0.45
SLOW_DISTANCE_M = 0.90
MIN_SURROUND_CLEARANCE_M = 0.30
YAW_JUMP_LIMIT_RAD = 0.12
SCAN_TIMEOUT_S = 0.5
ODOM_TIMEOUT_S = 0.5
CONTACT_LOSS_TIMEOUT_S = 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lidar-hold orbit around one obstacle")
    parser.add_argument("--target-range", type=float, default=0.70)
    parser.add_argument("--target-bearing-deg", type=float, default=90.0)
    parser.add_argument("--turns", type=float, default=1.0)
    parser.add_argument("--max-speed", type=float, default=0.08)
    parser.add_argument("--max-lateral", type=float, default=0.05)
    parser.add_argument("--max-yaw-rate", type=float, default=0.40)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--acquire-half-angle-deg", type=float, default=75.0)
    parser.add_argument("--track-half-angle-deg", type=float, default=45.0)
    parser.add_argument("--min-range", type=float, default=0.35)
    parser.add_argument("--max-track-range", type=float, default=2.5)
    parser.add_argument(
        "--heading-mode",
        choices=("rotating", "fixed"),
        default="rotating",
        help=(
            "rotating drives forward and turns the heading to hold the contact on "
            "one side; fixed keeps the heading and orbits with translation alone"
        ),
    )
    parser.add_argument("--heading-gain", type=float, default=0.8)
    parser.add_argument(
        "--observe-only",
        action="store_true",
        help="track the contact and report it without ever publishing velocity",
    )
    args, ros_args = parser.parse_known_args()
    if not 0.05 <= args.max_speed <= 0.10:
        raise SystemExit("max-speed must be between 0.05 and 0.10 m/s")
    if not 0.20 <= args.target_range <= 1.50:
        raise SystemExit("target-range must be between 0.20 and 1.50 m")
    if args.turns <= 0.0 and not args.observe_only:
        raise SystemExit("turns must be positive")
    if abs(math.sin(math.radians(args.target_bearing_deg))) < 0.5:
        raise SystemExit(
            "target-bearing-deg must stay near +/-90 degrees: an orbit holds the "
            "contact out to one side, not ahead of or behind the car"
        )

    rclpy.init(args=ros_args)
    node = rclpy.create_node("mentorpi_orbit_obstacle")
    publisher = node.create_publisher(Twist, "/controller/cmd_vel", 10)
    scan_state: dict[str, object] = {}
    rf_state: dict[str, object] = {}

    def receive_scan(message: LaserScan) -> None:
        scan_state.update(message=message, received=time.monotonic())

    def receive_rf(message: Odometry) -> None:
        rf_state.update(message=message, received=time.monotonic())

    scan_sub = node.create_subscription(LaserScan, "/scan_raw", receive_scan, qos_profile_sensor_data)
    rf_sub = node.create_subscription(Odometry, "/odom_rf2o", receive_rf, qos_profile_sensor_data)

    def stop() -> None:
        if args.observe_only:
            return
        for _ in range(12):
            publisher.publish(Twist())
            rclpy.spin_once(node, timeout_sec=0.025)

    def rf_yaw() -> float:
        message = rf_state["message"]
        assert isinstance(message, Odometry)
        if message.header.frame_id.strip("/") != "odom" or message.child_frame_id.strip("/") != "base_footprint":
            raise RuntimeError("RF2O frame mismatch")
        quaternion = message.pose.pose.orientation
        return quaternion_yaw(quaternion.z, quaternion.w)

    def contact_from(
        scan: LaserScan,
        half_angle_deg: float,
        reference: float | None,
        preferred_bearing_rad: float,
    ) -> tuple[float, float] | None:
        return tracked_obstacle(
            scan.ranges,
            scan.angle_min,
            scan.angle_increment,
            scan.range_min,
            scan.range_max,
            preferred_bearing_rad,
            math.radians(half_angle_deg),
            reference_range_m=reference,
        )

    target_bearing = math.radians(args.target_bearing_deg)
    result: dict[str, object] = {
        "status": "aborted",
        "turns_requested": args.turns,
        "target_range_m": args.target_range,
    }
    started = time.monotonic()
    try:
        ready_until = time.monotonic() + 15.0
        contact = None
        last_reason = "no readiness sample yet"
        while time.monotonic() < ready_until:
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.monotonic() - float(scan_state.get("received", 0)) > SCAN_TIMEOUT_S:
                last_reason = "no fresh /scan_raw"
                continue
            if time.monotonic() - float(rf_state.get("received", 0)) > ODOM_TIMEOUT_S:
                last_reason = "no fresh /odom_rf2o"
                continue
            scan = scan_state["message"]
            assert isinstance(scan, LaserScan)
            contact = contact_from(scan, args.acquire_half_angle_deg, None, target_bearing)
            if contact is None:
                last_reason = "no obstacle inside the acquisition sector"
                continue
            break
        if contact is None:
            raise RuntimeError(f"fresh scan, RF2O and a visible obstacle required ({last_reason})")
        followed_range, followed_bearing = contact
        if followed_range < args.min_range or followed_range > args.max_track_range:
            raise RuntimeError(f"orbit contact acquired out of envelope at {followed_range:.3f} m")
        result.update(
            acquired_range_m=followed_range,
            acquired_bearing_deg=math.degrees(followed_bearing),
        )
        node.get_logger().info(
            f"orbit contact acquired: range={followed_range:.3f} m "
            f"bearing={math.degrees(followed_bearing):.1f} deg"
        )

        start_yaw = previous_yaw = rf_yaw()
        previous_orbit_angle = normalize_angle(previous_yaw + followed_bearing)
        previous_bearing = followed_bearing
        turned = 0.0
        lost_since: float | None = None
        motion_started = last_report = time.monotonic()
        while True:
            rclpy.spin_once(node, timeout_sec=0.04)
            now = time.monotonic()
            if now - motion_started > args.timeout:
                if not args.observe_only:
                    raise RuntimeError("orbit timeout")
                result.update(
                    status="completed",
                    turns_completed=orbits_completed(turned),
                    final_range_m=followed_range,
                    final_bearing_deg=math.degrees(followed_bearing),
                    elapsed_s=now - motion_started,
                )
                break
            if now - float(scan_state.get("received", 0)) > SCAN_TIMEOUT_S:
                raise RuntimeError("lidar stale")
            if now - float(rf_state.get("received", 0)) > ODOM_TIMEOUT_S:
                raise RuntimeError("RF2O stale")
            yaw = rf_yaw()
            if abs(normalize_angle(yaw - previous_yaw)) > YAW_JUMP_LIMIT_RAD:
                raise RuntimeError("RF2O yaw jump")
            previous_yaw = yaw

            scan = scan_state["message"]
            assert isinstance(scan, LaserScan)
            # A fixed heading sweeps the contact through the whole scan, so the
            # tracking sector follows the last bearing; the rotating mode keeps
            # the contact where the controller holds it.
            preferred_bearing = previous_bearing if args.heading_mode == "fixed" else target_bearing
            contact = contact_from(
                scan, args.track_half_angle_deg, followed_range, preferred_bearing
            )
            if contact is None:
                if lost_since is None:
                    lost_since = now
                if not args.observe_only:
                    publisher.publish(Twist())
                if now - lost_since > CONTACT_LOSS_TIMEOUT_S:
                    raise RuntimeError("orbit contact lost")
                continue
            lost_since = None
            followed_range, followed_bearing = contact
            previous_bearing = followed_bearing
            if followed_range < args.min_range:
                raise RuntimeError(f"orbit contact too close at {followed_range:.3f} m")
            if followed_range > args.max_track_range:
                raise RuntimeError(f"orbit contact out of range at {followed_range:.3f} m")
            # Travel around the contact is the heading plus the bearing to it. The
            # alignment turn at the start of a run changes both in opposite
            # directions and so contributes nothing, while one lap adds 2*pi.
            orbit_angle = normalize_angle(yaw + followed_bearing)
            turned = unwrap_yaw_step(turned, previous_orbit_angle, orbit_angle)
            previous_orbit_angle = orbit_angle
            completed = orbits_completed(turned)
            if not args.observe_only and completed >= args.turns:
                result.update(
                    status="completed",
                    turns_completed=completed,
                    final_range_m=followed_range,
                    final_bearing_deg=math.degrees(followed_bearing),
                    elapsed_s=now - motion_started,
                )
                break

            linear_x, linear_y, angular_z = orbit_command(
                followed_range,
                followed_bearing,
                args.target_range,
                target_bearing,
                args.max_speed,
                args.max_lateral,
                args.max_yaw_rate,
                mode="tangential" if args.heading_mode == "fixed" else "rotating",
                heading_error_rad=normalize_angle(yaw - start_yaw),
                heading_gain=args.heading_gain,
            )
            travel_direction = math.atan2(linear_y, linear_x)
            clearance = directional_clearance(
                scan.ranges,
                scan.angle_min,
                scan.angle_increment,
                scan.range_min,
                scan.range_max,
                travel_direction,
                math.radians(30.0),
            )
            if clearance is None:
                raise RuntimeError("invalid lidar sector in the travel direction")
            surrounding = directional_clearance(
                scan.ranges,
                scan.angle_min,
                scan.angle_increment,
                scan.range_min,
                scan.range_max,
                0.0,
                math.pi,
            )
            if surrounding is not None and surrounding < MIN_SURROUND_CLEARANCE_M:
                raise RuntimeError(f"surrounding clearance {surrounding:.3f} m is not enough to turn")
            scale = clearance_speed_scale(clearance, STOP_DISTANCE_M, SLOW_DISTANCE_M)
            if scale < 0.15:
                raise RuntimeError(f"obstacle stop at {clearance:.3f} m")
            command = Twist()
            if not args.observe_only:
                command.linear.x = linear_x * scale
                command.linear.y = linear_y * scale
                command.angular.z = angular_z
                publisher.publish(command)
            if now - last_report >= 1.0:
                node.get_logger().info(
                    f"range={followed_range:.3f} bearing={math.degrees(followed_bearing):.1f} "
                    f"turns={completed:.3f} vx={linear_x * scale:.3f} vy={linear_y * scale:.3f} "
                    f"wz={angular_z:.3f} clearance={clearance:.3f}"
                )
                last_report = now
    except Exception as exc:
        result.update(status="aborted", reason=str(exc))
        node.get_logger().error(str(exc))
    finally:
        stop()
        result["total_elapsed_s"] = time.monotonic() - started
        print(json.dumps(result, separators=(",", ":")), flush=True)
        del scan_sub, rf_sub
        node.destroy_node()
        rclpy.shutdown()
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
