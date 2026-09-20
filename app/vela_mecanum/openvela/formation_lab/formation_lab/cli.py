from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the local Formation Lab")
    parser.add_argument("action", choices=["start", "status", "stop", "reset", "capabilities", "inject_fault"])
    parser.add_argument("--url", default="http://127.0.0.1:8765/api/v1/formation")
    parser.add_argument("--id", dest="experiment_id")
    parser.add_argument("--formation", choices=["square", "line", "circle", "diamond"], default="square")
    parser.add_argument("--control-mode", choices=["anchored", "laplacian", "second_order"], default="anchored")
    parser.add_argument("--spacing", type=float, default=0.8)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--reason", default="cli_stop")
    parser.add_argument("--fault", choices=["offline", "localization_lost", "boundary", "collision"])
    parser.add_argument("--robot", default="Robot01")
    args = parser.parse_args()
    payload = {"action": args.action}
    if args.action == "start":
        payload.update({"experiment_id": args.experiment_id, "formation": args.formation, "spacing_m": args.spacing, "duration_s": args.duration, "control_mode": args.control_mode})
    elif args.action == "stop":
        payload["reason"] = args.reason
    elif args.action == "inject_fault":
        payload.update({"fault": args.fault, "robot_id": args.robot})
    raw = json.dumps(payload).encode()
    request = urllib.request.Request(args.url, raw, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode())
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
