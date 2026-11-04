"""Run a three-robot HTTP replay and save inspectable evidence in a new directory."""
import argparse
import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from .robot_simulator import Fleet, SCHEMA, make_server


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    fleet = Fleet(output / "fleet.sqlite3")
    server = make_server(fleet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    evidence = []

    def send(message, expected=200):
        request = Request("http://127.0.0.1:%d/v1/commands" % server.server_port,
                          data=json.dumps(message).encode(), headers={"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            code, body = response.code, json.load(response)
        evidence.append({"request": message, "http_status": code, "response": body})
        if code != expected:
            raise RuntimeError("unexpected HTTP status: %d" % code)
        return body

    try:
        for robot, tag in zip(("S1", "S2", "S3"), ("D1", "D3", "D6")):
            base = dict(schema=SCHEMA, mode="simulation", robot_id=robot,
                        task_id="inspect-" + tag, revision=1)
            assignment = base | dict(command_id="assign-" + robot, action="ASSIGN", tag_id=tag)
            ack = send(assignment)
            if send(assignment) != ack:
                raise RuntimeError("retry was not idempotent")
            running = base | dict(command_id="run-" + robot, action="REPORT", state="RUNNING", sequence=1)
            if robot == "S2":
                fleet.offline.add(robot)
                send(running, 503)
                fleet.offline.clear()
            send(running)
            send(base | dict(command_id="done-" + robot, action="REPORT", state="COMPLETED", sequence=2))
        snapshot = Fleet(output / "fleet.sqlite3").snapshot()
        if not all(t["state"] == "COMPLETED" for t in snapshot["tasks"]) or len(snapshot["tasks"]) != 3:
            raise RuntimeError("incomplete replay")
        result = {"passed": True, "source": "PC_NETWORK_SIMULATOR", "board_verified": False,
                  "physical_execution": False, "requests": evidence, "reopened_state": snapshot}
        (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"passed": result["passed"], "requests": len(result["requests"]),
                      "source": result["source"], "board_verified": False}))
