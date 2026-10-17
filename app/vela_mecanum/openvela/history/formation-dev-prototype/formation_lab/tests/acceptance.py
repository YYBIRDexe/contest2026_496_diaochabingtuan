from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8765"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=3) as response:
        return json.load(response)


def post(path: str, payload: dict):
    request = urllib.request.Request(BASE + path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


def wait_state(wanted: set[str], timeout: float = 12.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        experiment = get("/api/v1/state")["experiment"]
        if experiment["state"] in wanted:
            return experiment
        time.sleep(0.1)
    raise AssertionError(f"state timeout: {experiment}")


def main() -> None:
    health = get("/api/v1/health")
    assert health["ok"]
    capabilities = get("/api/v1/capabilities")["capabilities"]
    assert capabilities["control_architecture"] == "distributed_onboard_agents"
    assert capabilities["command_axes"] == ["vx", "vy", "wz"]

    current = get("/api/v1/state")["experiment"]
    if current["state"] in {"VALIDATING", "FORMING", "HOLDING", "STOPPING"}:
        post("/api/v1/formation", {"action": "stop", "reason": "acceptance_setup"})
        wait_state({"ABORTED", "FAILED"})
    if get("/api/v1/state")["experiment"]["state"] != "IDLE":
        post("/api/v1/formation", {"action": "reset"})

    experiment_id = f"accept-{int(time.time())}"
    request = {"action": "start", "experiment_id": experiment_id, "formation": "square", "spacing_m": 0.8, "duration_s": 1}
    started = post("/api/v1/formation", request)
    replay = post("/api/v1/formation", request)
    assert started["experiment"]["state"] == "FORMING"
    assert replay["experiment"]["idempotent_replay"]
    finished = wait_state({"FINISHED", "FAILED"})
    assert finished["state"] == "FINISHED", finished
    assert finished["max_error_m"] <= 0.05

    trajectory = Path("var/experiments") / experiment_id / "trajectory.csv"
    with trajectory.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert rows and {row["robot_id"] for row in rows} == {"Robot01", "Robot02", "Robot03", "Robot04"}
    assert {"vx", "vy", "wz", "yaw_rad"}.issubset(rows[0])

    completion = post(
        "/v1/chat/completions",
        {"model": "formation-local-stub", "messages": [{"role": "user", "content": "让四辆车按菱形编队，间距0.9米，运行20秒"}], "tools": []},
    )
    call = completion["choices"][0]["message"]["tool_calls"][0]["function"]
    arguments = json.loads(call["arguments"])
    assert call["name"] == "formation_control"
    assert arguments["formation"] == "diamond"
    assert arguments["spacing_m"] == 0.9
    assert arguments["duration_s"] == 20.0

    post("/api/v1/formation", {"action": "reset"})
    post("/api/v1/formation", {"action": "start", "experiment_id": experiment_id + "-fault", "duration_s": 10})
    post("/api/v1/formation", {"action": "inject_fault", "fault": "offline", "robot_id": "Robot03"})
    failed = wait_state({"FAILED"})
    assert failed["error_code"] == "robot_offline"
    assert all(robot["vx"] == 0 and robot["vy"] == 0 and robot["wz"] == 0 for robot in failed["robots"])
    post("/api/v1/formation", {"action": "reset"})
    print(json.dumps({"ok": True, "experiment_id": experiment_id, "final_state": finished["state"], "trajectory_rows": len(rows), "nl_tool": arguments, "fault_stop": failed["error_code"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
