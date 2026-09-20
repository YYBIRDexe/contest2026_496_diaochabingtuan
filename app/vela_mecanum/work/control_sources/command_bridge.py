#!/usr/bin/env python3
"""Gated formation command path from the fleet domain to one MentorPi domain.

The default deployment cannot publish a moving command: it needs a short lived
root-created lease, hardware_output_enabled=true, fresh agent status/commands,
and no competing controller activity.
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import time
from pathlib import Path

from command_gate import CommandGate


def read_lease(path: Path, robot: str, now: float) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expiry = float(data["expires_mono"])
        if data.get("robot") == robot and now < expiry <= now + 30.0:
            return str(data["id"])
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def hardware_enabled(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("hardware_output_enabled") is True
    except (OSError, ValueError, TypeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robot", required=True, choices=[f"robot{i}" for i in range(1, 5)])
    parser.add_argument("--local-domain", required=True, type=int)
    parser.add_argument("--fleet-domain", required=True, type=int)
    parser.add_argument("--config", type=Path, default=Path("/opt/openvela-formation/config/mentorpi.json"))
    parser.add_argument("--lease", type=Path, default=Path("/run/openvela-formation/command-arm.json"))
    args = parser.parse_args()
    if args.local_domain == args.fleet_domain:
        parser.error("local and fleet domains must differ")

    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from std_msgs.msg import String

    gate = CommandGate()
    local_context, fleet_context = Context(), Context()
    rclpy.init(context=local_context, domain_id=args.local_domain)
    rclpy.init(context=fleet_context, domain_id=args.fleet_domain)
    local = rclpy.create_node(f"formation_command_bridge_{args.robot}", context=local_context)
    fleet = rclpy.create_node(f"formation_command_input_{args.robot}", context=fleet_context)
    motor = local.create_publisher(Twist, "/cmd_vel", 10)
    report = fleet.create_publisher(String, f"/{args.robot}/formation/command_bridge_status", 10)
    command_topic = f"/{args.robot}/controller/cmd_vel"
    current_reason = "disarmed"

    expected_agent = f"formation_agent_{args.robot}"

    def command_callback(message: Twist) -> None:
        now = time.monotonic()
        sources = fleet.get_publishers_info_by_topic(command_topic)
        if len(sources) != 1 or sources[0].node_name != expected_agent:
            gate.conflict(now, "unauthorized_command_source")
            return
        extra = (message.linear.z, message.angular.x, message.angular.y)
        if any(not math.isfinite(value) or value != 0.0 for value in extra):
            gate.conflict(now, "invalid_command_axes")
            return
        gate.command((message.linear.x, message.linear.y, message.angular.z), now)

    def agent_status_callback(message: String) -> None:
        try:
            data = json.loads(message.data)
            if data.get("robot_id") == args.robot and data.get("experiment_id"):
                gate.status(data.get("safe") is True, str(data.get("reason")), time.monotonic())
        except (TypeError, ValueError):
            pass

    def competing_command(_message) -> None:
        gate.conflict(time.monotonic())

    fleet.create_subscription(Twist, command_topic, command_callback, 10)
    fleet.create_subscription(String, "/formation/agent_status", agent_status_callback, 10)
    local.create_subscription(Twist, "/controller/cmd_vel", competing_command, 10)
    local.create_subscription(Twist, "/app/cmd_vel", competing_command, 10)

    def unique_command_source() -> bool:
        local_publishers = local.get_publishers_info_by_topic("/cmd_vel")
        fleet_publishers = fleet.get_publishers_info_by_topic(command_topic)
        motor_publishers = local.get_publishers_info_by_topic("/ros_robot_controller/set_motor")
        return (
            len(local_publishers) == 1
            and local_publishers[0].node_name == local.get_name()
            and len(fleet_publishers) == 1
            and fleet_publishers[0].node_name == expected_agent
            and len(motor_publishers) == 1
            and motor_publishers[0].node_name == "odom_publisher"
        )

    def tick() -> None:
        nonlocal current_reason
        now = time.monotonic()
        lease_id = read_lease(args.lease, args.robot, now)
        output, current_reason = gate.step(
            now,
            lease_id,
            hardware_enabled(args.config),
            unique_command_source(),
        )
        if output is not None:
            message = Twist()
            message.linear.x, message.linear.y, message.angular.z = output
            motor.publish(message)

    def status_tick() -> None:
        message = String()
        message.data = json.dumps({
            "robot": args.robot,
            "armed": gate.lease_id is not None,
            "forwarding": gate.active,
            "reason": current_reason,
            "local_domain": args.local_domain,
            "fleet_domain": args.fleet_domain,
        }, separators=(",", ":"))
        report.publish(message)

    local.create_timer(0.05, tick)
    fleet.create_timer(1.0, status_tick)
    local_executor = SingleThreadedExecutor(context=local_context)
    fleet_executor = SingleThreadedExecutor(context=fleet_context)
    local_executor.add_node(local)
    fleet_executor.add_node(fleet)
    stop = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    print(f"command bridge {args.robot}: local={args.local_domain} fleet={args.fleet_domain} locked", flush=True)
    try:
        while not stop:
            fleet_executor.spin_once(timeout_sec=0.02)
            local_executor.spin_once(timeout_sec=0.02)
    finally:
        if gate.lease_id is not None:
            zero = Twist()
            for _ in range(5):
                motor.publish(zero)
                time.sleep(0.05)
        local_executor.remove_node(local)
        fleet_executor.remove_node(fleet)
        local.destroy_node()
        fleet.destroy_node()
        rclpy.shutdown(context=local_context)
        rclpy.shutdown(context=fleet_context)


if __name__ == "__main__":
    main()
