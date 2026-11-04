"""Isolated W2 acceptance receiver, loopback only; use authenticated SSH tunnel.
Separate from the production UI. GET page shows persisted demo incidents.
"""
from http.server import BaseHTTPRequestHandler,HTTPServer
from contextlib import closing
import json
import sqlite3
try:
    from .human_control import Ledger,read_key
except ImportError:
    from human_control import Ledger,read_key

def unique_object(pairs):
    obj={}
    for key,value in pairs:
        if key in obj:raise ValueError('duplicate key')
        obj[key]=value
    return obj

def validate_notice(obj):
    if not isinstance(obj,dict):raise ValueError('object')
    event=obj['event'];assessment=obj['assessment']
    if not isinstance(event,dict) or not isinstance(assessment,dict):raise ValueError('envelope')
    for key in ('event_id','robot_id','tag_id'):
        if not isinstance(event.get(key),str) or not 0<len(event[key])<=128:raise ValueError(key)
    rev=event.get('revision')
    if type(rev) is not int or rev<1 or event.get('mode') not in ('replay','tag_demo'):raise ValueError('replay revision')
    if obj['notification_id']!=f"{event['event_id']}:{rev}":raise ValueError('notice binding')
    score=assessment.get('score');decision=assessment.get('decision')
    if type(score) is not int or not 0<=score<=100:raise ValueError('score')
    if decision not in ('AUTO','HUMAN_REVIEW','IMMEDIATE_HUMAN'):raise ValueError('decision')
    if obj.get('human_status')!=('NOT_REQUIRED' if decision=='AUTO' else 'REQUIRED'):raise ValueError('human status')
    if obj.get('execution')!='NONE':raise ValueError('execution')

def make_server(path, port=0, bind='127.0.0.1', allow_peer=None, control_key=None):
    if bind!='127.0.0.1' and not allow_peer:
        raise ValueError('LAN replay receiver requires an explicit peer allowlist')
    ledger=Ledger(path,control_key) if control_key else None
    class Handler(BaseHTTPRequestHandler):
        def allowed(self):
            if allow_peer and self.client_address[0] not in allow_peer:
                self.send_error(403);return False
            return True
        def setup(self):
            super().setup();self.connection.settimeout(5)
        def log_message(self,*args): pass
        def do_GET(self):
            if not self.allowed():return
            if self.path=='/human-actions' and ledger:
                data=ledger.next_envelope().encode();mime='application/json; charset=utf-8'
            elif self.path=='/incidents':
                with closing(sqlite3.connect(path)) as db:
                    db.execute('CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
                    rows=db.execute('SELECT body FROM incidents ORDER BY rowid DESC LIMIT 50').fetchall()
                notices=[json.loads(r[0]) for r in rows]
                if ledger:
                    for notice in notices:notice['human_workflow']=ledger.state_of(notice['notification_id'])
                data=json.dumps(notices,ensure_ascii=False).encode()
                mime='application/json; charset=utf-8'
            elif self.path=='/':
                data='''<!doctype html><meta charset="utf-8"><title>W2 告警验收</title>
<style>body{font:18px sans-serif;background:#eef4f8;color:#123;margin:32px;max-width:1000px}article{padding:18px;margin:14px 0;background:white;border-left:8px solid #168}article.urgent{border-color:#d32}small{display:block;overflow-wrap:anywhere;color:#456}h2{margin:4px 0}#status{font-weight:bold}</style>
<h1>水利巡检 · W2告警验收</h1><p>独立测试接收端｜演示/回放事件｜不控制车辆</p>
<p id="status">正在查询平台持久记录…</p><main id="events"></main>
<script>async function refresh(){try{const r=await fetch('/incidents');if(!r.ok)throw Error();const list=await r.json();document.querySelector('#status').textContent='平台已持久接收 '+list.length+' 条通知（最多显示50条）；接收不等于人工已接单';const root=document.querySelector('#events');root.replaceChildren();for(const n of list){const a=document.createElement('article');a.className=n.assessment.decision==='IMMEDIATE_HUMAN'?'urgent':'';const h=document.createElement('h2');h.textContent=n.event.tag_id+' · '+n.assessment.score+'分 · '+(a.className?'立即请求人工':n.assessment.decision==='HUMAN_REVIEW'?'需要人工复核':'未越即时人工阈值');const p=document.createElement('p');p.textContent='来源：'+n.event.mode+' / '+n.event.robot_id+'；人工状态：'+(n.human_workflow?.state||n.human_status);const s=document.createElement('small');s.textContent=n.notification_id;a.append(h,p,s);root.append(a)}}catch(e){document.querySelector('#status').textContent='连接中断：当前无法确认最新通知'}}refresh();setInterval(refresh,2000)</script>'''.encode()
                mime='text/html; charset=utf-8'
            else: self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(data)
        def do_POST(self):
            if not self.allowed():return
            if self.path=='/human-results' and ledger:
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2048:raise ValueError('size')
                    result=ledger.receive(json.loads(self.rfile.read(length).decode(),object_pairs_hook=unique_object))
                    data=json.dumps(result).encode();self.send_response(200)
                    self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                    self.end_headers();self.wfile.write(data)
                except (ValueError,TypeError,KeyError,UnicodeError):self.send_error(400)
                except sqlite3.Error:self.send_error(503)
                return
            if self.path!='/incidents': self.send_error(404); return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8192: raise ValueError('size')
                raw=self.rfile.read(length).decode()
                obj=json.loads(raw,object_pairs_hook=unique_object);validate_notice(obj)
                key=obj['notification_id']
                if not isinstance(key,str) or not 0<len(key)<=256: raise ValueError('id')
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('PRAGMA synchronous=FULL')
                    db.execute('CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
                    old=db.execute('SELECT body FROM incidents WHERE id=?',(key,)).fetchone()
                    if old and old[0]!=raw: raise ValueError('payload collision')
                    db.execute('INSERT OR IGNORE INTO incidents VALUES(?,?)',(key,raw))
                ack=json.dumps({'notification_id':key,'persisted':True}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(ack))); self.end_headers(); self.wfile.write(ack)
            except (ValueError,KeyError,TypeError,UnicodeError,OSError): self.send_error(400)
            except sqlite3.Error: self.send_error(503)
    return HTTPServer((bind,port),Handler)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--port',type=int,default=0)
    p.add_argument('--bind',default='127.0.0.1');p.add_argument('--allow-peer',action='append')
    p.add_argument('--control-key-file')
    args=p.parse_args(); server=make_server(args.db,args.port,args.bind,args.allow_peer,read_key(args.control_key_file) if args.control_key_file else None)
    print(f'ISOLATED W2 ACCEPTANCE http://{args.bind}:{server.server_port}/incidents',flush=True)
    server.serve_forever()
