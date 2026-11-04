"""Real Gemini LAN HTTP sender -> explicitly named test receiver; no car motion."""
import argparse
import json
from pathlib import Path
import subprocess

def event(rev=1):
    return dict(event_id='gemini-net-20261025-001',robot_id='S2',tag_id='D_TAG_2',revision=rev,
                policy_version='spine-v2',mode='replay',fresh=True,
                factors=dict(zip(('consequence','urgency','exposure','spread'),
                                 (5,5,4,3) if rev==1 else (1,1,1,1))))

def run(output,phase,endpoint):
    output.mkdir(parents=True,exist_ok=False);rows=[]
    def adb(*args,check=True):
        r=subprocess.run(['adb','-s','1234',*args],capture_output=True,text=True,timeout=20)
        if check and r.returncode:raise RuntimeError((r.stdout+r.stderr)[:400])
        return r
    def invoke(name,command,expected=None,ok=True):
        d=output/f'{len(rows):02d}';d.mkdir();script=d/'run.nsh'
        text=f'set +e\n{command} > /data/o25\necho $? > /data/c25\n'
        if max(map(len,text.splitlines()))>=64:raise ValueError('NSH line too long')
        script.write_text(text);adb('push',str(script),'/data/r25')
        r=adb('shell','sh','/data/r25',check=False)
        adb('pull','/data/o25',str(d/'result.json'));adb('pull','/data/c25',str(d/'status.txt'))
        obj=json.loads((d/'result.json').read_text());code=int((d/'status.txt').read_text().strip())
        passed=(code==0 if ok else code!=0)
        if expected:passed=passed and all(obj.get(k)==v for k,v in expected.items())
        rows.append(dict(name=name,passed=passed,exit_code=code,result=obj,diagnostic=(r.stdout+r.stderr)[:300]))
        return obj
    def ingest(rev,status,delivery):
        p=output/'input.json';p.write_text(json.dumps(event(rev)));adb('push',str(p),'/data/i25')
        return invoke('ingest-'+str(rev),'vela_spine --ingest /data/i25 /data/n25',
                      dict(status=status,delivery_status=delivery,durable_ack=True))
    if phase=='seed':
        adb('shell','mkdir','/data/n25')
        probe=adb('pull','/data/n25/state.json',str(output/'existing.json'),check=False)
        if probe.returncode==0:raise RuntimeError('test state already exists')
        ingest(1,'ACCEPTED_PERSISTED','PENDING')
        ip=endpoint.rsplit(':',1)[0]
        invoke('offline-keeps-pending',f'vela_spine --deliver /data/n25 {ip}:18134',
               dict(status='RETRY_PENDING',remote_ack=False),False)
        row=invoke('pending-after-failure','vela_spine --pending /data/n25')
        rows[-1]['passed'] &= len(row)==1 and row[0]['delivered'] is False
    elif phase=='offline':
        ip=endpoint.rsplit(':',1)[0]
        invoke('offline-keeps-pending',f'vela_spine --deliver /data/n25 {ip}:18134',
               dict(status='RETRY_PENDING',remote_ack=False),False)
        row=invoke('pending-after-failure','vela_spine --pending /data/n25')
        rows[-1]['passed'] &= len(row)==1 and row[0]['delivered'] is False
    elif phase=='send':
        row=invoke('pending-after-reboot','vela_spine --pending /data/n25')
        rows[-1]['passed'] &= len(row)==1 and row[0]['delivered'] is False
        invoke('real-http-delivery',f'vela_spine --deliver /data/n25 {endpoint}',
               dict(status='DELIVERED',remote_ack=True,ack_scope='REMOTE_STORAGE_ONLY'))
        invoke('no-repeat-send',f'vela_spine --deliver /data/n25 {endpoint}',dict(status='EMPTY'))
        ingest(1,'DUPLICATE','DELIVERED')
        ingest(2,'ACCEPTED_PERSISTED','PENDING')
        invoke('latched-update-delivery',f'vela_spine --deliver /data/n25 {endpoint}',dict(status='DELIVERED',remote_ack=True))
    else:
        invoke('delivered-after-reboot',f'vela_spine --deliver /data/n25 {endpoint}',dict(status='EMPTY'))
        ingest(2,'DUPLICATE','DELIVERED')
        row=invoke('human-work-still-pending','vela_spine --pending /data/n25')
        rows[-1]['passed'] &= (len(row)==1 and row[0]['delivered'] is True and row[0]['pending'] is True
                                and row[0]['assessment']['decision']=='IMMEDIATE_HUMAN'
                                and row[0]['escalation_score']==92)
    report=dict(phase=phase,endpoint=endpoint,target='PC_ISOLATED_REPLAY_RECEIVER',
                source='REAL_GEMINI_NATIVE_C_HTTP_OVER_HOTSPOT',cases=rows,
                passed=all(x['passed'] for x in rows),human_ack=False,motion=False)
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(phase=phase,passed=report['passed'],cases=len(rows))))
    return report['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--phase',choices=['seed','offline','send','resume'],required=True)
    p.add_argument('--endpoint',required=True);a=p.parse_args()
    raise SystemExit(0 if run(a.output,a.phase,a.endpoint) else 1)
