"""Run against the actual native CLI; no Python scoring substitute."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BIN = os.environ.get('SPINE_CLI')

@unittest.skipUnless(BIN, 'set SPINE_CLI to compiled native executable')
class Ingress(unittest.TestCase):
    def event(self):
        return dict(event_id='test-1',robot_id='S1',tag_id='D_TAG_1',revision=1,
                    policy_version='spine-v2',mode='replay',fresh=True,
                    factors=dict(consequence=5,urgency=5,exposure=4,spread=3))

    def run_event(self, event):
        raw=event if isinstance(event,str) else json.dumps(event)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'event.json'; p.write_text(raw,encoding='utf-8')
            return subprocess.run([BIN,'--event',str(p)],capture_output=True,text=True)

    def test_high_score(self):
        r=self.run_event(self.event());self.assertEqual(r.returncode,0,r.stderr)
        o=json.loads(r.stdout);self.assertEqual(o['score'],92)
        self.assertEqual(o['decision'],'IMMEDIATE_HUMAN')
        self.assertEqual(o['source'],'REPLAY_UNAUTHENTICATED')
        self.assertFalse(o['motion']);self.assertFalse(o['durable_ack'])

    def test_strict_threshold_unknown_and_stale(self):
        e=self.event();e['factors']=dict(consequence=5,urgency=5,exposure=0,spread=0)
        self.assertEqual(json.loads(self.run_event(e).stdout)['decision'],'AUTO')
        e['factors']={}
        self.assertEqual(json.loads(self.run_event(e).stdout)['decision'],'HUMAN_REVIEW')
        e=self.event();e['fresh']=False
        self.assertEqual(json.loads(self.run_event(e).stdout)['decision'],'IMMEDIATE_HUMAN')
        e['factors']=dict(consequence=1,urgency=1,exposure=0,spread=0)
        self.assertEqual(json.loads(self.run_event(e).stdout)['decision'],'HUMAN_REVIEW')

    def test_bad_envelopes(self):
        for k,v in [('mode','live'),('revision',True),('revision',1.5),
                    ('policy_version','other'),('robot_id',''),('fresh',1)]:
            e=self.event();e[k]=v
            with self.subTest(k=k,v=v):self.assertNotEqual(self.run_event(e).returncode,0)
        e=self.event();e['factors']['consequence']=6
        self.assertNotEqual(self.run_event(e).returncode,0)

    def test_duplicate_trailing_oversize_nul(self):
        raw=json.dumps(self.event())
        for bad in ['{"event_id":"duplicate",'+raw[1:],raw+' {}',
                    raw.replace('"S1"','"S1\\u0000suffix"'),raw+' '*4097,
                    '['*40+'0'+']'*40]:
            self.assertNotEqual(self.run_event(bad).returncode,0)

if __name__=='__main__':unittest.main()
