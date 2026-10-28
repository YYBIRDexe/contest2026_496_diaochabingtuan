"""Board-side task ledger: real C CLI against the loopback fleet simulator.

Covers the A/B/C contract: persisted plans, single ownership, executor ACK is not
completion, risk holds survive a human CLOSE, stop needs executor confirmation.
"""
import json
import os
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.request import Request, urlopen

from host.robot_simulator import Fleet, SCHEMA, make_server

BIN = os.environ.get('SPINE_CLI')
FAULT = os.environ.get('SPINE_FAULT_CLI')


@unittest.skipUnless(BIN, 'set SPINE_CLI')
class TaskLedger(unittest.TestCase):
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

    def plan(self, version=1, tasks=None, plan_id='p1', expect=0):
        body = dict(schema='spine-plan-v1', plan_id=plan_id, version=version,
                    tasks=tasks if tasks is not None else [dict(task_id='T1', tag_id='D1', robot_id='S1', revision=1)])
        path = self.root / ('plan-%d.json' % version)
        path.write_text(json.dumps(body), encoding='utf-8')
        return self.run_cli('--task-plan', str(path), str(self.ledger), expect=expect)

    def view(self, task=None, expect=0):
        args = ['--task-view', str(self.ledger)] + ([task] if task else [])
        return self.run_cli(*args, expect=expect)

    def dispatch(self, endpoint=None, expect=0):
        return self.run_cli('--task-dispatch', str(self.ledger), endpoint or self.endpoint, expect=expect)

    def poll(self, expect=0):
        return self.run_cli('--task-poll', str(self.ledger), self.endpoint, expect=expect)

    def stop(self, task, reason=None, expect=0):
        args = ['--task-stop', str(self.ledger), task] + ([reason] if reason else [])
        return self.run_cli(*args, expect=expect)

    def sync(self, expect=0):
        return self.run_cli('--task-stop-sync', str(self.ledger), self.endpoint, expect=expect)

    def ingest(self, tag='D1', values=(5, 5, 4, 3), revision=2, event='e1'):
        payload = dict(event_id=event, robot_id='S1', tag_id=tag, revision=revision,
                       policy_version='spine-v2', mode='replay', fresh=True,
                       factors=dict(zip(('consequence', 'urgency', 'exposure', 'spread'), values)))
        path = self.root / ('event-%s.json' % event)
        path.write_text(json.dumps(payload), encoding='utf-8')
        return self.run_cli('--ingest', str(path), str(self.ledger))

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

    def test_task_worker_dispatches_and_reacts_to_risk(self):
        self.plan()
        cmd=[BIN,'--task-watch',str(self.ledger),self.endpoint,'1']
        first=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        self.assertEqual(first.returncode,0,first.stderr)
        self.assertEqual(self.fleet_task('T1')[0]['state'],'ACCEPTED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'DISPATCHED')
        self.ingest(tag='D1')
        second=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(self.fleet_task('T1')[0]['state'],'STOP_CONFIRMED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_CONFIRMED')

    def test_mixed_explicit_and_auto_assignments_use_all_three_robots(self):
        result=self.plan(tasks=[dict(task_id='T1',tag_id='D1',robot_id='S1',revision=1),
                                dict(task_id='T2',tag_id='D2',robot_id='AUTO',revision=1)])
        owners={task['robot_id'] for task in result['tasks']}
        self.assertEqual(len(owners),2)
        self.assertIn('S1',owners)

    def test_generated_command_id_must_fit_protocol_limit(self):
        valid='a'*55
        self.plan(tasks=[dict(task_id=valid,tag_id='D1',robot_id='S1',revision=1)])
        self.assertEqual(self.dispatch()['tasks'][0]['status'],'DISPATCHED')
        rejected=self.plan(version=2,plan_id='p2',
            tasks=[dict(task_id='b'*56,tag_id='D2',robot_id='S2',revision=1)],expect=2)
        self.assertEqual(rejected['status'],'REJECTED')
        higher=self.plan(version=2,plan_id='p2',
            tasks=[dict(task_id='c'*55,tag_id='D2',robot_id='S2',revision=10)],expect=2)
        self.assertEqual(higher['status'],'REJECTED')
        self.assertEqual(self.view(valid)['tasks'][0]['state'],'DISPATCHED')

    def test_auto_assignment_excludes_existing_busy_robot(self):
        self.plan();self.dispatch()
        result=self.plan(version=2,plan_id='p2',tasks=[dict(
            task_id='T2',tag_id='D2',robot_id='AUTO',revision=1)])
        allocated={t['task_id']:t['robot_id'] for t in result['tasks']}
        self.assertEqual(allocated['T1'],'S1')
        self.assertIn(allocated['T2'],('S2','S3'))
        self.assertEqual(self.dispatch()['tasks'][0]['status'],'DISPATCHED')

    def test_auto_assignment_excludes_pending_and_refuses_full_fleet(self):
        self.plan(tasks=[dict(task_id='T1',tag_id='D1',robot_id='S1',revision=1),
                         dict(task_id='T2',tag_id='D2',robot_id='S2',revision=1)])
        result=self.plan(version=2,plan_id='p2',tasks=[dict(
            task_id='T3',tag_id='D3',robot_id='AUTO',revision=1)])
        self.assertEqual(next(t for t in result['tasks'] if t['task_id']=='T3')['robot_id'],'S3')
        rejected=self.plan(version=3,plan_id='p3',tasks=[dict(
            task_id='T4',tag_id='D4',robot_id='AUTO',revision=1)],expect=2)
        self.assertEqual(rejected['status'],'REJECTED')
        self.assertEqual(self.view('T3')['tasks'][0]['state'],'PENDING')

    def test_ack_is_not_completion(self):
        planned = self.plan()
        self.assertEqual(planned['status'], 'PLAN_PERSISTED')
        self.assertEqual(planned['previous_plan_version'], 0)
        self.assertEqual(planned['stored_plan_version'], 1)
        self.assertEqual(planned['tasks'][0]['state'], 'PENDING')
        self.assertFalse(planned['motion'])
        self.assertEqual(planned['ack_scope'], 'LOCAL_STORAGE_ONLY')
        dispatched = self.dispatch()
        self.assertEqual(dispatched['status'], 'DISPATCH_STEP')
        self.assertEqual(dispatched['tasks'][0]['status'], 'DISPATCHED')
        self.assertEqual(self.fleet_task('T1')[0]['state'], 'ACCEPTED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'DISPATCHED')
        polled = self.poll()
        self.assertEqual(polled['tasks'][0]['local_state'], 'DISPATCHED')
        self.assertEqual(polled['tasks'][0]['note'], 'DUPLICATE_REPORT')
        self.report('S1', 'T1', 1, 'RUNNING', 1)
        self.assertEqual(self.poll()['tasks'][0]['local_state'], 'RUNNING')
        self.report('S1', 'T1', 1, 'COMPLETED', 2)
        done = self.poll()
        self.assertEqual(done['tasks'][0]['local_state'], 'COMPLETED')
        self.assertEqual(done['tasks'][0]['note'], 'REPORT_APPLIED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'COMPLETED')

    def test_plan_versions_and_single_ownership(self):
        self.assertEqual(self.plan()['status'], 'PLAN_PERSISTED')
        duplicate = self.plan()
        self.assertEqual(duplicate['status'], 'DUPLICATE_PLAN')
        self.assertEqual(duplicate['tasks'][0]['state'], 'PENDING')
        conflict = self.plan(tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=2)], plan_id='p2',
                            expect=2)
        self.assertEqual(conflict['status'], 'PLAN_VERSION_CONFLICT')
        double = self.plan(version=2, tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=2)],
                           expect=2)
        self.assertEqual(double['status'], 'DOUBLE_AUTHORIZATION_REJECTED')
        stale = self.plan(version=1, plan_id='p1', tasks=[dict(task_id='T2', tag_id='D3', robot_id='S2', revision=1)], expect=2)
        self.assertEqual(stale['status'], 'PLAN_VERSION_CONFLICT')
        bad = self.plan(version=3, tasks=[dict(task_id='T3', tag_id='D1', robot_id='S1', revision=1),
                                         dict(task_id='T4', tag_id='D1', robot_id='S2', revision=1)], expect=2)
        self.assertEqual(bad['status'], 'REJECTED')
        self.assertEqual(bad['stage'], 'PLAN_VALIDATION')

    def test_network_failure_keeps_dispatch_uncertain(self):
        self.plan(tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=1)])
        failed = self.dispatch('127.0.0.1:9', expect=4)
        self.assertEqual(failed['status'], 'PARTIAL_NETWORK_ERROR')
        self.assertEqual(failed['tasks'][0]['status'], 'UNREACHABLE')
        self.assertFalse(failed['tasks'][0]['dispatched'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'DISPATCHING')
        self.assertEqual(self.fleet_task('T1'), [])

    @unittest.skipUnless(FAULT, 'set SPINE_FAULT_CLI')
    def test_poll_sync_failure_is_not_reported_as_success(self):
        self.plan();self.dispatch();self.report('S1','T1',1,'RUNNING',1)
        path=self.ledger/'tasks.json';before=path.read_bytes()
        result=subprocess.run([FAULT,'--task-poll',str(self.ledger),self.endpoint],
            capture_output=True,text=True,env=dict(os.environ,SP_TEST_FSYNC_FAIL='1'))
        self.assertEqual(result.returncode,3,result.stdout+result.stderr)
        self.assertFalse(result.stdout.strip())
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.poll()['tasks'][0]['local_state'],'RUNNING')

    @unittest.skipUnless(FAULT, 'set SPINE_FAULT_CLI')
    def test_dispatch_sync_failure_retries_without_false_success(self):
        self.plan()
        result=subprocess.run([FAULT,'--task-dispatch',str(self.ledger),self.endpoint],
            capture_output=True,text=True,env=dict(os.environ,SP_TEST_FSYNC_FAIL_AT='2'))
        self.assertEqual(result.returncode,3,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PARTIAL_STORAGE_ERROR')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'DISPATCHING')
        self.assertEqual(self.fleet_task('T1')[0]['state'],'ACCEPTED')
        self.assertEqual(self.dispatch()['tasks'][0]['status'],'DISPATCHED')

    @unittest.skipUnless(FAULT, 'set SPINE_FAULT_CLI')
    def test_dispatch_intent_save_failure_prevents_network_send(self):
        self.plan();path=self.ledger/'tasks.json';before=path.read_bytes()
        result=subprocess.run([FAULT,'--task-dispatch',str(self.ledger),self.endpoint],
            capture_output=True,text=True,env=dict(os.environ,SP_TEST_FSYNC_FAIL='1'))
        self.assertEqual(result.returncode,3,result.stdout+result.stderr)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'PENDING')
        self.assertEqual(self.fleet_task('T1'),[])

    def test_wrong_dispatch_ack_is_an_error_without_local_authorization(self):
        self.plan();original=self.fleet.apply
        def wrong(message):
            response=original(message)
            return dict(response,task=dict(response['task'],robot_id='S2'))
        with patch.object(self.fleet,'apply',side_effect=wrong):
            result=self.dispatch(expect=4)
        self.assertEqual(result['tasks'][0]['status'],'ACK_REJECTED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'DISPATCHING')
        self.assertEqual(self.dispatch()['tasks'][0]['status'],'DISPATCHED')

    def test_wrong_command_id_ack_is_rejected_and_can_retry(self):
        self.plan();original=self.fleet.apply
        def wrong(message):
            response=original(message)
            return dict(response,command_id='wrong-command')
        with patch.object(self.fleet,'apply',side_effect=wrong):
            result=self.dispatch(expect=4)
        self.assertEqual(result['tasks'][0]['status'],'ACK_REJECTED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'DISPATCHING')
        self.assertEqual(self.dispatch()['tasks'][0]['status'],'DISPATCHED')

    def test_uncertain_dispatch_stop_requires_executor_confirmation(self):
        self.plan();original=self.fleet.apply
        def wrong(message):
            response=original(message)
            return dict(response,command_id='wrong-command')
        with patch.object(self.fleet,'apply',side_effect=wrong):
            self.dispatch(expect=4)
        self.assertEqual(self.fleet_task('T1')[0]['state'],'ACCEPTED')
        stopped=self.stop('T1')
        self.assertEqual(stopped['status'],'STOP_REQUESTED')
        self.assertFalse(stopped['robot_released'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_REQUESTED')
        self.assertEqual(self.sync()['tasks'][0]['status'],'STOP_CONFIRMED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_CONFIRMED')

    def test_risk_stops_uncertain_dispatch_even_when_acceptance_ack_is_invalid(self):
        self.plan();original=self.fleet.apply
        def risk_during_assign(message):
            response=original(message)
            if message['action']=='ASSIGN':
                self.ingest()
                return dict(response,command_id='wrong-command')
            return response
        with patch.object(self.fleet,'apply',side_effect=risk_during_assign):
            result=self.dispatch(expect=4)
        self.assertEqual(result['stops'][0]['status'],'STOP_CONFIRMED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_CONFIRMED')
        self.assertEqual(self.fleet_task('T1')[0]['state'],'STOP_CONFIRMED')

    def test_stop_during_dispatch_does_not_cancel_or_restore_authorization(self):
        self.plan();original=self.fleet.apply;stopped={}
        def stop_while_sending(message):
            stopped.update(self.stop('T1'))
            return original(message)
        with patch.object(self.fleet,'apply',side_effect=stop_while_sending):
            self.dispatch(expect=3)
        self.assertEqual(stopped['status'],'STOP_REQUESTED')
        self.assertFalse(stopped['robot_released'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_REQUESTED')
        self.assertEqual(self.fleet_task('T1')[0]['state'],'ACCEPTED')
        self.assertEqual(self.sync()['tasks'][0]['status'],'STOP_CONFIRMED')

    def test_stop_pending_completion_or_failure_does_not_release_robot(self):
        for terminal in ('COMPLETED','FAILED'):
            with self.subTest(terminal=terminal):
                # Each subcase has an independent task and robot.
                number=1 if terminal=='COMPLETED' else 2;task='T'+str(number);robot='S'+str(number)
                self.plan(version=number,tasks=[dict(task_id=task,tag_id='D'+str(number),robot_id=robot,revision=1)])
                self.dispatch();self.report(robot,task,1,'RUNNING',1);self.poll();self.stop(task)
                self.report(robot,task,1,terminal,2);polled=self.poll()
                row=self.view(task)['tasks'][0]
                self.assertEqual(row['state'],'STOP_REQUESTED')
                progress=next(item for item in polled['tasks'] if item['task_id']==task)
                self.assertEqual(progress['sequence'],2)
                self.assertEqual(progress['vehicle_state'],terminal)
                self.assertEqual(self.sync()['tasks'][0]['status'],'STOP_CONFIRMED')
                self.assertEqual(self.view(task)['tasks'][0]['state'],'STOP_CONFIRMED')

    def test_ack_with_trailing_garbage_cannot_authorize(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        self.plan()
        body=json.dumps(dict(schema=SCHEMA,command_id='assign-T1-1',persisted=True,
            ack_scope='SIMULATOR_STORAGE_ONLY',motion=False,
            task=dict(task_id='T1',robot_id='S1',revision=1,state='ACCEPTED'))).encode()+b'garbage'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            result=self.dispatch('127.0.0.1:%d'%server.server_port,expect=4)
            self.assertEqual(result['tasks'][0]['status'],'ACK_REJECTED')
            self.assertEqual(self.view('T1')['tasks'][0]['state'],'DISPATCHING')
        finally:
            server.shutdown();server.server_close();worker.join()

    def test_poll_rejects_wrong_source_and_fractional_sequence(self):
        self.plan();self.dispatch();self.report('S1','T1',1,'RUNNING',1)
        original=self.fleet.current_snapshot
        def wrong_source():return dict(original(),source='UNTRUSTED_SOURCE')
        with patch.object(self.fleet,'current_snapshot',side_effect=wrong_source):
            self.poll(expect=4)
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'DISPATCHED')
        def fractional():
            state=original();state['tasks'][0]['sequence']=1.5;return state
        with patch.object(self.fleet,'current_snapshot',side_effect=fractional):
            self.poll(expect=4)
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'DISPATCHED')
        self.assertEqual(self.poll()['tasks'][0]['local_state'],'RUNNING')

    @unittest.skipUnless(FAULT, 'set SPINE_FAULT_CLI')
    def test_stop_confirmation_sync_failure_retries_without_false_success(self):
        self.plan();self.dispatch();self.stop('T1')
        path=self.ledger/'tasks.json';before=path.read_bytes()
        result=subprocess.run([FAULT,'--task-stop-sync',str(self.ledger),self.endpoint],
            capture_output=True,text=True,env=dict(os.environ,SP_TEST_FSYNC_FAIL='1'))
        self.assertEqual(result.returncode,3,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PARTIAL_STORAGE_ERROR')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.fleet_task('T1')[0]['state'],'STOP_CONFIRMED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_REQUESTED')
        self.assertEqual(self.sync()['tasks'][0]['status'],'STOP_CONFIRMED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_CONFIRMED')

    def test_wrong_stop_ack_is_an_error_without_release(self):
        self.plan();self.dispatch();self.stop('T1');original=self.fleet.apply
        def wrong(message):
            response=original(message)
            return dict(response,task=dict(response['task'],robot_id='S2'))
        with patch.object(self.fleet,'apply',side_effect=wrong):
            result=self.sync(expect=4)
        self.assertEqual(result['tasks'][0]['status'],'ACK_REJECTED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_REQUESTED')
        self.assertEqual(self.sync()['tasks'][0]['status'],'STOP_CONFIRMED')

    def test_stop_ack_must_advance_sequence(self):
        self.plan();self.dispatch();self.report('S1','T1',1,'RUNNING',1);self.poll();self.stop('T1')
        original=self.fleet.apply
        def stale(message):
            response=original(message)
            return dict(response,task=dict(response['task'],sequence=1))
        with patch.object(self.fleet,'apply',side_effect=stale):
            result=self.sync(expect=4)
        self.assertEqual(result['tasks'][0]['status'],'ACK_REJECTED')
        self.assertEqual(self.view('T1')['tasks'][0]['state'],'STOP_REQUESTED')
        self.assertEqual(self.sync()['tasks'][0]['status'],'STOP_CONFIRMED')

    def test_late_stop_ack_cannot_release_a_new_revision(self):
        self.plan();self.dispatch();self.stop('T1');original=self.fleet.apply
        def advance_revision_while_ack_in_flight(message):
            response=original(message)
            if message['action']=='STOP' and message['revision']==1:
                self.poll()  # A parallel status read already observed the stop.
                self.plan(version=2,tasks=[dict(task_id='T1',tag_id='D1',robot_id='S1',revision=2)])
                self.dispatch();self.stop('T1')
            return response
        with patch.object(self.fleet,'apply',side_effect=advance_revision_while_ack_in_flight):
            result=self.sync(expect=4)
        self.assertEqual(result['tasks'][0]['status'],'ACK_REJECTED')
        row=self.view('T1')['tasks'][0]
        self.assertEqual(row['revision'],2)
        self.assertEqual(row['state'],'STOP_REQUESTED')
        self.assertEqual(self.fleet_task('T1')[0]['state'],'ACCEPTED')
        self.assertEqual(self.sync()['tasks'][0]['status'],'STOP_CONFIRMED')

    def test_risk_hold_survives_replan(self):
        self.plan(tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=1)])
        self.assertEqual(self.ingest()['status'], 'ACCEPTED_PERSISTED')
        held = self.dispatch()
        self.assertEqual(held['tasks'][0]['status'], 'HELD_BY_RISK')
        self.assertFalse(held['tasks'][0]['dispatched'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'PENDING')
        self.assertEqual(self.view('T1')['tasks'][0]['note'], 'HELD_BY_RISK')
        self.assertEqual(self.fleet_task('T1'), [])
        again = self.dispatch()
        self.assertEqual(again['tasks'][0]['status'], 'HELD_BY_RISK')
        double = self.plan(version=2, tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=2)],
                           expect=2)
        self.assertEqual(double['status'], 'DOUBLE_AUTHORIZATION_REJECTED')
        sibling = self.plan(version=2, tasks=[dict(task_id='T9', tag_id='D1', robot_id='S2', revision=1)])
        self.assertEqual(sibling['status'], 'PLAN_PERSISTED')
        statuses = {item['task_id']: item['status'] for item in self.dispatch()['tasks']}
        self.assertEqual(statuses, {'T1': 'HELD_BY_RISK', 'T9': 'HELD_BY_RISK'})
        self.assertEqual(self.fleet_task('T1'), [])
        self.assertEqual(self.fleet_task('T9'), [])

    def test_risk_stops_running_task(self):
        self.plan(tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=1)])
        self.dispatch()
        self.report('S1', 'T1', 1, 'RUNNING', 1)
        self.poll()
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'RUNNING')
        self.assertEqual(self.ingest()['status'], 'ACCEPTED_PERSISTED')
        stopped = self.dispatch()
        self.assertEqual(stopped['status'], 'RISK_STOPPED')
        self.assertEqual([item['task_id'] for item in stopped['stops']], ['T1'])
        self.assertEqual(stopped['stops'][0]['status'], 'STOP_CONFIRMED')
        self.assertTrue(stopped['stops'][0]['executor_confirmed'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'STOP_CONFIRMED')
        self.assertEqual(self.fleet_task('T1')[0]['state'], 'STOP_CONFIRMED')
        self.assertEqual(self.dispatch()['status'], 'NOTHING_TO_DISPATCH')

    def test_stop_requires_executor_confirmation(self):
        self.plan(tasks=[dict(task_id='T1', tag_id='D6', robot_id='S3', revision=1)])
        self.dispatch()
        self.report('S3', 'T1', 1, 'RUNNING', 1)
        self.poll()
        asked = self.stop('T1', 'risk-linkage')
        self.assertEqual(asked['status'], 'STOP_REQUESTED')
        self.assertFalse(asked['robot_released'])
        self.assertFalse(asked['executor_confirmed'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'STOP_REQUESTED')
        self.assertEqual(self.stop('T1')['status'], 'ALREADY_REQUESTED')
        confirmed = self.sync()
        self.assertEqual(confirmed['tasks'][0]['status'], 'STOP_CONFIRMED')
        self.assertTrue(confirmed['tasks'][0]['executor_confirmed'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'STOP_CONFIRMED')
        self.assertEqual(self.fleet_task('T1')[0]['state'], 'STOP_CONFIRMED')
        self.assertEqual(self.stop('T1')['status'], 'STOP_NOT_REQUIRED')
        self.plan(version=2, tasks=[dict(task_id='T2', tag_id='D6', robot_id='S3', revision=1)])
        self.assertEqual(self.dispatch()['tasks'][0]['status'], 'DISPATCHED')

    def test_pending_task_cancels_without_executor(self):
        self.plan(tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=1)])
        cancelled = self.stop('T1')
        self.assertEqual(cancelled['status'], 'CANCELLED')
        self.assertTrue(cancelled['robot_released'])
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'CANCELLED')
        self.assertEqual(self.dispatch()['status'], 'NOTHING_TO_DISPATCH')

    def test_wrong_owner_report_is_not_applied(self):
        self.plan(tasks=[dict(task_id='T1', tag_id='D1', robot_id='S1', revision=1)])
        self.dispatch()
        import sqlite3
        with sqlite3.connect(str(self.root / 'fleet.db')) as db:
            db.execute("UPDATE tasks SET revision=2 WHERE task_id='T1'")
        self.assertEqual(self.poll()['tasks'][0]['note'], 'VEHICLE_STATE_CONFLICT')
        self.assertEqual(self.view('T1')['tasks'][0]['state'], 'DISPATCHED')

    def test_corrupt_ledger_is_refused(self):
        self.plan()
        (self.ledger / 'tasks.json').write_text('{not json}', encoding='utf-8')
        self.view(expect=3)
        self.assertEqual((self.ledger / 'tasks.json').read_text(encoding='utf-8'), '{not json}')


if __name__ == '__main__':
    unittest.main()
