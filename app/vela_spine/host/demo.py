"""Reproducible local W1/W2 run; no board/vehicle actions."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time
from .native import assess,allocate
from .outbox import Outbox
from .receiver import make_server

def run(output):
    output.mkdir(parents=True,exist_ok=True)
    config=json.loads((Path(__file__).parents[1]/'config/scenario.json').read_text(encoding='utf-8'))
    if config['weights']!={'consequence':40,'urgency':30,'exposure':20,'spread':10}:
        raise ValueError('native weights and config mismatch')
    server=make_server(output/'platform.sqlite')
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    box=Outbox(output/'outbox.sqlite',config['threshold'])
    run_id=str(time.time_ns());assessments={}
    route_robot={r['route']:r['id'] for r in config['robots']}
    try:
        for tag,meta in config['tags'].items():
            e={'event_id':run_id+'-'+tag,'revision':1,'tag_id':tag,'robot_id':route_robot[meta['route']],
               'policy_version':config['policy_version'],'mode':'replay','fresh':True,
               'factors':meta['factors']}
            result=box.ingest(e);assessments[tag]=result['assessment']
        deliveries=[]
        for _ in range(8):deliveries.append(box.deliver_one(f'http://127.0.0.1:{server.server_port}/incidents'))
        # Example reachable routes only. Deliberately no cross-bank edge.
        robots=[{'id':r['id'],'budget':100,'fresh':True,'ready':True} for r in config['robots']]
        tags=[{'id':tag,'priority':1,'state':'PENDING','owner':None} for tag in config['tags']]
        edges={(tag,route_robot[meta['route']]):{'energy':10,'cost':10,'verified':True}
               for tag,meta in config['tags'].items()}
        allocation=allocate(tags,robots,edges)
        with closing(sqlite3.connect(output/'platform.sqlite')) as db:
            ids=[r[0] for r in db.execute('SELECT id FROM incidents ORDER BY rowid')]
        report={'environment':'PC_REPLAY_NATIVE_C_WITH_REAL_LOOPBACK_HTTP',
                'board_deployed':False,'model_required':False,'alignment_feature':False,
                'policy':config['policy_version'],'assessments':assessments,
                'allocation':allocation,'deliveries':deliveries,'persisted_notice_ids':ids}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'scores':{k:v['score'] for k,v in assessments.items()},
                          'allocation':allocation,'deliveries':deliveries},ensure_ascii=False))
    finally:box.close();server.shutdown();server.server_close();worker.join()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
