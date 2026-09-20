from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any


def mission_from_experiment(experiment: dict[str, Any]) -> dict[str, Any]:
    active = experiment.get("state") in {"FORMING", "HOLDING"}
    return {
        "enabled": active,
        "experiment_id": experiment.get("experiment_id"),
        "formation": experiment.get("formation"),
        "spacing_m": experiment.get("spacing_m"),
        "control_mode": experiment.get("control_mode", "anchored"),
        "center_x": 0.0,
        "center_y": 0.0,
        "heading_rad": 0.0,
        "state": experiment.get("state"),
    }


def _fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=1.0) as response:
        return json.load(response)["experiment"]


def _dry_run(url: str) -> None:
    print(json.dumps(mission_from_experiment(_fetch(url)), ensure_ascii=False, indent=2))


def _run_ros(config: dict[str, Any], url: str, ros_args: list[str]) -> None:
    try:
        import rclpy
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit("ROS 2 Python packages are not installed on this VM; use --dry-run") from exc
    rclpy.init(args=ros_args)
    node = rclpy.create_node("openvela_formation_mission_gateway")
    publisher = node.create_publisher(String, str(config["mission_topic"]), 10)

    def publish_mission() -> None:
        try:
            payload = mission_from_experiment(_fetch(url))
        except Exception as exc:
            payload = {"enabled": False, "state": "SERVICE_UNAVAILABLE", "reason": str(exc)}
        message = String()
        message.data = json.dumps(payload, separators=(",", ":"))
        publisher.publish(message)

    node.create_timer(0.2, publish_mission)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            message = String()
            message.data = '{"enabled":false,"state":"GATEWAY_STOPPED"}'
            publisher.publish(message)
            time.sleep(0.05)
            rclpy.shutdown()
        node.destroy_node()


def main() -> None:
    parser = argparse.ArgumentParser(description="Broadcast high-level formation missions; never publishes wheel velocity")
    parser.add_argument("--config", default="config/mentorpi.json")
    parser.add_argument("--state-url", default="http://127.0.0.1:8765/api/v1/state")
    parser.add_argument("--dry-run", action="store_true")
    args, ros_args = parser.parse_known_args()
    if args.dry_run:
        _dry_run(args.state_url)
        return
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    _run_ros(config, args.state_url, ros_args)


if __name__ == "__main__":
    main()
