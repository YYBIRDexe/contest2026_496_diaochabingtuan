import itertools
from contextlib import closing
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
import unittest
from host.native import assess,allocate
from host.outbox import Outbox
from host.receiver import make_server

def event(key='e1',rev=1,values=(5,5,5,1)):
    return {'event_id':key,'revision':rev,'tag_id':'D_TAG_2','robot_id':'s2',
            'policy_version':'water-demo-score-v1','mode':'tag_demo','fresh':True,
            'factors':dict(zip(('consequence','urgency','exposure','spread'),values))}

class Scoring(unittest.TestCase):
    def test_strict_boundary(self):
        f=dict(consequence=4,urgency=3,exposure=3,spread=4) # 70
        self.assertEqual(assess(f)['score'],70)
        self.assertEqual(assess(f)['decision'],'AUTO')
        self.assertEqual(assess(f,69)['decision'],'IMMEDIATE_HUMAN')
    def test_unknown_not_safe(self):
        self.assertEqual(assess({})['decision'],'HUMAN_REVIEW')
        self.assertEqual(assess({'consequence':5,'urgency':5,'exposure':5})['decision'],'IMMEDIATE_HUMAN')
    def test_stale_requires_review(self):
        self.assertEqual(assess(dict.fromkeys(('consequence','urgency','exposure','spread'),1),fresh=False)['decision'],'HUMAN_REVIEW')
    def test_same_type_context_changes(self):
        low=event(values=(1,1,1,1));high=event()
        self.assertEqual(low['tag_id'],high['tag_id'])
        self.assertEqual(assess(low['factors'])['decision'],'AUTO')
        self.assertEqual(assess(high['factors'])['decision'],'IMMEDIATE_HUMAN')
    def test_monotonic_exhaustive(self):
        for vals in itertools.product(range(6),repeat=4):
            f=event(values=vals)['factors'];base=assess(f)['score']
            for k in f:
                if f[k]<5:
                    higher=dict(f);higher[k]+=1
                    self.assertGreaterEqual(assess(higher)['score'],base)
    def test_invalid(self):
        for v in (6,-2,True,'5',1.5):
            with self.assertRaises(ValueError): assess({'urgency':v})
    def test_scenario(self):
        config=json.loads((Path(__file__).parents[1]/'config/scenario.json').read_text(encoding='utf-8'))
        self.assertEqual(len(config['tags']),8)
        self.assertEqual(assess(config['tags']['D_TAG_2']['factors'])['score'],92)

class Allocation(unittest.TestCase):
    def test_excludes_active_unknown_unreachable(self):
        tags=[{'id':'t','priority':1,'state':'RUNNING','owner':'s1'}]
        robots=[{'id':'s2','budget':100,'fresh':True,'ready':True}]
        edges={('t','s2'):{'energy':10,'cost':1,'verified':True}}
        self.assertIsNone(allocate(tags,robots,edges)['assignments']['t'])
        tags[0].update(state='PENDING',owner=None)
        robots[0]['fresh']=False
        self.assertIsNone(allocate(tags,robots,edges)['assignments']['t'])
        robots[0]['fresh']=True;edges[('t','s2')]['verified']=False
        self.assertIsNone(allocate(tags,robots,edges)['assignments']['t'])
    def test_global_assignment_beats_greedy(self):
        tags=[{'id':x,'priority':1,'state':'PENDING','owner':None} for x in ('a','b')]
        robots=[{'id':x,'budget':1,'fresh':True,'ready':True} for x in ('s1','s2')]
        edges={('a','s1'):{'energy':1,'cost':1,'verified':True},
               ('a','s2'):{'energy':1,'cost':2,'verified':True},
               ('b','s1'):{'energy':1,'cost':1,'verified':True}}
        r=allocate(tags,robots,edges)
        self.assertEqual(r['assignments'],{'a':'s2','b':'s1'})
    def test_against_independent_bruteforce(self):
        rng=random.Random(9)
        for _ in range(60):
            tags=[{'id':str(i),'priority':rng.randint(1,5),'state':'PENDING','owner':None} for i in range(4)]
            robots=[{'id':str(i),'budget':rng.randint(1,5),'fresh':True,'ready':True} for i in range(3)]
            edges={(t['id'],r['id']):{'energy':rng.randint(1,3),'cost':rng.randint(0,8),'verified':bool(rng.randint(0,1))} for t in tags for r in robots}
            best=(999,999)
            for owners in itertools.product(range(-1,3),repeat=4):
                used=[0]*3;miss=cost=0;valid=True
                for t,r in enumerate(owners):
                    if r<0:miss+=tags[t]['priority'];continue
                    edge=edges[(str(t),str(r))]
                    if not edge['verified']:valid=False;break
                    used[r]+=edge['energy'];cost+=edge['cost']
                if valid and all(used[r]<=robots[r]['budget'] for r in range(3)):
                    best=min(best,(miss,cost))
            actual=allocate(tags,robots,edges)
            self.assertEqual((actual['uncovered_priority'],actual['total_cost']),best)

class Notifications(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.box=Outbox(self.path/'out.sqlite')
    def tearDown(self): self.box.close();self.tmp.cleanup()
    def test_duplicate_collision_and_escalation(self):
        e=event(values=(1,1,1,1));self.box.ingest(e)
        self.assertEqual(self.box.ingest(e)['status'],'DUPLICATE')
        with self.assertRaises(ValueError):self.box.ingest(event())
        self.assertEqual(self.box.ingest(event(rev=2))['assessment']['decision'],'IMMEDIATE_HUMAN')
        self.assertEqual(self.box.ingest(e)['status'],'STALE_IGNORED')
        r=self.box.ingest(event(rev=3,values=(0,0,0,0)))
        self.assertEqual(r['assessment']['decision'],'IMMEDIATE_HUMAN')
    def test_real_http_retry_restart_and_durable_ack(self):
        self.box.ingest(event())
        # Bind a port without serving, then close it: deterministic connection refusal.
        server=make_server(self.path/'platform.sqlite');port=server.server_port;server.server_close()
        self.assertEqual(self.box.deliver_one(f'http://127.0.0.1:{port}/incidents',now=0),'RETRY_PENDING')
        self.box.close();self.box=Outbox(self.path/'out.sqlite')
        server=make_server(self.path/'platform.sqlite',port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            self.assertEqual(self.box.deliver_one(f'http://127.0.0.1:{port}/incidents',now=10),'DELIVERED')
            with closing(sqlite3.connect(self.path/'platform.sqlite')) as db:
                stored=json.loads(db.execute('SELECT body FROM incidents').fetchone()[0])
            self.assertEqual(stored['human_status'],'REQUIRED')
            self.assertEqual(stored['execution'],'NONE')
            self.assertEqual(self.box.deliver_one(f'http://127.0.0.1:{port}/incidents',now=11),'EMPTY')
        finally:server.shutdown();server.server_close();thread.join()
    def test_urgent_priority(self):
        self.box.ingest(event('low',values=(1,1,1,1)));self.box.ingest(event('high'))
        row=self.box.db.execute('SELECT id FROM outbox ORDER BY level DESC,rowid LIMIT 1').fetchone()
        self.assertEqual(row[0],'high:1')
    def test_unknown_human_review(self):
        e=event();e['factors']={}
        self.assertEqual(self.box.ingest(e)['human_status'],'REQUIRED')

if __name__=='__main__':unittest.main(verbosity=2)
