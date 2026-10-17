from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

from .agent import ROBOT_IDS, arena_bounds_from_config, formation_offsets, point_in_arena
from .mentorpi_agent import (
    _normalized_frame,
    _yaw_from_quaternion,
    localization_covariance_ok,
    message_stamp_fresh,
    ros_stamp_unix_s,
)


def circular_mean(values: list[float]) -> float:
    if not values:
        raise ValueError("no headings")
    return math.atan2(sum(math.sin(value) for value in values), sum(math.cos(value) for value in values))


def build_relative_mission(
    poses: dict[str, tuple[float, float, float]],
    distance_m: float,
    duration_s: float,
    formation: str,
    spacing_m: float,
    control_mode: str,
    experiment_id: str,
    now_unix_s: float,
) -> dict[str, Any]:
    if set(poses) != set(ROBOT_IDS):
        raise ValueError("all four poses are required")
    if not math.isfinite(distance_m) or abs(distance_m) > 0.5:
        raise ValueError("distance must be finite and no more than 0.5 m")
    if not math.isfinite(duration_s) or not 1.0 <= duration_s <= 20.0:
        raise ValueError("duration must be between 1 and 20 seconds")
    center_x = sum(pose[0] for pose in poses.values()) / len(ROBOT_IDS)
    center_y = sum(pose[1] for pose in poses.values()) / len(ROBOT_IDS)
    heading = circular_mean([pose[2] for pose in poses.values()])
    return {
        "enabled": True,
        "phase": "prepare",
        "experiment_id": experiment_id,
        "formation": formation,
        "spacing_m": spacing_m,
        "center_x": center_x + distance_m * math.cos(heading),
        "center_y": center_y + distance_m * math.sin(heading),
        "heading_rad": heading,
        "control_mode": control_mode,
        "deadline_unix_s": now_unix_s + duration_s,
    }


def validate_geometry(
    poses: dict[str, tuple[float, float, float]],
    mission: dict[str, Any],
    arena_half_extent_m: float | tuple[float, float, float, float],
    min_distance_m: float,
    max_initial_target_distance_m: float = 0.4,
) -> None:
    if not math.isfinite(max_initial_target_distance_m) or max_initial_target_distance_m <= 0.0:
        raise ValueError("invalid maximum initial target distance")
    bounds = (
        arena_half_extent_m
        if isinstance(arena_half_extent_m, tuple)
        else arena_bounds_from_config({"arena_half_extent_m": arena_half_extent_m})
    )
    for index, first in enumerate(ROBOT_IDS):
        if not point_in_arena(poses[first][0], poses[first][1], bounds):
            raise ValueError(f"{first} is outside the configured arena")
        for second in ROBOT_IDS[index + 1 :]:
            distance = math.hypot(poses[first][0] - poses[second][0], poses[first][1] - poses[second][1])
            if distance < min_distance_m:
                raise ValueError(f"{first}/{second} separation {distance:.3f} m is unsafe")
    offsets = formation_offsets(str(mission["formation"]), float(mission["spacing_m"]))
    cosine = math.cos(float(mission["heading_rad"]))
    sine = math.sin(float(mission["heading_rad"]))
    for robot_id, (offset_x, offset_y) in offsets.items():
        target_x = float(mission["center_x"]) + cosine * offset_x - sine * offset_y
        target_y = float(mission["center_y"]) + sine * offset_x + cosine * offset_y
        if not point_in_arena(target_x, target_y, bounds):
            raise ValueError(f"{robot_id} target is outside the configured arena")
        travel = math.hypot(target_x - poses[robot_id][0], target_y - poses[robot_id][1])
        if travel > max_initial_target_distance_m:
            raise ValueError(f"{robot_id} target requires {travel:.3f} m, above the configured limit")


