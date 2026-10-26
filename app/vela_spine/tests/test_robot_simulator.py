import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from host.robot_simulator import Fleet, SCHEMA, make_server


def assign(robot="S1", task="task1", revision=1, command="assign1"):
    return dict(schema=SCHEMA, mode="simulation", command_id=command,
                robot_id=robot, task_id=task, revision=revision,
                action="ASSIGN", tag_id="D1")


def report(state, seq, robot="S1", task="task1", revision=1):
    msg = assign(robot, task, revision, "report-%s-%s-%s-%s" % (robot, task, revision, seq))
    msg.pop("tag_id")
    msg.update(action="REPORT", state=state, sequence=seq)
    return msg


class RobotNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "fleet.db"
        self.fleet = Fleet(self.path)
        self.server = make_server(self.fleet)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self, msg, status=200):
        data = msg if isinstance(msg, bytes) else json.dumps(msg).encode()
        request = Request(self.url + "/v1/commands", data=data, headers={"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=4)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.code, status)
            result = json.load(response)
        if status != 200:
            self.assertFalse(result["persisted"])
        return result

    def test_three_robots_complete_over_http(self):
        for robot in ("S1", "S2", "S3"):
            self.post(assign(robot, robot, command="assign" + robot))
            self.post(report("RUNNING", 1, robot, robot))
            result = self.post(report("COMPLETED", 2, robot, robot))
            self.assertEqual(result["task"]["state"], "COMPLETED")
            self.assertFalse(result["motion"])
        with urlopen(self.url + "/v1/state", timeout=4) as response:
            self.assertEqual(len(json.load(response)["tasks"]), 3)

    def test_lost_ack_retry_and_database_reopen(self):
        message = assign()
        original = self.post(message)
        self.post(report("RUNNING", 1))
        self.assertEqual(self.post(message), original)  # cached acceptance, not current state
        reopened = Fleet(self.path)
        self.assertEqual(reopened.apply(message), original)
        self.assertEqual(reopened.snapshot()["tasks"][0]["state"], "RUNNING")

    def test_conflict_busy_and_unique_owner(self):
        self.post(assign())
        self.post(assign(robot="S2"), 409)
        self.post(assign(robot="S2", revision=2, command="steal"), 409)
        self.post(assign(task="other", command="busy"), 409)
        self.post(report("RUNNING", 1, robot="S2"), 409)

    def test_sequence_and_terminal_guards(self):
        self.post(assign())
        self.post(report("COMPLETED", 1), 409)
        self.post(report("RUNNING", 2), 409)
        self.post(report("RUNNING", 1))
        self.post(report("BLOCKED", 2))
        self.post(report("COMPLETED", 3), 409)
        self.post(report("CANCELLED", 3))
        self.post(report("RUNNING", 4), 409)
        self.post(assign(robot="S2", revision=2, command="next"))
        self.post(report("COMPLETED", 4), 409)

    def test_offline_never_implies_completion_or_release(self):
        self.post(assign())
        self.fleet.offline.add("S1")
        message = report("RUNNING", 1)
        self.post(message, 503)
        self.post(assign(robot="S2", revision=2, command="unsafe-reassign"), 409)
        self.fleet.offline.clear()
        self.assertEqual(self.post(message)["task"]["state"], "RUNNING")

    def test_reject_malformed_or_live_input(self):
        for change in ({"mode": "live"}, {"robot_id": "S4"}, {"revision": True},
                       {"revision": 0}, {"extra": 1}, {"task_id": "../x"}):
            self.post({**assign(), **change}, 409)
        self.post(b'{"schema":1,"schema":2}', 409)
        self.post(b"[]", 409)
        self.post(b"x" * 4097, 409)
        self.assertEqual(self.fleet.snapshot()["tasks"], [])

    def test_concurrent_assignments_only_one_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        from host.robot_simulator import ProtocolError
        # Two independent DB connections exercise the SQLite transaction guard.
        second = Fleet(self.path)
        def attempt(fleet, robot):
            try:
                fleet.apply(assign(robot, command=robot))
                return True
            except ProtocolError:
                return False
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(attempt, self.fleet, "S1"), pool.submit(attempt, second, "S2")]
            self.assertEqual(sum(f.result() for f in futures), 1)


if __name__ == "__main__":
    unittest.main()
