import json
from contextlib import closing
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from host.operator_server import make_operator_server

class OperatorHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name)/'platform.sqlite'
        self.server = make_operator_server(self.db, secrets.token_bytes(32))
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        with urlopen(self.base, timeout=3) as r:
            self.html = r.read().decode()
        self.token = re.search("const csrf='([^']+)'", self.html)[1]
        obj = dict(notification_id='http-event:1', event=dict(event_id='http-event',revision=1,robot_id='S1',tag_id='D_TAG_1',mode='replay'),
                   assessment=dict(score=92,decision='IMMEDIATE_HUMAN'),human_status='REQUIRED',escalation_score=92,source='HOST_NATIVE_C_TRANSPORT_TEST')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO incidents VALUES(?,?)', ('http-event:1',json.dumps(obj)))
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def post(self, overrides=None, headers=None):
        body=dict(request_id='request-1',event_id='http-event',revision=1,step='CLAIM',actor='tester',note='Replay claim',verified=False)
        body.update(overrides or {})
        h={'Content-Type':'application/json','Origin':self.base,'X-Spine-Operator':self.token}
        h.update(headers or {})
        request=Request(self.base+'/actions',json.dumps(body).encode(),h)
        try:
            with urlopen(request,timeout=3) as r:return r.status,json.load(r)
        except HTTPError as r:
            with r:return r.code,json.load(r)
    def test_browser_session_and_version_checks(self):
        self.assertEqual(self.post(headers={'X-Spine-Operator':'bad'})[0],403)
        self.assertEqual(self.post(headers={'Origin':'https://unrelated.example'})[0],403)
        self.assertEqual(self.post(dict(revision=2))[0],409)
        self.assertEqual(self.post()[0],202)
        self.assertEqual(self.post()[1]['phase'],'QUEUED')
        with urlopen(self.base+'/operations') as r:view=json.load(r)
        self.assertEqual(view[0]['human_state'],'REQUIRED')
        self.assertEqual(view[0]['waiting']['step'],'CLAIM')
    def test_cannot_skip_handling_or_omit_recheck(self):
        self.assertEqual(self.post(dict(step='CLOSE',verified=False))[0],400)
        self.assertEqual(self.post(dict(step='CLOSE',verified=True))[0],409)
        self.assertEqual(self.post(dict(actor='invalid actor'))[0],400)
        self.assertIn('复核通过并关闭',self.html)
