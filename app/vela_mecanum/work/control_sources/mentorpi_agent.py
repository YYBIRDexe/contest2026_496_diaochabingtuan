from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent import AgentObservation, FormationMission, ROBOT_IDS, RobotFormationAgent, arena_bounds_from_config, point_in_arena
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


def ros_stamp_unix_s(stamp: Any) -> float:
    """Return a ROS header timestamp, or NaN for a missing/invalid stamp."""
    try:
        sec = int(stamp.sec)
        nanosec = int(stamp.nanosec)
        if sec <= 0 or not 0 <= nanosec < 1_000_000_000:
            return math.nan
        return sec + nanosec * 1e-9
    except (AttributeError, TypeError, ValueError, OverflowError):
        return math.nan


def message_stamp_fresh(
    stamp_unix_s: float,
    max_age_s: float,
    now_unix_s: float | None = None,
    future_tolerance_s: float = 0.2,
) -> bool:
    """Require a recent measurement timestamp as well as recent delivery."""
    now = time.time() if now_unix_s is None else now_unix_s
    age = now - stamp_unix_s
    return math.isfinite(age) and -future_tolerance_s <= age <= max_age_s


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


@dataclass
class PreparedMission:
    mission: FormationMission
    controller: RobotFormationAgent
    fingerprint: str
    deadline_unix_s: float
    prepare_expires_monotonic: float


def mission_from_payload(payload: dict[str, Any], default_control_mode: str) -> FormationMission:
    """Build the immutable controller mission used by both prepare and commit."""
    return FormationMission(
        experiment_id=str(payload["experiment_id"]),
        formation=str(payload["formation"]),
        spacing_m=float(payload["spacing_m"]),
        center_x=float(payload.get("center_x", 0.0)),
        center_y=float(payload.get("center_y", 0.0)),
        heading_rad=float(payload.get("heading_rad", 0.0)),
        control_mode=str(payload.get("control_mode", default_control_mode)),
    )


