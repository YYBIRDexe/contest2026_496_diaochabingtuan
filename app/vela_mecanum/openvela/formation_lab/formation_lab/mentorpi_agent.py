from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from .agent import AgentObservation, FormationMission, ROBOT_IDS, RobotFormationAgent
from .laplacian import topology_from_config
from .second_order import SecondOrderCommand, SecondOrderFormationAgent


def world_to_body(world_vx: float, world_vy: float, yaw_rad: float) -> tuple[float, float]:
    return (
        math.cos(yaw_rad) * world_vx + math.sin(yaw_rad) * world_vy,
        -math.sin(yaw_rad) * world_vx + math.cos(yaw_rad) * world_vy,
    )


def body_to_world(body_vx: float, body_vy: float, yaw_rad: float) -> tuple[float, float]:
    return (
        math.cos(yaw_rad) * body_vx - math.sin(yaw_rad) * body_vy,
        math.sin(yaw_rad) * body_vx + math.cos(yaw_rad) * body_vy,
    )


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _normalized_frame(frame_id: str) -> str:
    """Normalize ROS frame spelling without changing its semantic identity."""
    return str(frame_id).strip().lstrip("/")


def localization_covariance_ok(
    covariance: Any,
    max_xy_variance_m2: float,
    max_yaw_variance_rad2: float,
) -> bool:
    """Reject non-finite or high-uncertainty AMCL poses before motion."""
    try:
        values = [float(value) for value in covariance]
        checked = (values[0], values[7], values[35])
    except (IndexError, TypeError, ValueError):
        return False
    return (
        all(math.isfinite(value) and value >= 0.0 for value in checked)
        and checked[0] <= max_xy_variance_m2
        and checked[1] <= max_xy_variance_m2
        and checked[2] <= max_yaw_variance_rad2
    )


def _dry_run(robot_id: str) -> None:
    agent = RobotFormationAgent(robot_id)
    agent.accept_mission(FormationMission("dry-run", "square", 0.8))
    observations = {
        "Robot01": AgentObservation("Robot01", -1.4, -1.0),
        "Robot02": AgentObservation("Robot02", -1.4, 1.0),
        "Robot03": AgentObservation("Robot03", 1.4, 1.0),
        "Robot04": AgentObservation("Robot04", 1.4, -1.0),
    }
    own = observations[robot_id]
    command = agent.compute(own, (item for key, item in observations.items() if key != robot_id))
    body_vx, body_vy = world_to_body(command.world_vx, command.world_vy, own.yaw_rad)
    print(json.dumps({"robot_id": robot_id, "body_vx": body_vx, "body_vy": body_vy, "wz": command.wz, "safe": command.safe, "reason": command.reason}, indent=2))


