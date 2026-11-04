"""Actual C foreground worker, locks and automatic recovery (host only)."""
import json, os, subprocess, threading, time, unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
import test_delivery_cli as delivery
BIN=delivery.BIN

@unittest.skipUnless(BIN, 'set SPINE_CLI')
class Watch(unittest.TestCase):
    setUp=delivery.Delivery.setUp
    tearDown=delivery.Delivery.tearDown
    ingest=delivery.Delivery.ingest
    pending=delivery.Delivery.pending
    server=delivery.Delivery.server
    def start(self, endpoint, cycles=None):
        cmd=[BIN,'--watch',str(self.store),endpoint]
        if cycles is not None: cmd.append(str(cycles))
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.addCleanup(self.stop,p)
        self.assertEqual(json.loads(p.stdout.readline())['watch'],'STARTED')
        return p
    def stop(self,p):
        if p.poll() is None: p.terminate()
        try:p.communicate(timeout=8)
        except subprocess.TimeoutExpired:p.kill();p.communicate()
    def until_delivered(self):
        end=time.monotonic()+9
        while time.monotonic()<end:
            r=subprocess.run([BIN,'--pending',str(self.store)],capture_output=True,text=True)
            if r.returncode==0 and json.loads(r.stdout)[0]['delivered']:return
            self.assertIn(r.returncode,(0,3),r.stderr)
            time.sleep(.1)
        self.fail('worker did not deliver')
    def test_new_event_while_idle_and_single_owner(self):
        with self.server() as endpoint:
            p=self.start(endpoint)
            self.until_delivered()
            other=subprocess.run([BIN,'--watch',str(self.store),endpoint,'1'],capture_output=True,text=True)
            self.assertEqual(other.returncode,3)
            self.ingest(2);self.until_delivered()
            time.sleep(2.2)
            self.assertEqual(len(self.received),2)
            self.stop(p)
            # Kernel releases owner lock after termination. Empty bounded watch is quiet.
            r=subprocess.run([BIN,'--watch',str(self.store),endpoint,'1'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(len(r.stdout.splitlines()),1)
    def test_offline_then_recovery_without_manual_deliver(self):
        received=self.received
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                obj=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(obj)
                body=json.dumps(dict(notification_id=obj['notification_id'],persisted=True)).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
        server=HTTPServer(('127.0.0.1',0),Handler)
        endpoint=f'127.0.0.1:{server.server_port}'
        port=server.server_port;server.server_close()
        p=self.start(endpoint)
        self.assertEqual(json.loads(p.stdout.readline())['status'],'RETRY_PENDING')
        self.assertFalse(self.pending()[0]['delivered'])
        server=HTTPServer(('127.0.0.1',port),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:self.until_delivered();self.assertEqual(len(received),1)
        finally:server.shutdown();server.server_close();thread.join()
    def test_corrupt_store_stops_and_preserves(self):
        state=self.store/'state.json';state.write_text('broken')
        p=self.start('127.0.0.1:1',1)
        p.communicate(timeout=3)
        self.assertEqual(p.returncode,3)
        self.assertEqual(state.read_text(),'broken')

    def test_transient_store_lock_does_not_stop_worker(self):
        import fcntl
        with self.server() as endpoint:
            with (self.store/'lock').open('r+') as locked:
                fcntl.lockf(locked,fcntl.LOCK_EX)
                worker=self.start(endpoint)
                self.assertEqual(json.loads(worker.stdout.readline())['status'],'RETRY_PENDING')
                self.assertIsNone(worker.poll())
            self.until_delivered()

    def test_invalid_endpoint_never_starts(self):
        for endpoint in ['8.8.8.8:80','127.0.0.1:0','localhost:80','10.1.1.1:99999','10.1.1.1:80;reboot']:
            r=subprocess.run([BIN,'--watch',str(self.store),endpoint,'1'],capture_output=True,text=True,timeout=2)
            self.assertEqual(r.returncode,2)
            self.assertEqual(r.stdout,'')