def mission_fingerprint(mission: FormationMission, deadline_unix_s: float) -> str:
    """Canonical value checked again at commit so a prepared task cannot mutate."""
    return json.dumps(
        {
            "experiment_id": mission.experiment_id,
            "formation": mission.formation,
            "spacing_m": mission.spacing_m,
            "center_x": mission.center_x,
            "center_y": mission.center_y,
            "heading_rad": mission.heading_rad,
            "control_mode": mission.control_mode,
            "deadline_unix_s": deadline_unix_s,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def load_retired_experiment_ids(path: Path) -> set[str]:
    """Load IDs that must never be restarted after an agent process restart."""
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("retired_experiment_ids", [])
    if not isinstance(values, list):
        raise ValueError("retired_experiment_ids must be a list")
    return {str(value) for value in values if str(value)}


def persist_retired_experiment_ids(path: Path, values: set[str], keep: int = 256) -> None:
    """Atomically persist consumed IDs; failure is handled as a fail-closed condition."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(values)[-max(1, int(keep)) :]
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps({"retired_experiment_ids": ordered}, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def actuator_twist(
    command: Any,
    own: AgentObservation,
    dt: float,
    max_linear_mps: float,
    max_angular_radps: float,
) -> tuple[float, float, float]:
    """Map a controller command to the body twist the MentorPi chassis receives.

    The chassis interface is velocity level.  A second-order command carries an
    acceleration and is integrated here for one control period; a first-order
    command already carries a velocity.

    An unsafe command must reach the chassis as zero *velocity*.  In
    second-order mode the controller reports an unsafe state as zero
    acceleration, and integrating that would let a moving car coast instead of
    stopping, so the safety return is handled before the integration.
    """

    if not command.safe:
        return 0.0, 0.0, 0.0
    if isinstance(command, SecondOrderCommand):
        world_vx = own.vx + command.accel_x * dt
        world_vy = own.vy + command.accel_y * dt
        speed = math.hypot(world_vx, world_vy)
        if speed > max_linear_mps:
            world_vx = world_vx * max_linear_mps / speed
            world_vy = world_vy * max_linear_mps / speed
        wz = own.wz + command.angular_accel * dt
        wz = max(-max_angular_radps, min(max_angular_radps, wz))
    else:
        world_vx, world_vy, wz = command.world_vx, command.world_vy, command.wz
    body_vx, body_vy = world_to_body(world_vx, world_vy, own.yaw_rad)
    return body_vx, body_vy, wz


def _dry_run(robot_id: str) -> None:
    agent = RobotFormationAgent(robot_id)
    agent.accept_mission(FormationMission("dry-run", "square", 0.8))
    observations = {
        "robot1": AgentObservation("robot1", -1.4, -1.0),
        "robot2": AgentObservation("robot2", -1.4, 1.0),
        "robot3": AgentObservation("robot3", 1.4, 1.0),
        "robot4": AgentObservation("robot4", 1.4, -1.0),
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
        raise SystemExit(f"ROS 2 runtime import failed ({exc}); use --dry-run outside the robot container") from exc
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
            "arena_bounds_m": arena_bounds_from_config(limits),
            "min_distance_m": float(limits.get("min_distance_m", 0.25)),
            "topology": topology,
        }
        if mode == "second_order":
            return SecondOrderFormationAgent(robot_id, **kwargs)
        return RobotFormationAgent(robot_id, control_mode=mode, **kwargs)

    controller_ref: dict[str, RobotFormationAgent] = {"value": build_controller(control_mode)}
    protocol: dict[str, Any] = {
        "pending": None,
        "active_experiment_id": None,
        "active_deadline_unix_s": None,
    }
    poses: dict[str, tuple[float, float, float, bool, float, float]] = {}
    velocities: dict[str, tuple[float, float, float, float, float]] = {}
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
    mission_protocol_config = config.get("mission_protocol", {})
    max_mission_duration_s = float(mission_protocol_config.get("max_duration_s", 30.0))
    min_deadline_lead_s = float(mission_protocol_config.get("min_deadline_lead_s", 0.5))
    prepare_timeout_s = float(mission_protocol_config.get("prepare_timeout_s", 5.0))
    state_path = Path(
        str(
            mission_protocol_config.get(
                "state_path", "/opt/openvela-formation/state/{robot_id}-mission-state.json"
            )
        ).format(robot_id=robot_id)
    )
    try:
        retired_experiment_ids = load_retired_experiment_ids(state_path)
    except Exception as exc:
        raise SystemExit(f"cannot load mission replay-protection state {state_path}: {exc}") from exc
    publisher = node.create_publisher(Twist, str(mapping[robot_id]["cmd_vel_topic"]), 10)
    status_publisher = node.create_publisher(String, str(config["agent_status_topic"]), 10)
    ack_publisher = node.create_publisher(
        String,
        str(config.get("mission_ack_topic", "/formation/mission_ack")),
        10,
    )

    def publish_ack(experiment_id: str | None, phase: str, accepted: bool, reason: str) -> None:
        message = String()
        message.data = json.dumps(
            {
                "robot_id": robot_id,
                "experiment_id": experiment_id,
                "phase": phase,
                "accepted": accepted,
                "reason": reason,
                "timestamp_s": time.time(),
            },
            separators=(",", ":"),
        )
        ack_publisher.publish(message)

    def publish_status(safe: bool, reason: str, command: Any | None = None) -> None:
        message = String()
        message.data = json.dumps(
            {
                "robot_id": robot_id,
                "experiment_id": controller_ref["value"].mission.experiment_id if controller_ref["value"].mission else None,
                "control_mode": getattr(controller_ref["value"].mission, "control_mode", None),
                "deadline_unix_s": protocol["active_deadline_unix_s"],
                "safe": safe,
                "reason": reason,
                "target_x": command.target_x if command else None,
                "target_y": command.target_y if command else None,
                "timestamp_s": time.time(),
            },
            separators=(",", ":"),
        )
        status_publisher.publish(message)

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
                ros_stamp_unix_s(message.header.stamp),
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
                ros_stamp_unix_s(message.header.stamp),
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
            qos_profile_sensor_data,
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
            stamp_unix_s=ros_stamp_unix_s(message.header.stamp),
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
        if (
            not pose_entry
            or now - pose_entry[4] > timeout_s
            or not message_stamp_fresh(pose_entry[5], timeout_s)
        ):
            return None
        x, y, yaw, localization_ok, _, _ = pose_entry
        velocity_entry = velocities.get(observed_id)
        velocity_fresh = bool(
            velocity_entry
            and now - velocity_entry[3] <= odom_timeout_s
            and message_stamp_fresh(velocity_entry[4], odom_timeout_s)
        )
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

    def retire_experiment(experiment_id: str) -> None:
        if not experiment_id:
            return
        updated = set(retired_experiment_ids)
        updated.add(experiment_id)
        persist_retired_experiment_ids(state_path, updated)
        retired_experiment_ids.clear()
        retired_experiment_ids.update(updated)

    def stop_protocol(reason: str, requested_experiment_id: str | None = None) -> None:
        identifiers = {
            str(value)
            for value in (
                requested_experiment_id,
                protocol.get("active_experiment_id"),
                getattr(protocol.get("pending"), "mission", None).experiment_id
                if protocol.get("pending") is not None
                else None,
            )
            if value
        }
        controller_ref["value"].emergency_stop()
        publisher.publish(Twist())
        controller_ref["value"].clear()
        protocol["pending"] = None
        protocol["active_experiment_id"] = None
        protocol["active_deadline_unix_s"] = None
        protocol["active_fingerprint"] = None
        persistence_errors = []
        for experiment_id in identifiers:
            try:
                retire_experiment(experiment_id)
            except Exception as exc:
                persistence_errors.append(str(exc))
        if persistence_errors:
            node.get_logger().error(
                "mission stopped but replay-state persistence failed: " + "; ".join(persistence_errors)
            )
        publish_ack(requested_experiment_id, "abort", True, reason)

    def checked_deadline(payload: dict[str, Any], now_wall: float) -> float:
        deadline = float(payload["deadline_unix_s"])
        remaining = deadline - now_wall
        if not math.isfinite(deadline):
            raise ValueError("deadline_not_finite")
        if remaining < min_deadline_lead_s:
            raise ValueError("deadline_too_close_or_expired")
        if remaining > max_mission_duration_s:
            raise ValueError("deadline_exceeds_max_duration")
        return deadline

    def preflight(candidate: RobotFormationAgent, now_monotonic: float) -> str | None:
        observations: dict[str, AgentObservation] = {}
        for observed_id in ROBOT_IDS:
            observation = current_observation(observed_id, now_monotonic, True)
            if observation is None:
                return f"{observed_id}_state_stale"
            if not observation.localization_ok:
                return f"{observed_id}_localization_invalid"
            observations[observed_id] = observation
        if guard_enabled:
            if (
                now_monotonic - float(scan_state.get("received", 0.0)) > scan_timeout_s
                or not message_stamp_fresh(float(scan_state.get("stamp_unix_s", math.nan)), scan_timeout_s)
            ):
                return "lidar_stale"
            if not scan_state.get("ranges"):
                return "lidar_empty"
        target_x, target_y, _ = candidate.target_pose()
        if not point_in_arena(target_x, target_y, arena_bounds_from_config(limits)):
            return "target_outside_arena"
        own = observations[robot_id]
        if math.hypot(target_x - own.x, target_y - own.y) > float(limits.get("max_initial_target_distance_m", 0.4)):
            return "target_too_far"
        peers = [observations[item] for item in ROBOT_IDS if item != robot_id]
        command = candidate.compute(own, peers)
        if not command.safe:
            return command.reason
        return None

    def mission_callback(message: Any) -> None:
        payload: dict[str, Any] = {}
        experiment_id: str | None = None
        phase = "invalid"
        try:
            payload = json.loads(message.data)
            if not isinstance(payload, dict):
                raise ValueError("payload_not_object")
            experiment_id = str(payload.get("experiment_id") or "") or None
            phase = str(payload.get("phase") or "invalid").lower()
            if not payload.get("enabled", False) or phase == "abort":
                stop_protocol(str(payload.get("reason") or "mission_aborted"), experiment_id)
                return
            if phase not in {"prepare", "commit"}:
                raise ValueError("two_phase_protocol_required")
            if experiment_id is None:
                raise ValueError("experiment_id_required")
            now_wall = time.time()
            now_monotonic = time.monotonic()
            deadline = checked_deadline(payload, now_wall)
            mission = mission_from_payload(payload, control_mode)
            if mission.experiment_id != experiment_id:
                raise ValueError("experiment_id_mismatch")
            if not math.isfinite(mission.spacing_m) or mission.spacing_m <= 0.0:
                raise ValueError("spacing_invalid")
            fingerprint = mission_fingerprint(mission, deadline)

            if phase == "prepare":
                if protocol.get("active_experiment_id") is not None:
                    raise ValueError("another_mission_active")
                if experiment_id in retired_experiment_ids:
                    raise ValueError("experiment_id_retired")
                existing = protocol.get("pending")
                if existing is not None and existing.mission.experiment_id != experiment_id:
                    raise ValueError("another_mission_pending")
                candidate = build_controller(mission.control_mode)
                candidate.accept_mission(mission)
                reason = preflight(candidate, now_monotonic)
                if reason is not None:
                    raise ValueError(reason)
                protocol["pending"] = PreparedMission(
                    mission=mission,
                    controller=candidate,
                    fingerprint=fingerprint,
                    deadline_unix_s=deadline,
                    prepare_expires_monotonic=now_monotonic + prepare_timeout_s,
                )
                publisher.publish(Twist())
                publish_ack(experiment_id, "prepare", True, "prepared")
                node.get_logger().info(f"prepared mission {experiment_id}")
                return

            active_id = protocol.get("active_experiment_id")
            if active_id == experiment_id and protocol.get("active_fingerprint") == fingerprint:
                publish_ack(experiment_id, "commit", True, "already_committed")
                return
            pending: PreparedMission | None = protocol.get("pending")
            if pending is None or pending.mission.experiment_id != experiment_id:
                raise ValueError("mission_not_prepared")
            if now_monotonic > pending.prepare_expires_monotonic:
                retire_experiment(experiment_id)
                protocol["pending"] = None
                raise ValueError("prepare_expired")
            if fingerprint != pending.fingerprint:
                raise ValueError("commit_differs_from_prepare")
            reason = preflight(pending.controller, now_monotonic)
            if reason is not None:
                raise ValueError(reason)
            # Persist before activation. If this write fails, the mission fails closed.
            retire_experiment(experiment_id)
            controller_ref["value"] = pending.controller
            protocol["pending"] = None
            protocol["active_experiment_id"] = experiment_id
            protocol["active_deadline_unix_s"] = deadline
            protocol["active_fingerprint"] = fingerprint
            publish_ack(experiment_id, "commit", True, "committed")
            node.get_logger().warning(f"committed mission {experiment_id} until {deadline:.3f}")
        except Exception as exc:
            # A malformed or rejected control-plane message cannot leave an old
            # task running. This is intentionally fail-closed.
            identifiers = {
                str(value)
                for value in (experiment_id, protocol.get("active_experiment_id"))
                if value
            }
            pending = protocol.get("pending")
            if pending is not None:
                identifiers.add(pending.mission.experiment_id)
            controller_ref["value"].emergency_stop()
            publisher.publish(Twist())
            controller_ref["value"].clear()
            protocol["pending"] = None
            protocol["active_experiment_id"] = None
            protocol["active_deadline_unix_s"] = None
            protocol["active_fingerprint"] = None
            for identifier in identifiers:
                try:
                    retire_experiment(identifier)
                except Exception as persistence_exc:
                    node.get_logger().error(f"cannot persist retired mission {identifier}: {persistence_exc}")
            publish_ack(experiment_id, phase, False, str(exc))
            node.get_logger().error(f"mission {phase} rejected; output stopped: {exc}")

    mission_subscription = node.create_subscription(
        String,
        str(config["mission_topic"]),
        mission_callback,
        10,
    )

    def publish_control() -> None:
        if not pose_subscriptions or not odom_subscriptions:  # retain handles for this node's lifetime
            return
        now = time.monotonic()
        pending: PreparedMission | None = protocol.get("pending")
        if pending is not None and now > pending.prepare_expires_monotonic:
            try:
                retire_experiment(pending.mission.experiment_id)
            except Exception as exc:
                node.get_logger().error(f"cannot persist expired prepare: {exc}")
            protocol["pending"] = None
            publisher.publish(Twist())
            publish_ack(pending.mission.experiment_id, "prepare", False, "prepare_expired")
        active_id = protocol.get("active_experiment_id")
        active_deadline = protocol.get("active_deadline_unix_s")
        if active_id is not None and (active_deadline is None or time.time() >= float(active_deadline)):
            controller_ref["value"].emergency_stop()
            publisher.publish(Twist())
            controller_ref["value"].clear()
            protocol["active_experiment_id"] = None
            protocol["active_deadline_unix_s"] = None
            protocol["active_fingerprint"] = None
            publish_ack(str(active_id), "deadline", True, "mission_deadline_reached")
            publish_status(False, "mission_deadline_reached")
            return
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
        if controller.mission is not None:
            target_x, target_y, _ = controller.target_pose()
            max_target_distance = float(limits.get("max_initial_target_distance_m", 0.4)) + 0.1
            if math.hypot(target_x - own.x, target_y - own.y) > max_target_distance:
                controller.emergency_stop()
                publisher.publish(Twist())
                publish_status(False, "target_displacement_exceeded")
                return
        command = controller.compute(own, peers)
        body_vx, body_vy, wz = actuator_twist(
            command,
            own,
            1.0 / float(config.get("control_hz", 20.0)),
            float(limits.get("max_linear_mps", 0.65)),
            float(limits.get("max_angular_radps", 1.5)),
        )

        guard_reason: str | None = None
        if guard_enabled:
            scan_received = float(scan_state.get("received", 0.0))
            if (
                now - scan_received > scan_timeout_s
                or not message_stamp_fresh(float(scan_state.get("stamp_unix_s", math.nan)), scan_timeout_s)
            ):
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