def _run_ros(config: dict[str, Any], robot_id: str, ros_args: list[str]) -> None:
    try:
        import rclpy
        from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import LaserScan
        from std_msgs.msg import String
        from mentorpi_formation_bringup.lidar_guard import (
            clearance_speed_scale,
            directional_clearance,
        )
    except ImportError as exc:
        raise SystemExit("ROS 2 Python packages are not installed on this VM; use --dry-run") from exc
    if not config.get("hardware_output_enabled", False):
        raise SystemExit("hardware_output_enabled is false; verify topics and shared localization before enabling")

    rclpy.init(args=ros_args)
    node = rclpy.create_node(f"formation_agent_{robot_id.lower()}")
    limits = config.get("limits", {})
    control_mode = str(config.get("control_mode", "anchored"))
    topology = topology_from_config(config)

    def build_controller(mode: str) -> RobotFormationAgent:
        kwargs = {
            "max_linear_mps": float(limits.get("max_linear_mps", 0.65)),
            "max_angular_radps": float(limits.get("max_angular_radps", 1.5)),
            "arena_half_extent_m": float(limits.get("arena_half_extent_m", 3.0)),
            "min_distance_m": float(limits.get("min_distance_m", 0.25)),
            "topology": topology,
        }
        if mode == "second_order":
            return SecondOrderFormationAgent(robot_id, **kwargs)
        return RobotFormationAgent(robot_id, control_mode=mode, **kwargs)

    controller_ref: dict[str, RobotFormationAgent] = {"value": build_controller(control_mode)}
    poses: dict[str, tuple[float, float, float, bool, float]] = {}
    velocities: dict[str, tuple[float, float, float, float]] = {}
    scan_state: dict[str, Any] = {}
    timeout_s = float(config.get("peer_timeout_s", 0.7))
    odom_timeout_s = float(config.get("odom_timeout_s", 0.5))
    map_frame = _normalized_frame(config.get("shared_map_frame", "map"))
    max_xy_variance = float(config.get("max_xy_variance_m2", 0.25))
    max_yaw_variance = float(config.get("max_yaw_variance_rad2", 0.25))
    mapping = config["robots"]
    guard_config = config.get("lidar_guard", {})
    guard_enabled = bool(guard_config.get("enabled", True))
    scan_timeout_s = float(guard_config.get("scan_timeout_s", 0.5))
    stop_distance_m = float(guard_config.get("stop_distance_m", 0.4))
    slow_distance_m = float(guard_config.get("slow_distance_m", 0.8))
    sector_half_angle_rad = math.radians(float(guard_config.get("sector_half_angle_deg", 30.0)))
    rotation_stop_distance_m = float(guard_config.get("rotation_stop_distance_m", 0.3))
    publisher = node.create_publisher(Twist, str(mapping[robot_id]["cmd_vel_topic"]), 10)
    status_publisher = node.create_publisher(String, str(config["agent_status_topic"]), 10)

    def publish_status(safe: bool, reason: str, command: Any | None = None) -> None:
        message = String()
        message.data = json.dumps(
            {
                "robot_id": robot_id,
                "experiment_id": controller_ref["value"].mission.experiment_id if controller_ref["value"].mission else None,
                "control_mode": getattr(controller_ref["value"].mission, "control_mode", None),
                "safe": safe,
                "reason": reason,
                "target_x": command.target_x if command else None,
                "target_y": command.target_y if command else None,
                "timestamp_s": time.time(),
            },
            separators=(",", ":"),
        )
        status_publisher.publish(message)

    def mission_callback(message: Any) -> None:
        try:
            payload = json.loads(message.data)
            if not payload.get("enabled", False):
                controller_ref["value"].emergency_stop()
                return
            mode = str(payload.get("control_mode", control_mode))
            if mode != getattr(controller_ref["value"], "control_mode", None):
                controller_ref["value"] = build_controller(mode)
            controller_ref["value"].accept_mission(
                FormationMission(
                    experiment_id=str(payload["experiment_id"]),
                    formation=str(payload["formation"]),
                    spacing_m=float(payload["spacing_m"]),
                    center_x=float(payload.get("center_x", 0.0)),
                    center_y=float(payload.get("center_y", 0.0)),
                    heading_rad=float(payload.get("heading_rad", 0.0)),
                    control_mode=mode,
                )
            )
            node.get_logger().info(f"accepted mission {payload['experiment_id']}")
        except Exception as exc:
            controller_ref["value"].emergency_stop()
            node.get_logger().error(f"invalid mission; emergency stop: {exc}")

    node.create_subscription(String, str(config["mission_topic"]), mission_callback, 10)

    def make_pose_callback(observed_id: str):
        def callback(message: Any) -> None:
            pose = message.pose.pose
            yaw = _yaw_from_quaternion(pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w)
            frame_ok = _normalized_frame(message.header.frame_id) == map_frame
            covariance_ok = localization_covariance_ok(
                message.pose.covariance,
                max_xy_variance,
                max_yaw_variance,
            )
            finite_pose = all(math.isfinite(value) for value in (pose.position.x, pose.position.y, yaw))
            poses[observed_id] = (
                float(pose.position.x),
                float(pose.position.y),
                yaw,
                frame_ok and covariance_ok and finite_pose,
                time.monotonic(),
            )
        return callback

    def make_odom_callback(observed_id: str):
        def callback(message: Any) -> None:
            twist = message.twist.twist
            velocities[observed_id] = (
                float(twist.linear.x),
                float(twist.linear.y),
                float(twist.angular.z),
                time.monotonic(),
            )
        return callback

    pose_subscriptions = [
        node.create_subscription(
            PoseWithCovarianceStamped,
            str(mapping[observed_id]["pose_topic"]),
            make_pose_callback(observed_id),
            10,
        )
        for observed_id in ROBOT_IDS
    ]
    odom_subscriptions = [
        node.create_subscription(
            Odometry,
            str(mapping[observed_id]["odom_topic"]),
            make_odom_callback(observed_id),
            10,
        )
        for observed_id in ROBOT_IDS
    ]

    def scan_callback(message: Any) -> None:
        scan_state.update(
            ranges=tuple(message.ranges),
            angle_min=float(message.angle_min),
            angle_increment=float(message.angle_increment),
            range_min=float(message.range_min),
            range_max=float(message.range_max),
            received=time.monotonic(),
        )

    scan_subscription = None
    if guard_enabled:
        scan_topic = mapping[robot_id].get("scan_topic")
        if not scan_topic:
            raise SystemExit(f"lidar guard enabled but scan_topic missing for {robot_id}")
        scan_subscription = node.create_subscription(
            LaserScan,
            str(scan_topic),
            scan_callback,
            qos_profile_sensor_data,
        )

    def current_observation(observed_id: str, now: float, require_velocity: bool) -> AgentObservation | None:
        pose_entry = poses.get(observed_id)
        if not pose_entry or now - pose_entry[4] > timeout_s:
            return None
        x, y, yaw, localization_ok, _ = pose_entry
        velocity_entry = velocities.get(observed_id)
        velocity_fresh = bool(velocity_entry and now - velocity_entry[3] <= odom_timeout_s)
        if require_velocity and not velocity_fresh:
            return None
        body_vx, body_vy, wz = velocity_entry[:3] if velocity_fresh and velocity_entry else (0.0, 0.0, 0.0)
        world_vx, world_vy = body_to_world(body_vx, body_vy, yaw)
        return AgentObservation(
            observed_id,
            x,
            y,
            yaw,
            online=True,
            localization_ok=localization_ok,
            vx=world_vx,
            vy=world_vy,
            wz=wz,
        )

    def publish_control() -> None:
        if not pose_subscriptions or not odom_subscriptions:  # retain handles for this node's lifetime
            return
        now = time.monotonic()
        require_velocity = controller_ref["value"].control_mode == "second_order"
        own = current_observation(robot_id, now, require_velocity)
        if own is None:
            publisher.publish(Twist())
            publish_status(False, "local_state_stale")
            return
        peers = []
        for peer_id in ROBOT_IDS:
            if peer_id == robot_id:
                continue
            observation = current_observation(peer_id, now, require_velocity)
            if observation is None:
                peers.append(AgentObservation(peer_id, 0.0, 0.0, online=False))
            else:
                peers.append(observation)
        controller = controller_ref["value"]
        command = controller.compute(own, peers)
        if isinstance(command, SecondOrderCommand):
            # MentorPi's actuator interface is velocity-level.  Integrate the
            # local acceleration command for one control period before the
            # frame transform; no central process computes this for the car.
            dt = 1.0 / float(config.get("control_hz", 20.0))
            world_vx = own.vx + command.accel_x * dt
            world_vy = own.vy + command.accel_y * dt
            speed = math.hypot(world_vx, world_vy)
            max_speed = float(limits.get("max_linear_mps", 0.65))
            if speed > max_speed:
                scale = max_speed / speed
                world_vx, world_vy = world_vx * scale, world_vy * scale
            wz = own.wz + command.angular_accel * dt
            max_angular = float(limits.get("max_angular_radps", 1.5))
            wz = max(-max_angular, min(max_angular, wz))
        else:
            world_vx, world_vy, wz = command.world_vx, command.world_vy, command.wz
        body_vx, body_vy = world_to_body(world_vx, world_vy, own.yaw_rad)

        guard_reason: str | None = None
        if guard_enabled:
            scan_received = float(scan_state.get("received", 0.0))
            if now - scan_received > scan_timeout_s:
                publisher.publish(Twist())
                publish_status(False, "lidar_stale", command)
                return
            ranges = scan_state.get("ranges", ())
            linear_speed = math.hypot(body_vx, body_vy)
            if linear_speed > 1e-4:
                clearance = directional_clearance(
                    ranges,
                    float(scan_state["angle_min"]),
                    float(scan_state["angle_increment"]),
                    float(scan_state["range_min"]),
                    float(scan_state["range_max"]),
                    math.atan2(body_vy, body_vx),
                    sector_half_angle_rad,
                )
                if clearance is None:
                    publisher.publish(Twist())
                    publish_status(False, "lidar_no_valid_ranges", command)
                    return
                scale = clearance_speed_scale(clearance, stop_distance_m, slow_distance_m)
                if scale <= 0.0:
                    publisher.publish(Twist())
                    publish_status(False, "lidar_stop", command)
                    return
                body_vx *= scale
                body_vy *= scale
                if scale < 1.0:
                    guard_reason = "lidar_slow"
            elif abs(wz) > 1e-4:
                clearance = directional_clearance(
                    ranges,
                    float(scan_state["angle_min"]),
                    float(scan_state["angle_increment"]),
                    float(scan_state["range_min"]),
                    float(scan_state["range_max"]),
                    0.0,
                    math.pi,
                )
                if clearance is None or clearance <= rotation_stop_distance_m:
                    publisher.publish(Twist())
                    publish_status(False, "lidar_rotation_stop", command)
                    return
        output = Twist()
        output.linear.x, output.linear.y, output.angular.z = body_vx, body_vy, wz
        publisher.publish(output)
        publish_status(command.safe, guard_reason or command.reason, command)

    node.create_timer(1.0 / float(config.get("control_hz", 20.0)), publish_control)
    node.get_logger().warning(f"{robot_id} distributed formation control is ACTIVE")
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        # SIGINT/SIGTERM can invalidate the rclpy context before spin returns.
        # Treat that as a normal shutdown and let the finally block guard all
        # last-chance ROS publications.
        pass
    finally:
        if scan_subscription is not None:
            del scan_subscription
        if rclpy.ok():
            publisher.publish(Twist())
            publish_status(False, "agent_shutdown")
            rclpy.shutdown()
        node.destroy_node()


def main() -> None:
    parser = argparse.ArgumentParser(description="Per-car distributed formation controller for MentorPi")
    parser.add_argument("--robot-id", choices=ROBOT_IDS, required=True)
    parser.add_argument("--config", default="config/mentorpi.json")
    parser.add_argument("--dry-run", action="store_true")
    args, ros_args = parser.parse_known_args()
    if args.dry_run:
        _dry_run(args.robot_id)
        return
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    _run_ros(config, args.robot_id, ros_args)


if __name__ == "__main__":
    main()
