"""Durable reference notification transport. Host implementation, not board firmware.

No movement commands or real emergency contacts. HTTP endpoint must explicitly
acknowledge durable storage of the matching notification ID.
"""
import json
import sqlite3
import time
import urllib.request
from .native import assess

class Outbox:
    def __init__(self, path, threshold=70):
        if type(threshold) is not int or not 0<=threshold<=100: raise ValueError('threshold')
        self.threshold=threshold
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL,
            level INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS outbox (
            id TEXT PRIMARY KEY, body TEXT NOT NULL, level INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
            delivered INTEGER NOT NULL DEFAULT 0);
        ''')

    def ingest(self, event):
        for k in ('event_id','tag_id','robot_id','policy_version','mode'):
            if not isinstance(event.get(k),str) or not 0<len(event[k])<=128: raise ValueError(k)
        if event['mode'] not in ('tag_demo','replay'): raise ValueError('unvalidated live mode')
        rev=event.get('revision')
        if type(rev) is not int or rev<1: raise ValueError('revision')
        if not isinstance(event.get('fresh'),bool): raise ValueError('fresh')
        result=assess(event.get('factors',{}),self.threshold,event['fresh'])
        level={'AUTO':0,'HUMAN_REVIEW':1,'IMMEDIATE_HUMAN':2}[result['decision']]
        canonical=json.dumps(event,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        if len(canonical.encode())>4096: raise ValueError('event too large')
        with self.db:
            old=self.db.execute('SELECT revision,body,level FROM events WHERE id=?',(event['event_id'],)).fetchone()
            if old and rev<old[0]: return {'status':'STALE_IGNORED'}
            if old and rev==old[0]:
                if old[1]!=canonical: raise ValueError('revision collision')
                return {'status':'DUPLICATE'}
            # A newer low score cannot silently retract an already urgent event.
            effective=max(level,old[2] if old else 0)
            result['current_decision']=result['decision']
            result['decision']=('AUTO','HUMAN_REVIEW','IMMEDIATE_HUMAN')[effective]
            notice_id=f"{event['event_id']}:{rev}"
            payload={'notification_id':notice_id,'event':event,'assessment':result,
                     'human_status':'REQUIRED' if effective else 'NOT_REQUIRED',
                     'execution':'NONE','delivery_status':'PENDING'}
            self.db.execute('INSERT INTO events VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,body=excluded.body,level=excluded.level',
                            (event['event_id'],rev,canonical,effective))
            self.db.execute('INSERT INTO outbox(id,body,level) VALUES(?,?,?)',
                            (notice_id,json.dumps(payload,ensure_ascii=False),effective))
        return payload

    def deliver_one(self, endpoint, now=None):
        now=time.time() if now is None else now
        row=self.db.execute('SELECT id,body,attempts FROM outbox WHERE delivered=0 AND next_try<=? ORDER BY level DESC,rowid LIMIT 1',(now,)).fetchone()
        if row is None: return 'EMPTY'
        key,body,attempts=row
        try:
            req=urllib.request.Request(endpoint,data=body.encode(),headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=2) as response:
                ack=json.loads(response.read(4097))
                if response.status!=200 or ack.get('notification_id')!=key or ack.get('persisted') is not True:
                    raise ValueError('invalid durable ACK')
        except (OSError,ValueError):
            with self.db:
                self.db.execute('UPDATE outbox SET attempts=?,next_try=? WHERE id=?',(attempts+1,now+min(30,2**min(attempts,5)),key))
            return 'RETRY_PENDING'
        with self.db:
            self.db.execute('UPDATE outbox SET delivered=1 WHERE id=?',(key,))
        return 'DELIVERED'

    def close(self): self.db.close()
