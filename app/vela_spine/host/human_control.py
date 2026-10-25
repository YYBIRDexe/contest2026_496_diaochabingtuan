"""Version-bound operator commands. Only board-confirmed results change state."""
from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3

class Conflict(ValueError):
    pass

def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result

def read_key(path):
    text = Path(path).read_text().strip()
    if not re.fullmatch('[0-9a-f]{64}', text):
        raise ValueError('invalid control key')
    return bytes.fromhex(text)

def signed(key, payload):
    return dict(payload=payload, mac=hmac.new(key, payload.encode(), hashlib.sha256).hexdigest())

def verified(key, envelope):
    if not isinstance(envelope, dict) or set(envelope) != {'payload', 'mac'}:
        raise ValueError('envelope')
    payload, signature = envelope['payload'], envelope['mac']
    if not isinstance(payload, str) or len(payload.encode()) > 1400 or not isinstance(signature, str):
        raise ValueError('signature')
    expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError('signature')
    return json.loads(payload, object_pairs_hook=unique)

class Ledger:
    def __init__(self, path, key):
        if len(key) != 32:
            raise ValueError('control key')
        self.path, self.key = path, key
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS human_actions(id TEXT PRIMARY KEY,notice TEXT NOT NULL,step TEXT NOT NULL,payload TEXT NOT NULL,envelope TEXT NOT NULL,phase TEXT NOT NULL,outcome TEXT,result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS human_state(notice TEXT PRIMARY KEY,state TEXT NOT NULL,actor TEXT NOT NULL,last_action TEXT NOT NULL)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _latest(self, db):
        latest = {}
        for (body,) in db.execute('SELECT body FROM incidents'):
            obj = json.loads(body)
            eid = obj['event']['event_id']
            if eid not in latest or obj['event']['revision'] > latest[eid]['event']['revision']:
                latest[eid] = obj
        return latest

    def _state(self, db, notice):
        row = db.execute('SELECT state,actor FROM human_state WHERE notice=?', (notice,)).fetchone()
        return row or ('REQUIRED', '')

    def view(self):
        with closing(self.connect()) as db:
            result = []
            for obj in self._latest(db).values():
                notice = obj['notification_id']
                state, actor = self._state(db, notice)
                pending = db.execute("SELECT id,step FROM human_actions WHERE notice=? AND phase='QUEUED'", (notice,)).fetchone()
                last = db.execute('SELECT id,step,outcome FROM human_actions WHERE notice=? ORDER BY rowid DESC LIMIT 1', (notice,)).fetchone()
                result.append(dict(notice=obj, human_state=state, actor=actor,
                                   waiting=dict(zip(('action_id', 'step'), pending)) if pending else None,
                                   last_action=dict(zip(('action_id', 'step', 'outcome'), last)) if last else None))
            return result

    def state_of(self, notice):
        with closing(self.connect()) as db:
            state, actor = self._state(db, notice)
        return dict(state=state, actor=actor)

    def queue(self, request):
        fields = {'request_id', 'event_id', 'revision', 'step', 'actor', 'note', 'verified'}
        if not isinstance(request, dict) or set(request) != fields:
            raise ValueError('fields')
        for name, limit in [('request_id', 64), ('event_id', 64), ('actor', 32)]:
            value = request[name]
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,' + str(limit) + '}', value):
                raise ValueError(name)
        revision, step, note = request['revision'], request['step'], request['note']
        if type(revision) is not int or not 1 <= revision <= 2147483647:
            raise ValueError('revision')
        if step not in ('CLAIM', 'HANDLE', 'CLOSE') or type(request['verified']) is not bool or request['verified'] != (step == 'CLOSE'):
            raise ValueError('step or verification')
        if not isinstance(note, str) or not note.strip() or len(note.encode()) > 240 or any(ord(c) < 32 for c in note):
            raise ValueError('note')
        command = dict(schema=1, action_id=request['request_id'], event_id=request['event_id'],
                       revision=revision, step=step, actor=request['actor'], note=note,
                       verified=request['verified'])
        payload = canonical(command)
        if len(payload.encode()) > 1400:
            raise ValueError('size')
        envelope = canonical(signed(self.key, payload))
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            obj = self._latest(db).get(request['event_id'])
            if not obj or obj['event']['revision'] != revision:
                raise Conflict('STALE_REVISION')
            if obj['assessment']['decision'] == 'AUTO':
                raise Conflict('HUMAN_NOT_REQUIRED')
            if obj.get('source') not in ('GEMINI_REPLAY_NATIVE_C', 'HOST_NATIVE_C_TRANSPORT_TEST'):
                raise Conflict('SOURCE_NOT_CONTROLLABLE')
            old = db.execute('SELECT payload,phase,outcome FROM human_actions WHERE id=?', (request['request_id'],)).fetchone()
            if old:
                if old[0] != payload:
                    raise Conflict('REQUEST_ID_COLLISION')
                return dict(action_id=request['request_id'], phase=old[1], outcome=old[2])
            notice = obj['notification_id']
            if db.execute("SELECT 1 FROM human_actions WHERE notice=? AND phase='QUEUED'", (notice,)).fetchone():
                raise Conflict('AWAITING_BOARD_CONFIRMATION')
            state, actor = self._state(db, notice)
            if state != {'CLAIM': 'REQUIRED', 'HANDLE': 'CLAIMED', 'CLOSE': 'HANDLED'}[step]:
                raise Conflict('INVALID_TRANSITION')
            if step != 'CLAIM' and actor != request['actor']:
                raise Conflict('OWNER_MISMATCH')
            db.execute('INSERT INTO human_actions(id,notice,step,payload,envelope,phase) VALUES(?,?,?,?,?,?)',
                       (request['request_id'], notice, step, payload, envelope, 'QUEUED'))
        return dict(action_id=request['request_id'], phase='QUEUED', outcome=None)

    def next_envelope(self):
        with closing(self.connect()) as db:
            row = db.execute("SELECT envelope FROM human_actions WHERE phase='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
        return row[0] if row else '{"empty":true}'

    def receive(self, envelope):
        result = verified(self.key, envelope)
        fields = {'action_id', 'event_id', 'revision', 'current_revision', 'status', 'human_state', 'pending'}
        if not isinstance(result, dict) or set(result) != fields:
            raise ValueError('result fields')
        if result['status'] not in ('APPLIED', 'DUPLICATE', 'STALE_REJECTED', 'STATE_REJECTED'):
            raise ValueError('outcome')
        if type(result['revision']) is not int or type(result['current_revision']) is not int or type(result['pending']) is not bool:
            raise ValueError('result types')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload,step,phase FROM human_actions WHERE id=?', (result['action_id'],)).fetchone()
            if not row:
                raise ValueError('unknown action')
            command = json.loads(row[0])
            if result['event_id'] != command['event_id'] or result['revision'] != command['revision']:
                raise ValueError('result binding')
            if row[2] == 'FINAL':
                return dict(action_id=result['action_id'], persisted=True)
            if result['status'] in ('APPLIED', 'DUPLICATE'):
                expected = {'CLAIM': 'CLAIMED', 'HANDLE': 'HANDLED', 'CLOSE': 'CLOSED'}[row[1]]
                if result['human_state'] != expected or result['pending'] != (expected != 'CLOSED') or result['current_revision'] != command['revision']:
                    raise ValueError('result state')
                db.execute('INSERT OR REPLACE INTO human_state VALUES(?,?,?,?)',
                           (f"{command['event_id']}:{command['revision']}", expected, command['actor'], result['action_id']))
            db.execute("UPDATE human_actions SET phase='FINAL',outcome=?,result=? WHERE id=?",
                       (result['status'], canonical(envelope), result['action_id']))
        return dict(action_id=result['action_id'], persisted=True)