def _run(config: dict[str, Any], args: argparse.Namespace, ros_args: list[str]) -> None:
    try:
        import rclpy
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit(f"ROS 2 runtime import failed: {exc}") from exc

    rclpy.init(args=ros_args)
    node = rclpy.create_node("formation_once_coordinator")
    mission_publisher = node.create_publisher(String, str(config["mission_topic"]), 10)
    map_frame = _normalized_frame(config.get("shared_map_frame", "map"))
    max_xy_variance = float(config.get("max_xy_variance_m2", 0.25))
    max_yaw_variance = float(config.get("max_yaw_variance_rad2", 0.25))
    pose_timeout_s = float(config.get("peer_timeout_s", 0.7))
    poses: dict[str, tuple[float, float, float, float, float]] = {}
    acknowledgements: dict[str, dict[str, Any]] = {}
    bridge_status: dict[str, tuple[dict[str, Any], float]] = {}
    agent_status: dict[str, tuple[dict[str, Any], float]] = {}

    def pose_callback(robot_id: str):
        def callback(message: Any) -> None:
            pose = message.pose.pose
            if _normalized_frame(message.header.frame_id) != map_frame:
                return
            if not localization_covariance_ok(message.pose.covariance, max_xy_variance, max_yaw_variance):
                return
            stamp_unix_s = ros_stamp_unix_s(message.header.stamp)
            if not message_stamp_fresh(stamp_unix_s, pose_timeout_s):
                return
            yaw = _yaw_from_quaternion(
                pose.orientation.x,
                pose.orientation.y,
                pose.orientation.z,
                pose.orientation.w,
            )
            values = (float(pose.position.x), float(pose.position.y), yaw)
            if all(math.isfinite(value) for value in values):
                poses[robot_id] = (*values, time.monotonic(), stamp_unix_s)

        return callback

    subscriptions = [
        node.create_subscription(
            PoseWithCovarianceStamped,
            str(config["robots"][robot_id]["pose_topic"]),
            pose_callback(robot_id),
            10,
        )
        for robot_id in ROBOT_IDS
    ]

    def ack_callback(message: Any) -> None:
        try:
            payload = json.loads(message.data)
            robot_id = str(payload["robot_id"])
            if robot_id in ROBOT_IDS:
                acknowledgements[robot_id] = payload
        except (KeyError, TypeError, ValueError):
            return

    def agent_status_callback(message: Any) -> None:
        try:
            payload = json.loads(message.data)
            robot_id = str(payload["robot_id"])
            if robot_id in ROBOT_IDS:
                agent_status[robot_id] = (payload, time.monotonic())
        except (KeyError, TypeError, ValueError):
            return

    subscriptions.append(
        node.create_subscription(String, str(config.get("mission_ack_topic", "/formation/mission_ack")), ack_callback, 10)
    )
    subscriptions.append(
        node.create_subscription(String, str(config["agent_status_topic"]), agent_status_callback, 10)
    )

    def bridge_callback(robot_id: str):
        def callback(message: Any) -> None:
            try:
                bridge_status[robot_id] = (json.loads(message.data), time.monotonic())
            except (TypeError, ValueError):
                return

        return callback

    for robot_id in ROBOT_IDS:
        subscriptions.append(
            node.create_subscription(
                String,
                f"/{robot_id}/formation/command_bridge_status",
                bridge_callback(robot_id),
                10,
            )
        )

    def spin_until(predicate, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if predicate():
                return True
        return False

    def publish(payload: dict[str, Any]) -> None:
        message = String()
        message.data = json.dumps(payload, separators=(",", ":"), allow_nan=False)
        mission_publisher.publish(message)

    def abort(experiment_id: str, reason: str) -> None:
        publish({"enabled": False, "phase": "abort", "experiment_id": experiment_id, "reason": reason})
        for _ in range(3):
            rclpy.spin_once(node, timeout_sec=0.05)

    try:
        if not spin_until(lambda: len(poses) == len(ROBOT_IDS), args.discovery_timeout_s):
            raise RuntimeError(f"fresh valid poses missing: {sorted(set(ROBOT_IDS) - set(poses))}")
        now_monotonic = time.monotonic()
        stale_poses = [
            robot_id
            for robot_id, pose in poses.items()
            if now_monotonic - pose[3] > pose_timeout_s
            or not message_stamp_fresh(pose[4], pose_timeout_s)
        ]
        if stale_poses:
            raise RuntimeError(f"stale poses: {stale_poses}")
        if not spin_until(lambda: len(agent_status) == len(ROBOT_IDS), args.discovery_timeout_s):
            raise RuntimeError("not all four formation agents are reporting")
        if args.require_armed:
            if not spin_until(lambda: len(bridge_status) == len(ROBOT_IDS), args.discovery_timeout_s):
                raise RuntimeError("not all four command bridges are reporting")
            now_monotonic = time.monotonic()
            bad_bridges = [
                robot_id
                for robot_id in ROBOT_IDS
                if now_monotonic - bridge_status[robot_id][1] > 1.5
                or bridge_status[robot_id][0].get("armed") is not True
                or bridge_status[robot_id][0].get("forwarding") is True
            ]
            if bad_bridges:
                raise RuntimeError(f"bridges not freshly armed and idle: {bad_bridges}")

        clean_poses = {robot_id: poses[robot_id][:3] for robot_id in ROBOT_IDS}
        experiment_id = args.experiment_id or f"formation-{uuid.uuid4()}"
        mission = build_relative_mission(
            clean_poses,
            args.distance_m,
            args.duration_s,
            args.formation,
            args.spacing_m,
            args.control_mode,
            experiment_id,
            time.time(),
        )
        limits = config.get("limits", {})
        validate_geometry(
            clean_poses,
            mission,
            arena_bounds_from_config(limits),
            float(limits.get("min_distance_m", 0.25)),
            float(limits.get("max_initial_target_distance_m", 0.4)),
        )
        if not args.execute:
            print(json.dumps({"result": "validated_only", "mission": mission}, ensure_ascii=False, indent=2))
            return

        acknowledgements.clear()
        publish(mission)

        def phase_complete(phase: str) -> bool:
            return all(
                acknowledgements.get(robot_id, {}).get("experiment_id") == experiment_id
                and acknowledgements[robot_id].get("phase") == phase
                for robot_id in ROBOT_IDS
            )

        if not spin_until(lambda: phase_complete("prepare"), args.ack_timeout_s):
            abort(experiment_id, "prepare_timeout")
            raise RuntimeError(f"prepare acknowledgements incomplete: {acknowledgements}")
        rejected = [robot_id for robot_id, item in acknowledgements.items() if item.get("accepted") is not True]
        if rejected:
            abort(experiment_id, "prepare_rejected")
            raise RuntimeError(f"prepare rejected by {rejected}: {acknowledgements}")

        stale_poses = [
            robot_id
            for robot_id, pose in poses.items()
            if time.monotonic() - pose[3] > pose_timeout_s
            or not message_stamp_fresh(pose[4], pose_timeout_s)
        ]
        if stale_poses:
            abort(experiment_id, "pose_stale_before_commit")
            raise RuntimeError(f"poses stale before commit: {stale_poses}")

        acknowledgements.clear()
        commit = dict(mission, phase="commit")
        publish(commit)
        if not spin_until(lambda: phase_complete("commit"), args.ack_timeout_s):
            abort(experiment_id, "commit_timeout")
            raise RuntimeError(f"commit acknowledgements incomplete: {acknowledgements}")
        rejected = [robot_id for robot_id, item in acknowledgements.items() if item.get("accepted") is not True]
        if rejected:
            abort(experiment_id, "commit_rejected")
            raise RuntimeError(f"commit rejected by {rejected}: {acknowledgements}")
        print(json.dumps({"result": "committed", "mission": commit}, ensure_ascii=False, indent=2))
    finally:
        del subscriptions
        node.destroy_node()
        rclpy.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and commit one bounded four-car formation task")
    parser.add_argument("--config", default="config/mentorpi.json")
    parser.add_argument("--distance-m", type=float, default=0.20)
    parser.add_argument("--duration-s", type=float, default=5.0)
    parser.add_argument("--formation", default="square", choices=("square", "line", "circle", "diamond"))
    parser.add_argument("--spacing-m", type=float, default=0.8)
    parser.add_argument("--control-mode", default="anchored", choices=("anchored", "laplacian", "second_order"))
    parser.add_argument("--experiment-id")
    parser.add_argument("--discovery-timeout-s", type=float, default=5.0)
    parser.add_argument("--ack-timeout-s", type=float, default=2.0)
    parser.add_argument("--require-armed", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--execute", action="store_true", help="publish prepare/commit; otherwise validate only")
    args, ros_args = parser.parse_known_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    _run(config, args, ros_args)


if __name__ == "__main__":
    main()
