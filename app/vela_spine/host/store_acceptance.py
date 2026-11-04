"""Actual Gemini store acceptance, split around an external real reboot."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

BASE='/data/p25'
DB=BASE+'/db'

def event(rev=1,high=False):
    return dict(event_id='store-S2-test',robot_id='S2',tag_id='D_TAG_2',revision=rev,
                policy_version='spine-v2',mode='replay',fresh=True,
                factors=dict(zip(('consequence','urgency','exposure','spread'),
                                 (5,5,4,3) if high else (1,1,1,1))))

def run(output,phase):
    output.mkdir(parents=True,exist_ok=False);rows=[]
    def adb(*args,check=True):
        r=subprocess.run(['adb','-s','1234',*args],capture_output=True,text=True,timeout=20)
        if check and r.returncode:raise RuntimeError((r.stdout+r.stderr)[:400])
        return r
    def pull(remote,local):adb('pull',remote,str(local));return local.read_bytes()
    def invoke(command,folder):
        folder.mkdir();script=folder/'run.nsh'
        text=f'set +e\n{command} > {BASE}/out\necho $? > {BASE}/rc\n'
        if max(map(len,text.splitlines()))>=64:raise ValueError('NSH command too long')
        script.write_text(text);adb('push',str(script),BASE+'/run')
        r=adb('shell','sh',BASE+'/run',check=False)
        raw=pull(BASE+'/out',folder/'result.json').decode()
        code=int(pull(BASE+'/rc',folder/'status.txt').decode().strip())
        return code,json.loads(raw) if raw.strip() else None,(r.stdout+r.stderr)[:400]
    def snapshot(name):return pull(DB+'/state.json',output/name)
    def check(name,e,status=None,decision=None,ack=None,unchanged=False,root=DB):
        folder=output/f'{len(rows):02d}'
        before=snapshot('before.json') if unchanged else None
        payload=output/'input.json';payload.write_text(json.dumps(e))
        adb('push',str(payload),BASE+'/in')
        code,result,diag=invoke(f'vela_spine --ingest {BASE}/in {root}',folder)
        if status is None:passed=code!=0 and result is None
        else:
            passed=(code==0 and result is not None and result.get('status')==status
                    and result.get('decision')==decision and result.get('durable_ack') is ack
                    and result.get('ack_scope')=='LOCAL_STORAGE_ONLY'
                    and result.get('motion') is False)
        if unchanged:passed=passed and snapshot('after.json')==before
        rows.append(dict(name=name,passed=passed,exit_code=code,result=result,diagnostic=diag))
    def pending(name):
        code,result,diag=invoke(f'vela_spine --pending {DB}',output/f'{len(rows):02d}')
        passed=(code==0 and isinstance(result,list) and len(result)==1
                and result[0]['event']['revision']==3 and result[0]['pending'] is True
                and result[0]['assessment']['decision']=='IMMEDIATE_HUMAN'
                and result[0]['assessment']['latched'] is True)
        rows.append(dict(name=name,passed=passed,exit_code=code,result=result,diagnostic=diag))
    if phase=='seed':
        # Fresh firmware/test environment only. Never delete or reset an existing DB.
        adb('shell','mkdir',BASE)
        adb('shell','mkdir',DB)
        probe=adb('pull',DB+'/state.json',str(output/'existing.json'),check=False)
        if probe.returncode==0:raise RuntimeError('test store already exists; do not overwrite')
        check('first-commit',event(),'ACCEPTED_PERSISTED','AUTO',True)
        check('duplicate-no-write',event(),'DUPLICATE','AUTO',True,True)
        check('revision-collision',event(high=True),unchanged=True)
        check('urgent-update',event(2,True),'ACCEPTED_PERSISTED','IMMEDIATE_HUMAN',True)
        check('old-version-no-write',event(),'STALE_IGNORED','IMMEDIATE_HUMAN',False,True)
        check('low-update-keeps-human',event(3),'ACCEPTED_PERSISTED','IMMEDIATE_HUMAN',True)
        check('duplicate-urgent-state',event(3),'DUPLICATE','IMMEDIATE_HUMAN',True,True)
        e=event(4);e['robot_id']='S1';check('identity-conflict',e,unchanged=True)
        e=event(4);e['factors']['urgency']=6;check('invalid-no-write',e,unchanged=True)
        pending('pending-before-reboot')
        data=snapshot('checkpoint.json')
        # Incomplete staging file must not replace the last committed snapshot.
        orphan=output/'orphan.tmp';orphan.write_text('incomplete staging data')
        adb('push',str(orphan),DB+'/state.tmp')
    else:
        pending('pending-after-real-reboot')
        check('duplicate-after-reboot',event(3),'DUPLICATE','IMMEDIATE_HUMAN',True,True)
        data=snapshot('checkpoint.json')
        # Corruption test is isolated from the primary persisted store.
        adb('shell','mkdir','/data/b25')
        probe=adb('pull','/data/b25/state.json',str(output/'existing-bad.json'),check=False)
        if probe.returncode==0:raise RuntimeError('isolated corruption store already exists')
        bad=output/'corrupt.json';obj=json.loads(data);obj['crc32']='invalid'
        bad.write_text(json.dumps(obj));adb('push',str(bad),'/data/b25/state.json')
        check('corrupt-store-no-ack',event(4,True),root='/data/b25')
        self_after=snapshot('after-corrupt-test.json')
        rows.append(dict(name='main-store-not-overwritten',passed=data==self_after))
    report=dict(phase=phase,source='REPLAY_ON_REAL_GEMINI_OVER_ADB',cases=rows,
                passed=all(r['passed'] for r in rows),snapshot_sha256=hashlib.sha256(data).hexdigest(),
                scope='LOCAL_STORAGE_ONLY; no network delivery, human ACK or hard power-cut guarantee')
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(phase=phase,passed=report['passed'],cases=len(rows))))
    return report['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--phase',choices=['seed','resume'],required=True);a=p.parse_args()
    raise SystemExit(0 if run(a.output,a.phase) else 1)
