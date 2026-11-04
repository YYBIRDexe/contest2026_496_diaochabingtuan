"""Three simulated cars -> real board CLI over ADB. No live-car claims."""
import argparse
import copy
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from .native import allocate

def event(robot='S1', tag='D_TAG_1', values=(3,2,1,2)):
    return dict(event_id='sim-'+robot+'-'+tag, robot_id=robot, tag_id=tag,
                revision=1, policy_version='spine-v2', mode='replay', fresh=True,
                factors=dict(zip(('consequence','urgency','exposure','spread'),values)))

def cases():
    items=[]
    def add(name,e,score=None,decision=None):items.append((name,e,score,decision))
    add('S1-bank',event(),44,'AUTO')
    add('S2-urgent',event('S2','D_TAG_2',(5,5,5,1)),92,'IMMEDIATE_HUMAN')
    add('S3-room',event('S3','M_TAG_3',(1,1,1,1)),20,'AUTO')
    add('threshold-equal',event(values=(4,3,3,4)),70,'AUTO')
    add('threshold-above',event(values=(4,3,3,5)),72,'IMMEDIATE_HUMAN')
    add('same-tag-low',event(values=(1,1,1,1)),20,'AUTO')
    add('same-tag-high',event(values=(5,5,4,3)),92,'IMMEDIATE_HUMAN')
    e=event();e['factors']={};add('unknown',e,0,'HUMAN_REVIEW')
    e=event(values=(1,1,1,1));e['fresh']=False;add('stale-low',e,20,'HUMAN_REVIEW')
    e=event(values=(5,5,4,3));e['fresh']=False;add('stale-high',e,92,'IMMEDIATE_HUMAN')
    for key,value in [('revision',True),('revision',0),('revision',1.5),
                      ('mode','live'),('policy_version','unknown'),('fresh',1),
                      ('robot_id',''),('tag_id','unsafe/tag')]:
        e=event();e[key]=value;add('reject-'+key+'-'+str(value),e)
    for value in (6,-2,True,'5'):
        e=event();e['factors']['urgency']=value;add('reject-factor-'+str(value),e)
    raw=json.dumps(event())
    add('reject-duplicate-key','{"robot_id":"S2",'+raw[1:])
    add('reject-trailing',raw+' {}')
    add('reject-size',raw+' '*4097)
    add('reject-nesting','['*40+'0'+']'*40)
    add('repeat-observation',event(),44,'AUTO')
    return items

def allocations():
    robots=[dict(id=r,budget=10,ready=True,fresh=True) for r in ('S1','S2','S3')]
    tags=[dict(id=t,priority=1,state='PENDING',owner=None) for t in ('left','right','room')]
    edges={(t,r):dict(energy=10,cost=10,verified=True)
           for t,r in zip(('left','right','room'),('S1','S2','S3'))}
    rows=[]
    def check(name,rs,ts,es,expected):
        result=allocate(ts,rs,es)
        rows.append(dict(name=name,scope='HOST_NATIVE_C_PROPOSAL',result=result,
                         passed=result['assignments']==expected))
    check('three-zones',robots,tags,edges,dict(left='S1',right='S2',room='S3'))
    rs=copy.deepcopy(robots);rs[0]['budget']=0
    check('low-energy-no-route',rs,tags,edges,dict(left=None,right='S2',room='S3'))
    rs[1]['budget']=20;es=copy.deepcopy(edges)
    es[('left','S2')]=dict(energy=10,cost=12,verified=True)
    check('verified-backup-proposal',rs,tags,es,dict(left='S2',right='S2',room='S3'))
    es[('left','S2')]['verified']=False
    check('unverified-backup-refused',rs,tags,es,dict(left=None,right='S2',room='S3'))
    rs=copy.deepcopy(robots);rs[1]['fresh']=False
    check('offline-car-excluded',rs,tags,edges,dict(left='S1',right=None,room='S3'))
    ts=copy.deepcopy(tags);ts[0].update(state='RUNNING',owner='S1')
    check('active-owner-not-stolen',robots,ts,edges,dict(left=None,right='S2',room='S3'))
    return rows

def run(output, serial):
    output.mkdir(parents=True,exist_ok=False)
    def adb(*args,check=True):
        r=subprocess.run(['adb','-s',serial,*args],capture_output=True,text=True,timeout=20)
        if check and r.returncode:raise RuntimeError('ADB operation failed: '+(r.stdout+r.stderr)[:400])
        return r
    if adb('get-state').stdout.strip()!='device':raise RuntimeError('board not ready')
    # Board CONFIG_NAME_MAX=32; keep each device path component short.
    device='/data/s3'+hashlib.sha256(output.name.encode()).hexdigest()[:6]
    # Only the new dedicated test directory is written; no credentials or firmware changes.
    if not all(c.isalnum() or c in '-_' for c in output.name):raise ValueError('output basename')
    adb('shell','mkdir',device)
    rows=[]
    for i,(name,e,score,decision) in enumerate(cases()):
        folder=output/f'{i:02d}';folder.mkdir()
        payload=folder/'input.json';payload.write_text(e if isinstance(e,str) else json.dumps(e),encoding='utf-8')
        script=folder/'run.nsh'
        # Short absolute paths: spawned apps do not reliably inherit NSH's local cwd.
        script.write_text(f'set +e\nvela_spine --event {device}/in > {device}/out\necho $? > {device}/rc\n',encoding='utf-8')
        if max(map(len,script.read_text().splitlines()))>=64:raise ValueError('NSH line too long')
        adb('push',str(payload),device+'/in');adb('push',str(script),device+'/run')
        start=time.monotonic();r=adb('shell','sh',device+'/run',check=False)
        elapsed=round((time.monotonic()-start)*1000,1)
        adb('pull',device+'/out',str(folder/'result.json'))
        adb('pull',device+'/rc',str(folder/'status.txt'))
        code=int((folder/'status.txt').read_text().strip())
        raw=(folder/'result.json').read_text();result=json.loads(raw) if raw.strip() else None
        if score is None:passed=code!=0 and result is None
        else:
            passed=(code==0 and result is not None and result.get('score')==score
                    and result.get('decision')==decision
                    and all(result.get(k)==e[k] for k in ('event_id','robot_id','tag_id','revision'))
                    and result.get('source')=='REPLAY_UNAUTHENTICATED'
                    and result.get('status')=='VALIDATED_ONLY'
                    and result.get('motion') is False and result.get('durable_ack') is False)
        rows.append(dict(name=name,passed=passed,exit_code=code,result=result,
                         adb_execution_ms=elapsed,diagnostic=(r.stdout+r.stderr)[:300]))
    host=allocations()
    report=dict(utc=datetime.now(timezone.utc).isoformat(),robots=['S1','S2','S3'],
                transport='SIMULATED_CAR_EVENTS_OVER_ADB_TO_REAL_GEMINI',
                firmware=adb('shell','uname','-a').stdout.strip(),board_cases=rows,
                host_allocation_cases=host,
                passed=all(r['passed'] for r in rows+host),
                limitations=['No real car, wireless car transport or source authentication',
                             'Board ingress is stateless; repeat is validated again, not deduplicated',
                             'Allocation cases use host C reference; no execution ACK or motion',
                             'Freshness is replay input; no live timestamp validation',
                             'No Gemini-to-platform durable notification tested'])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],board_cases=len(rows),host_cases=len(host))))
    return report['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--serial',default='1234');args=p.parse_args()
    raise SystemExit(0 if run(args.output,args.serial) else 1)
