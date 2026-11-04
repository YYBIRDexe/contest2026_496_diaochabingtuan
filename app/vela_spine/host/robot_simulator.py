"""Loopback-only, durable three-robot protocol simulator. Never drives hardware."""
import argparse
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCHEMA = "spine-robot-sim-v1"
ROBOTS = ("S1", "S2", "S3")
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED", "STOP_CONFIRMED")
TRANSITIONS = {
    "ACCEPTED": {"RUNNING", "FAILED", "CANCELLED"},
    "RUNNING": {"BLOCKED", "COMPLETED", "FAILED", "CANCELLED"},
    "BLOCKED": {"RUNNING", "FAILED", "CANCELLED"},
}


class ProtocolError(ValueError):
    pass


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProtocolError("duplicate key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def validate(message):
    common = {"schema", "mode", "command_id", "robot_id", "task_id", "revision", "action"}
    if not isinstance(message, dict):
        raise ProtocolError("object required")
    action = message.get("action")
    if action == "ASSIGN":
        extra = {"tag_id"}
    elif action == "REPORT":
        extra = {"state", "sequence"}
    elif action == "STOP":
        extra = set()
    else:
        extra = None
    if extra is None or set(message) != common | extra:
        raise ProtocolError("invalid action or fields")
    if message["schema"] != SCHEMA or message["mode"] != "simulation":
        raise ProtocolError("simulation schema required")
    if message["robot_id"] not in ROBOTS:
        raise ProtocolError("unknown robot")
    for key in ("command_id", "task_id") + (("tag_id",) if action == "ASSIGN" else ()):
        if not isinstance(message[key], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", message[key]):
            raise ProtocolError("invalid identifier")
    for key in ("revision",) + (("sequence",) if action == "REPORT" else ()):
        if type(message[key]) is not int or not 1 <= message[key] <= 2147483647:
            raise ProtocolError("positive integer required")
    if action == "REPORT" and message["state"] not in ("RUNNING", "BLOCKED") + TERMINAL:
        raise ProtocolError("invalid state")


class Fleet:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()
        self.offline = set()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, revision INTEGER, robot_id TEXT,
                    tag_id TEXT, state TEXT, sequence INTEGER);
                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY, body TEXT, response TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self):
        with self.lock, self.connect() as db:
            return {"schema": SCHEMA, "source": "PC_NETWORK_SIMULATOR",
                    "motion": False, "offline": sorted(self.offline),
                    "tasks": [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY task_id")]}

    def current_snapshot(self):
        """One latest task per robot; historical rows remain in SQLite.

        A robot can have only one nonterminal task. The board can therefore
        reconcile the current task without receiving an unbounded history.
        """
        with self.lock, self.connect() as db:
            rows=db.execute("""SELECT t.* FROM tasks t WHERE t.rowid =
                (SELECT MAX(x.rowid) FROM tasks x WHERE x.robot_id=t.robot_id)
                ORDER BY t.robot_id""")
            return {"schema":SCHEMA,"source":"PC_NETWORK_SIMULATOR","motion":False,
                    "offline":sorted(self.offline),"tasks":[dict(r) for r in rows]}

    def apply(self, message):
        validate(message)
        body = json.dumps(message, sort_keys=True, separators=(",", ":"))
        with self.lock, self.connect() as db:
            if message["robot_id"] in self.offline:
                raise ConnectionError("simulated robot offline")
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM commands WHERE command_id=?", (message["command_id"],)).fetchone()
            if old:
                if old["body"] != body:
                    raise ProtocolError("command id conflict")
                return json.loads(old["response"])
            task = db.execute("SELECT * FROM tasks WHERE task_id=?", (message["task_id"],)).fetchone()
            if message["action"] == "ASSIGN":
                if task and (message["revision"] != task["revision"] + 1 or task["state"] not in TERMINAL):
                    raise ProtocolError("task still owned or revision mismatch")
                if not task and message["revision"] != 1:
                    raise ProtocolError("first revision must be one")
                busy = db.execute(
                    "SELECT task_id FROM tasks WHERE robot_id=? AND state NOT IN (%s)"
                    % ",".join("?" * len(TERMINAL)), (message["robot_id"],) + TERMINAL).fetchone()
                if busy:
                    raise ProtocolError("robot busy")
                db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?)", (
                    message["task_id"], message["revision"], message["robot_id"], message["tag_id"], "ACCEPTED", 0))
            elif message["action"] == "STOP":
                if not task or (task["revision"], task["robot_id"]) != (message["revision"], message["robot_id"]):
                    raise ProtocolError("stale revision or wrong owner")
                # An explicit STOP must also confirm quiescence when completion
                # raced with the request. Never stop an old task on a busy robot.
                other = db.execute(
                    "SELECT task_id FROM tasks WHERE robot_id=? AND task_id<>? "
                    "AND state NOT IN (%s)" % ",".join("?" * len(TERMINAL)),
                    (message["robot_id"], message["task_id"]) + TERMINAL).fetchone()
                if other:
                    raise ProtocolError("robot serving another task")
                if task["sequence"] >= 2147483647:
                    raise ProtocolError("sequence exhausted")
                db.execute("UPDATE tasks SET state=?,sequence=? WHERE task_id=?", (
                    "STOP_CONFIRMED", task["sequence"] + 1, message["task_id"]))
            else:
                if not task or (task["revision"], task["robot_id"]) != (message["revision"], message["robot_id"]):
                    raise ProtocolError("stale revision or wrong owner")
                if message["sequence"] != task["sequence"] + 1:
                    raise ProtocolError("out of order report")
                if message["state"] not in TRANSITIONS.get(task["state"], set()):
                    raise ProtocolError("invalid transition")
                db.execute("UPDATE tasks SET state=?,sequence=? WHERE task_id=?", (
                    message["state"], message["sequence"], message["task_id"]))
            current = dict(db.execute("SELECT * FROM tasks WHERE task_id=?", (message["task_id"],)).fetchone())
            response = {"schema": SCHEMA, "command_id": message["command_id"],
                        "persisted": True, "ack_scope": "SIMULATOR_STORAGE_ONLY",
                        "motion": False, "task": current}
            db.execute("INSERT INTO commands VALUES (?,?,?)", (message["command_id"], body, json.dumps(response)))
            # Context manager commits before caller can send an ACK.
        return response


def make_server(fleet, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.reply(200, fleet.current_snapshot()) if self.path == "/v1/state" else self.reply(404, {"error": "not found"})

        def do_POST(self):
            self.connection.settimeout(3)
            try:
                if self.path != "/v1/commands":
                    self.reply(404, {"error": "not found"})
                    return
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
                    raise ProtocolError("one Content-Length required")
                size = int(lengths[0])
                if not 0 < size <= 4096:
                    raise ProtocolError("body limit 4096")
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ProtocolError("incomplete body")
                self.reply(200, fleet.apply(decode(raw)))
            except ConnectionError:
                self.reply(503, {"error": "simulated offline", "persisted": False})
            except (ValueError, TypeError, UnicodeError):
                self.reply(409, {"error": "invalid or conflicting command", "persisted": False})
            except (sqlite3.Error, OSError):
                self.reply(503, {"error": "storage or transport unavailable", "persisted": False})
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--port", type=int, default=18140)
    parser.add_argument("--offline", choices=ROBOTS, nargs="*", default=[])
    args = parser.parse_args()
    fleet = Fleet(args.database)
    fleet.offline.update(args.offline)
    server = make_server(fleet, args.port)
    print(json.dumps({"url": "http://127.0.0.1:%d" % server.server_port, "motion": False}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
