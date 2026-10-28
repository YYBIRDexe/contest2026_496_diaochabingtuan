"""Official ai_agent business tools: the three narrow tool calls, executed for real.

The tool layer must return execution results (not explanations), must never accept
a shell/path/speed argument, and must keep "acknowledged" apart from "completed".
"""
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from host.robot_simulator import Fleet, SCHEMA, make_server

BIN = os.environ.get('SPINE_CLI')


@unittest.skipUnless(BIN, 'set SPINE_CLI')
class TaskTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = self.root / 'sp'
        self.ledger.mkdir()
        self.fleet = Fleet(self.root / 'fleet.db')
        self.server = make_server(self.fleet)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = '127.0.0.1:%d' % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def run_cli(self, *args, expect=0):
        result = subprocess.run([BIN] + list(args), capture_output=True, text=True)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def tool(self, name, arguments, endpoint=False, expect=0):
        args = ['--task-tool', str(self.ledger), name, json.dumps(arguments)]
        if endpoint:
            args.append(self.endpoint)
        return self.run_cli(*args, expect=expect)

    def plan_body(self, tasks, version=1, plan_id='p1'):
        return dict(schema='spine-plan-v1', plan_id=plan_id, version=version, tasks=tasks)

    def task(self, task_id='T1', tag='D1', robot='S1', revision=1):
        return dict(task_id=task_id, tag_id=tag, robot_id=robot, revision=revision)

    def submit(self, tasks=None, expect=0, **kw):
        return self.tool('task_submit', self.plan_body(tasks or [self.task()], **kw), expect=expect)

    def report(self, robot, task, revision, state, sequence):
        message = dict(schema=SCHEMA, mode='simulation', command_id='r-%s-%s-%d' % (task, state, sequence),
                       robot_id=robot, task_id=task, revision=revision, action='REPORT',
                       state=state, sequence=sequence)
        request = Request('http://%s/v1/commands' % self.endpoint, data=json.dumps(message).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=4) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def fleet_task(self, task):
        return [dict(row) for row in self.fleet.snapshot()['tasks'] if row['task_id'] == task]

    def running_task(self):
        self.submit()
        self.tool('task_status', {})  # ledger is readable through the same tool
        self.run_cli('--task-dispatch', str(self.ledger), self.endpoint)
        self.report('S1', 'T1', 1, 'RUNNING', 1)
        self.run_cli('--task-poll', str(self.ledger), self.endpoint)

    def test_submit_executes_and_returns_result(self):
        submitted = self.submit()
        self.assertEqual(submitted['tool'], 'task_submit')
        self.assertTrue(submitted['ok'])
        self.assertEqual(submitted['result']['status'], 'PLAN_PERSISTED')
        self.assertEqual(submitted['result']['tasks'][0]['state'], 'PENDING')
        self.assertFalse(submitted['motion'])
        self.assertEqual(submitted['ack_scope'], 'LOCAL_STORAGE_ONLY')
        listed = self.tool('task_status', {})
        self.assertEqual(listed['result']['status'], 'TASK_LIST')
        self.assertEqual(listed['result']['tasks'][0]['task_id'], 'T1')
        self.assertEqual(listed['result']['tasks'][0]['state'], 'PENDING')

    def test_status_single_and_missing(self):
        self.submit()
        single = self.tool('task_status', {'task_id': 'T1'})
        self.assertEqual(single['result']['status'], 'TASK_VIEW')
        self.assertEqual(single['result']['tasks'][0]['state'], 'PENDING')
        missing = self.tool('task_status', {'task_id': 'nope'}, expect=2)
        self.assertEqual(missing['result']['status'], 'TASK_NOT_FOUND')
        self.assertFalse(missing['ok'])

    def test_stop_without_executor_only_requests(self):
        self.running_task()
        stopped = self.tool('task_stop', {'task_id': 'T1'})
        self.assertEqual(stopped['result']['status'], 'STOP_REQUESTED')
        self.assertFalse(stopped['result']['executor_confirmed'])
        self.assertFalse(stopped['result']['robot_released'])
        self.assertEqual(self.fleet_task('T1')[0]['state'], 'RUNNING')

    def test_stop_with_executor_confirms(self):
        self.running_task()
        stopped = self.tool('task_stop', {'task_id': 'T1'}, endpoint=True)
        self.assertEqual(stopped['result']['request']['status'], 'STOP_REQUESTED')
        executed = stopped['result']['executor']['tasks'][0]
        self.assertEqual(executed['status'], 'STOP_CONFIRMED')
        self.assertTrue(executed['executor_confirmed'])
        self.assertEqual(self.fleet_task('T1')[0]['state'], 'STOP_CONFIRMED')
        self.assertEqual(self.tool('task_status', {'task_id': 'T1'})['result']['tasks'][0]['state'],
                         'STOP_CONFIRMED')

    def test_stop_missing_with_executor_preserves_error(self):
        self.submit()
        result = self.tool('task_stop', {'task_id': 'missing'}, endpoint=True, expect=2)
        self.assertFalse(result['ok'])
        self.assertEqual(result['result']['status'], 'TASK_NOT_FOUND')

    def test_stop_network_failure_keeps_request_pending(self):
        self.running_task()
        self.server.shutdown()
        self.server.server_close()
        result = self.tool('task_stop', {'task_id': 'T1'}, endpoint=True, expect=4)
        self.assertFalse(result['ok'])
        self.assertEqual(result['result']['request']['status'], 'STOP_REQUESTED')
        self.assertEqual(result['result']['executor']['status'], 'PARTIAL_NETWORK_ERROR')
        self.assertEqual(self.tool('task_status', {'task_id': 'T1'})['result']['tasks'][0]['state'], 'STOP_REQUESTED')

    def test_unknown_tool_is_not_answered_as_text(self):
        result = subprocess.run([BIN, '--task-tool', str(self.ledger), 'run_shell', '{"command":"ls"}'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')

    def test_bad_arguments_are_rejected_before_the_ledger(self):
        self.submit()
        extra = self.tool('task_status', {'task_id': 'T1', 'x': 1}, expect=2)
        self.assertFalse(extra['ok'])
        self.assertFalse(self.tool('task_status', {'x': 1}, expect=2)['ok'])
        nine = [self.task('T%d' % n, 'D%d' % n, 'S1') for n in range(9)]
        self.assertFalse(self.submit(nine, expect=2)['ok'])
        fast = self.submit([dict(self.task(), speed=3)], expect=2)
        self.assertEqual(fast['result']['status'], 'REJECTED')
        self.assertEqual(fast['result']['stage'], 'PLAN_VALIDATION')
        self.assertEqual(self.tool('task_status', {})['result']['tasks'][0]['state'], 'PENDING')


if __name__ == '__main__':
    unittest.main()
