"""Real native persistence, controller signatures and HTTP worker closure."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
import unittest
from host.human_control import Ledger, Conflict, canonical, signed, verified
from host.receiver import make_server

BIN = os.environ.get('SPINE_CLI')
FAULT = os.environ.get('SPINE_FAULT_CLI')

@unittest.skipUnless(BIN, 'set SPINE_CLI')
class Human(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = self.root/'store'
        self.store.mkdir()
        self.key = secrets.token_bytes(32)
        (self.store/'control.key').write_text(self.key.hex())
        self.db = self.root/'platform.sqlite'
        self.ledger = Ledger(self.db, self.key)
        self.ingest()
    def tearDown(self):
        self.tmp.cleanup()
    def run_cli(self, mode, obj, binary=BIN, env=None):
        path = self.root/'input.json'
        path.write_text(canonical(obj))
        return subprocess.run([binary, mode, str(path), str(self.store)], capture_output=True, text=True, timeout=4, env=env)
    def ingest(self, rev=1, high=True):
        obj = dict(event_id='human-event', robot_id='S1', tag_id='D_TAG_1', revision=rev,
                   policy_version='spine-v2', mode='replay', fresh=True,
                   factors=dict(zip(('consequence','urgency','exposure','spread'), (5,5,4,3) if high else (1,1,1,1))))
        r = self.run_cli('--ingest', obj)
        self.assertEqual(r.returncode, 0, r.stderr)
    def row(self):
        return json.loads((self.store/'state.json').read_text())['records'][0]
    def command(self, step='CLAIM', rev=1, actor='tester', aid=None):
        return dict(schema=1, action_id=aid or secrets.token_hex(8), event_id='human-event', revision=rev,
                    step=step, actor=actor, note='Replay operator verification', verified=step=='CLOSE')
    def apply(self, command, binary=BIN, env=None, key=None):
        r = self.run_cli('--human', signed(key or self.key, canonical(command)), binary, env)
        result = verified(self.key, json.loads(r.stdout)) if r.returncode == 0 else None
        return r, result
    def test_complete_workflow_duplicate_and_restart(self):
        for step, expected in [('CLAIM','CLAIMED'),('HANDLE','HANDLED'),('CLOSE','CLOSED')]:
            cmd = self.command(step)
            r, result = self.apply(cmd)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(result['status'], 'APPLIED')
            self.assertEqual(self.row()['human']['state'], expected)
            self.assertEqual(self.row()['pending'], expected != 'CLOSED')
            self.assertEqual(self.apply(cmd)[1]['status'], 'DUPLICATE')
        self.assertEqual(self.row()['assessment']['decision'], 'IMMEDIATE_HUMAN')
        pending = subprocess.check_output([BIN, '--pending', str(self.store)], text=True)
        self.assertEqual(json.loads(pending), [])
        self.assertEqual(len(self.row()['human']['actions']), 3)
    def test_stale_close_cannot_clear_new_revision(self):
        self.apply(self.command())
        self.apply(self.command('HANDLE'))
        old_close = self.command('CLOSE')
        self.ingest(2, high=False)
        self.assertEqual(self.apply(old_close)[1]['status'], 'STALE_REJECTED')
        self.assertTrue(self.row()['pending'])
        self.assertEqual(self.row()['assessment']['score'], 20)
        self.assertEqual(self.row()['escalation_score'], 92)
        self.assertNotIn('human', self.row())
    def test_closed_event_reopens_on_new_high_revision(self):
        for step in ('CLAIM','HANDLE','CLOSE'):
            self.apply(self.command(step))
        self.ingest(2)
        self.assertTrue(self.row()['pending'])
        self.assertNotIn('human', self.row())
        self.assertEqual(self.row()['previous_human']['state'], 'CLOSED')
        self.assertEqual(self.apply(self.command(rev=2))[1]['status'], 'APPLIED')
    def test_low_revision_after_reviewed_closure_does_not_relatch(self):
        for step in ('CLAIM','HANDLE','CLOSE'):
            self.apply(self.command(step))
        self.ingest(2, high=False)
        self.assertFalse(self.row()['pending'])
        self.assertEqual(self.row()['assessment']['decision'], 'AUTO')
    def test_step_owner_and_action_id_collision(self):
        self.assertEqual(self.apply(self.command('CLOSE'))[1]['status'], 'STATE_REJECTED')
        cmd = self.command()
        self.apply(cmd)
        self.assertEqual(self.apply(self.command('HANDLE', actor='other'))[1]['status'], 'STATE_REJECTED')
        cmd['note'] = 'changed payload'
        self.assertEqual(self.apply(cmd)[1]['status'], 'STATE_REJECTED')
        bad = self.command('CLOSE');bad['verified'] = False
        self.assertEqual(self.apply(bad)[0].returncode, 2)
    def test_bad_signature_duplicate_fields_and_missing_key_fail_closed(self):
        before = (self.store/'state.json').read_bytes()
        self.assertEqual(self.apply(self.command(), key=secrets.token_bytes(32))[0].returncode, 2)
        cmd = canonical(self.command()).replace('"schema":1', '"schema":1,"schema":1')
        self.assertEqual(self.run_cli('--human', signed(self.key, cmd)).returncode, 2)
        (self.store/'control.key').unlink()
        self.assertEqual(self.apply(self.command())[0].returncode, 2)
        self.assertEqual((self.store/'state.json').read_bytes(), before)
    @unittest.skipUnless(FAULT, 'set SPINE_FAULT_CLI')
    def test_sync_failure_never_confirms_action(self):
        before = (self.store/'state.json').read_bytes()
        r, result = self.apply(self.command(), binary=FAULT, env=dict(os.environ, SP_TEST_FSYNC_FAIL='1'))
        self.assertEqual(r.returncode, 3)
        self.assertIsNone(result)
        self.assertEqual(r.stdout, '')
        self.assertEqual((self.store/'state.json').read_bytes(), before)
    @contextmanager
    def server(self):
        server = make_server(self.db, control_key=self.key)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'127.0.0.1:{server.server_port}'
        finally:
            server.shutdown();server.server_close();thread.join()
    def deliver(self, endpoint):
        r = subprocess.run([BIN, '--deliver', str(self.store), endpoint], capture_output=True, text=True, timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)
    def request(self, step='CLAIM', rev=1):
        cmd = self.command(step, rev)
        return dict(request_id=cmd['action_id'], **{k:cmd[k] for k in ('event_id','revision','step','actor','note','verified')})
    def test_platform_queues_without_claiming_board_confirmation(self):
        with self.server() as endpoint:
            self.deliver(endpoint)
        req = self.request()
        self.ledger.queue(req)
        self.assertEqual(self.ledger.view()[0]['human_state'], 'REQUIRED')
        self.assertEqual(self.ledger.queue(req)['phase'], 'QUEUED')
        with self.assertRaises(Conflict):
            self.ledger.queue(self.request())
        self.ledger = Ledger(self.db, self.key) # Simulate controller restart.
        self.assertNotEqual(self.ledger.next_envelope(), '{"empty":true}')
    def test_real_worker_applies_and_confirms_all_steps(self):
        with self.server() as endpoint:
            self.deliver(endpoint)
            worker = subprocess.Popen([BIN, '--watch', str(self.store), endpoint], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for step, expected in [('CLAIM','CLAIMED'),('HANDLE','HANDLED'),('CLOSE','CLOSED')]:
                    self.ledger.queue(self.request(step))
                    until = time.monotonic()+8
                    while time.monotonic()<until and self.ledger.view()[0]['human_state'] != expected:
                        time.sleep(.05)
                    self.assertEqual(self.ledger.view()[0]['human_state'], expected)
                self.assertFalse(self.row()['pending'])
                self.assertEqual(self.ledger.next_envelope(), '{"empty":true}')
            finally:
                worker.terminate();worker.wait(timeout=3)
    def test_inflight_old_close_is_rejected_after_new_event(self):
        with self.server() as endpoint:
            self.deliver(endpoint)
            for step in ('CLAIM','HANDLE'):
                req = self.request(step);self.ledger.queue(req)
                action = json.loads(self.ledger.next_envelope())
                r = self.run_cli('--human', action)
                self.ledger.receive(json.loads(r.stdout))
            req = self.request('CLOSE');self.ledger.queue(req)
            stale = json.loads(self.ledger.next_envelope())
            self.ingest(2, high=False);self.deliver(endpoint)
            r = self.run_cli('--human', stale)
            self.ledger.receive(json.loads(r.stdout))
            view = self.ledger.view()[0]
            self.assertEqual(view['notice']['event']['revision'], 2)
            self.assertEqual(view['human_state'], 'REQUIRED')
            self.assertTrue(self.row()['pending'])
            with self.assertRaises(Conflict):
                self.ledger.queue(self.request('CLOSE'))
    def test_forged_result_never_advances_platform(self):
        with self.server() as endpoint:
            self.deliver(endpoint)
        req = self.request();self.ledger.queue(req)
        result = dict(action_id=req['request_id'],event_id='human-event',revision=1,current_revision=1,
                      status='APPLIED',human_state='CLAIMED',pending=True)
        with self.assertRaises(ValueError):
            self.ledger.receive(signed(secrets.token_bytes(32), canonical(result)))
        self.assertEqual(self.ledger.view()[0]['human_state'], 'REQUIRED')
