"""Real loopback HTTP tests against the actual native sender/store CLI."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from contextlib import contextmanager

BIN=os.environ.get('SPINE_CLI');FAULT=os.environ.get('SPINE_FAULT_CLI')

@unittest.skipUnless(BIN,'set SPINE_CLI')
class Delivery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=self.root/'db';self.store.mkdir();self.received=[]
        self.ingest(1)
    def tearDown(self):self.tmp.cleanup()
    def ingest(self,rev):
        e=dict(event_id='delivery-test',robot_id='S2',tag_id='D_TAG_2',revision=rev,
               policy_version='spine-v2',mode='replay',fresh=True,
               factors=dict(consequence=5,urgency=5,exposure=4,spread=3))
        p=self.root/'in.json';p.write_text(json.dumps(e))
        r=subprocess.run([BIN,'--ingest',str(p),str(self.store)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        return json.loads(r.stdout)
    def pending(self):
        r=subprocess.run([BIN,'--pending',str(self.store)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def send(self,endpoint,binary=BIN,env=None):
        return subprocess.run([binary,'--deliver',str(self.store),endpoint],
                              capture_output=True,text=True,timeout=10,env=env)
    @contextmanager
    def server(self,mode='good',callback=None):
        received=self.received
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                obj=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(obj)
                if callback:callback()
                ack=dict(notification_id=obj['notification_id'],persisted=True)
                if mode=='wrong-id':ack['notification_id']='wrong'
                if mode=='false':ack['persisted']=False
                if mode=='string':ack['persisted']='true'
                body=json.dumps(ack).encode()
                if mode=='duplicate':body=body[:-1]+b',"persisted":false}'
                if mode=='trailing':body+=b' {}'
                if mode=='nul':body=body.replace(b'delivery-test:1',b'delivery-test:1\\u0000extra')
                self.send_response(204 if mode=='204' else 200)
                if mode=='chunked':self.send_header('Transfer-Encoding','chunked')
                if mode!='missing-length':self.send_header('Content-Length',str(3000 if mode=='huge' else len(body)))
                if mode=='double-length':self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                try:
                    if mode=='split':
                        for i in range(0,len(body),3):self.wfile.write(body[i:i+3]);self.wfile.flush()
                    else:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:yield f'127.0.0.1:{server.server_port}'
        finally:server.shutdown();server.server_close();thread.join()
    def test_valid_ack_and_no_second_send(self):
        with self.server('split') as endpoint:
            r=self.send(endpoint);self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads(r.stdout)['status'],'DELIVERED')
            self.assertTrue(self.pending()[0]['delivered'])
            self.assertTrue(self.pending()[0]['pending']) # Human work remains required.
            self.assertEqual(self.ingest(1)['delivery_status'],'DELIVERED')
            r=self.send(endpoint);self.assertEqual(json.loads(r.stdout)['status'],'EMPTY')
            self.assertEqual(len(self.received),1)
    def test_bad_acks_keep_pending(self):
        before=(self.store/'state.json').read_bytes()
        for mode in ('wrong-id','false','string','duplicate','trailing','nul','204',
                     'chunked','missing-length','huge','double-length'):
            with self.subTest(mode=mode),self.server(mode) as endpoint:
                r=self.send(endpoint);self.assertNotEqual(r.returncode,0)
                self.assertEqual(json.loads(r.stdout)['status'],'RETRY_PENDING')
                self.assertFalse(json.loads(r.stdout)['remote_ack'])
                self.assertEqual((self.store/'state.json').read_bytes(),before)
    def test_offline_then_retry(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        r=self.send(f'127.0.0.1:{port}');self.assertNotEqual(r.returncode,0)
        self.assertFalse(self.pending()[0]['delivered'])
        with self.server() as endpoint:self.assertEqual(self.send(endpoint).returncode,0)
    def test_new_revision_during_send_not_marked_delivered(self):
        with self.server(callback=lambda:self.ingest(2)) as endpoint:
            r=self.send(endpoint);self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads(r.stdout)['status'],'ACK_FOR_OLDER_REVISION')
        row=self.pending()[0];self.assertEqual(row['event']['revision'],2)
        self.assertFalse(row['delivered'])
        with self.server() as endpoint:self.assertEqual(self.send(endpoint).returncode,0)
    @unittest.skipUnless(FAULT,'set SPINE_FAULT_CLI')
    def test_remote_ack_local_sync_failure_is_retryable(self):
        with self.server() as endpoint:
            r=self.send(endpoint,FAULT,dict(os.environ,SP_TEST_FSYNC_FAIL='1'))
            self.assertNotEqual(r.returncode,0)
            self.assertTrue(json.loads(r.stdout)['remote_ack'])
            self.assertFalse(self.pending()[0]['delivered'])
            self.assertEqual(self.send(endpoint).returncode,0)
            self.assertEqual(self.received[0],self.received[1])
    def test_receiver_durable_idempotence(self):
        from host.receiver import make_server
        import sqlite3
        receiver=make_server(self.root/'platform.sqlite')
        thread=threading.Thread(target=receiver.serve_forever,daemon=True);thread.start()
        endpoint=f'127.0.0.1:{receiver.server_port}'
        try:
            r=self.send(endpoint,FAULT or BIN,dict(os.environ,SP_TEST_FSYNC_FAIL='1'))
            if FAULT:self.assertNotEqual(r.returncode,0)
            self.assertEqual(self.send(endpoint).returncode,0)
            with sqlite3.connect(self.root/'platform.sqlite') as db:
                self.assertEqual(db.execute('SELECT count(*) FROM incidents').fetchone()[0],1)
        finally:receiver.shutdown();receiver.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
