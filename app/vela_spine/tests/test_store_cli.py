"""Actual C durable store across separate processes; Linux host fault injection."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BIN=os.environ.get('SPINE_CLI')
FAULT=os.environ.get('SPINE_FAULT_CLI')

@unittest.skipUnless(BIN,'set SPINE_CLI')
class Store(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=self.root/'store';self.store.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def event(self,rev=1,values=(1,1,1,1),eid='e1'):
        return dict(event_id=eid,robot_id='S1',tag_id='D_TAG_1',revision=rev,
                    policy_version='spine-v2',mode='replay',fresh=True,
                    factors=dict(zip(('consequence','urgency','exposure','spread'),values)))
    def ingest(self,e,binary=None,env=None):
        p=self.root/'input.json';p.write_text(json.dumps(e),encoding='utf-8')
        return subprocess.run([binary or BIN,'--ingest',str(p),str(self.store)],
                              capture_output=True,text=True,env=env)
    def ok(self,e):
        r=self.ingest(e);self.assertEqual(r.returncode,0,r.stderr)
        return json.loads(r.stdout)
    def pending(self):
        r=subprocess.run([BIN,'--pending',str(self.store)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_versions_and_latch(self):
        a=self.ok(self.event());self.assertEqual(a['status'],'ACCEPTED_PERSISTED')
        self.assertTrue(a['durable_ack']);self.assertEqual(a['ack_scope'],'LOCAL_STORAGE_ONLY')
        self.assertEqual(self.pending(),[])
        reordered=dict(reversed(list(self.event().items())))
        self.assertEqual(self.ok(reordered)['status'],'DUPLICATE')
        self.assertNotEqual(self.ingest(self.event(values=(5,5,4,3))).returncode,0)
        a=self.ok(self.event(2,(5,5,4,3)));self.assertEqual(a['decision'],'IMMEDIATE_HUMAN')
        a=self.ok(self.event());self.assertEqual(a['status'],'STALE_IGNORED');self.assertFalse(a['durable_ack'])
        a=self.ok(self.event(3));self.assertEqual(a['decision'],'IMMEDIATE_HUMAN')
        self.assertEqual(a['current_decision'],'AUTO');self.assertTrue(a['latched'])
        self.assertEqual(a['delivery_status'],'PENDING');self.assertEqual(len(self.pending()),1)
        self.assertEqual(self.pending()[0]['escalation_event']['revision'],2)
        self.assertEqual(self.pending()[0]['escalation_score'],92)
        a=self.ok(self.event(3));self.assertEqual(a['status'],'DUPLICATE')
        self.assertEqual(len(self.pending()),1)
    def test_identity_cannot_change(self):
        self.ok(self.event());e=self.event(2);e['robot_id']='S2'
        self.assertNotEqual(self.ingest(e).returncode,0)
        e=self.event(2);e['tag_id']='M_TAG_1';self.assertNotEqual(self.ingest(e).returncode,0)
    def test_priority_and_capacity(self):
        e=self.event(eid='review');e['factors']={};self.ok(e)
        self.ok(self.event(values=(5,5,4,3),eid='urgent'))
        self.assertEqual([x['event']['event_id'] for x in self.pending()],['urgent','review'])
        for i in range(30):self.ok(self.event(eid='auto-'+str(i)))
        before=(self.store/'state.json').read_bytes()
        self.assertNotEqual(self.ingest(self.event(eid='over-capacity')).returncode,0)
        self.assertEqual((self.store/'state.json').read_bytes(),before)
        self.assertEqual(self.ok(self.event(eid='auto-0'))['status'],'DUPLICATE')
    def test_corrupt_and_orphan_snapshot(self):
        self.ok(self.event(values=(5,5,4,3)))
        (self.store/'state.tmp').write_text('interrupted write')
        self.assertEqual(len(self.pending()),1)
        p=self.store/'state.json';s=p.read_text();s=s.replace('"revision":1','"revision":2')
        p.write_text(s);before=p.read_bytes()
        r=self.ingest(self.event(3));self.assertNotEqual(r.returncode,0);self.assertFalse(r.stdout.strip())
        self.assertEqual(p.read_bytes(),before)
    def test_missing_directory_fails(self):
        self.store=self.root/'missing'
        r=self.ingest(self.event());self.assertNotEqual(r.returncode,0);self.assertFalse(r.stdout.strip())
    def test_process_lock(self):
        import fcntl
        with (self.store/'lock').open('w') as f:
            fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            r=self.ingest(self.event());self.assertNotEqual(r.returncode,0);self.assertFalse(r.stdout.strip())
        self.assertEqual(self.ok(self.event())['status'],'ACCEPTED_PERSISTED')
    @unittest.skipUnless(FAULT,'set SPINE_FAULT_CLI for fsync fault test')
    def test_sync_failure_no_ack_no_overwrite(self):
        self.ok(self.event());before=(self.store/'state.json').read_bytes()
        env=dict(os.environ,SP_TEST_FSYNC_FAIL='1')
        r=self.ingest(self.event(2,(5,5,4,3)),FAULT,env)
        self.assertNotEqual(r.returncode,0);self.assertFalse(r.stdout.strip())
        self.assertEqual((self.store/'state.json').read_bytes(),before)
        self.assertFalse((self.store/'state.tmp').exists())
        self.assertEqual(self.ok(self.event(2,(5,5,4,3)))['status'],'ACCEPTED_PERSISTED')

if __name__=='__main__':unittest.main(verbosity=2)
