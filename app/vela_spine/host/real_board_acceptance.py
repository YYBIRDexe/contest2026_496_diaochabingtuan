"""Run isolated, simulated fleet acceptance against a real Gemini board.

Uses ADB through the existing VM, a separately started PC simulator and a
simulated platform. Never drives a vehicle. Each round uses a unique board
directory and task IDs. The operator must start the named simulator first.
"""
import argparse
import json
import ipaddress
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
from .robot_simulator import Fleet, SCHEMA


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True);p.add_argument('--output',required=True)
    p.add_argument('--identity',required=True);p.add_argument('--bind',default='192.168.6.1')
    p.add_argument('--vm',default='ggbird@192.168.6.129')
    p.add_argument('--remote-dir',default='/home/ggbird/codex-five-20261027')
    p.add_argument('--fleet-endpoint',default='10.175.92.181:18141')
    p.add_argument('--platform-endpoint',default='10.175.92.181:18135')
    p.add_argument('--board-ip',default='10.175.92.70')
    p.add_argument('--usb-bus',default='6-1')
    p.add_argument('--human-test-key',help='VM path to an isolated test key, never a production key')
    p.add_argument('--operator-db',help='VM path of the matching simulated-platform database')
    p.add_argument('--prefix',required=True);p.add_argument('--rounds',type=int,default=3)
    p.add_argument('--reboot',action='store_true',help='Run the previously verified board reboot check each round')
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,24}',a.prefix) or not 1<=a.rounds<=3:
        raise ValueError('invalid prefix or round count')
    if not ipaddress.IPv4Address(a.board_ip).is_private:raise ValueError('private board IP required')
    if not re.fullmatch(r'[0-9]+-[0-9]+',a.usb_bus):raise ValueError('invalid USB bus')
    if not re.fullmatch(r'/home/[A-Za-z0-9_./-]+',a.remote_dir):raise ValueError('invalid VM directory')
    if bool(a.human_test_key)!=bool(a.operator_db):raise ValueError('test key and operator database must be paired')
    for path in (a.human_test_key,a.operator_db):
        if path and not re.fullmatch(r'/home/[A-Za-z0-9_./-]+',path):raise ValueError('invalid VM test path')
    out=Path(a.output)
    if out.exists():raise FileExistsError('preserve existing acceptance report')
    fleet=Fleet(a.database); results=[]
    ssh=['ssh','-b',a.bind,'-i',a.identity,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',a.vm]
    scp=['scp','-o','BindAddress='+a.bind,'-i',a.identity,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes']
    def vm(*args,timeout=35):
        attempts=3 if args[0]=='cat' else 1
        for attempt in range(attempts):
            try:run=subprocess.run(ssh+[shlex.join(args)],capture_output=True,text=True,timeout=timeout)
            except subprocess.TimeoutExpired:
                if attempt+1==attempts:raise
                continue
            if run.returncode:raise RuntimeError('VM command failed: '+args[0]+' '+run.stderr[-300:])
            return run.stdout.strip()
    if a.human_test_key:
        resolved=vm('realpath','-e',a.human_test_key)
        if not resolved.startswith('/home/ggbird/.spine-acceptance-private/'):
            raise ValueError('operator test requires an isolated test key')
        if vm('stat','-c','%a',a.human_test_key)!='600':raise ValueError('test key must have mode 0600')
    def ensure_adb():
        # Reattach only before a new command. Never automatically replay a
        # mutating command whose outcome is uncertain after a disconnect.
        for _ in range(12):
            try:
                state=subprocess.run(ssh+[shlex.join(['adb','-s','1234','get-state'])],
                                     capture_output=True,text=True,timeout=6)
                if state.returncode==0 and state.stdout.strip()=='device':return
                ports=subprocess.run(ssh+[shlex.join(['/usr/lib/linux-tools/6.8.0-40-generic/usbip','port'])],
                                     capture_output=True,text=True,timeout=6)
                if ports.returncode==0 and '<Port in Use>' not in ports.stdout:
                    subprocess.run(ssh+[shlex.join(['sudo','/usr/lib/linux-tools/6.8.0-40-generic/usbip',
                        'attach','-r',a.bind,'-b',a.usb_bus])],capture_output=True,text=True,timeout=6)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(.5)
        raise RuntimeError('board ADB unavailable; no command was retried')
    def adb(*args,timeout=35):
        ensure_adb()
        text=vm('adb','-s','1234',*args,timeout=timeout)
        if 'error: ' in text or 'nsh: ' in text:raise RuntimeError('ADB command failed: '+text[:250])
        return text
    def upload(body,name):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/name;file.write_text(json.dumps(body,separators=(',',':')),encoding='utf-8')
            remote=a.remote_dir+'/'+name
            r=subprocess.run(scp+[str(file),a.vm+':'+remote],capture_output=True,text=True,timeout=20)
            if r.returncode:raise RuntimeError('fixture transfer failed')
            adb('push',remote,'/data/'+name)
            return '/data/'+name
    def view(root,task):
        # Some NuttX ADB shell responses truncate long output; write on the
        # board and pull it, then parse the complete file in the build VM.
        device_file=root+'/accept-view.json'
        command=shlex.join(['vela_spine','--task-view',root,task])+' > '+shlex.quote(device_file)
        adb('shell',command)
        remote_file=a.remote_dir+'/'+a.prefix+'-view.json'
        adb('pull',device_file,remote_file)
        output=vm('cat',remote_file)
        return json.loads(output)['tasks'][0]['state']
    def human_state(root,event_id):
        remote_file=a.remote_dir+'/'+a.prefix+'-state.json'
        adb('pull',root+'/state.json',remote_file)
        data=json.loads(vm('cat',remote_file))
        matches=[r for r in data['records'] if r['event']['event_id']==event_id]
        if len(matches)!=1:raise RuntimeError('event missing from board store')
        return matches[0].get('human',{}).get('state'),matches[0].get('pending')
    def report(robot,task,state,seq):
        return fleet.apply(dict(schema=SCHEMA,mode='simulation',command_id=task+'-'+state,
             robot_id=robot,task_id=task,revision=1,action='REPORT',state=state,sequence=seq))
    def wait_wifi():
        for _ in range(30):
            info=adb('shell','ifconfig','wlan0')
            if re.search(r'inet addr:'+re.escape(a.board_ip)+r'(?:\s|$)',info):return
            time.sleep(2)
        raise RuntimeError('Wi-Fi did not reconnect')
    try:
        if adb('get-state')!='device':raise RuntimeError('board not online')
        wait_wifi()
        for n in range(1,a.rounds+1):
            root='/data/vg-'+a.prefix+'-'+str(n)
            ids=[a.prefix+'-'+str(n)+'-T'+str(i) for i in (1,2,3)]
            tags=[a.prefix+'-'+str(n)+'-D'+str(i) for i in (1,2,3)]
            if any(r['task_id'] in ids for r in fleet.snapshot()['tasks']):
                raise RuntimeError('prefix already used in simulator')
            adb('shell','mkdir',root)
            if a.human_test_key:
                adb('push',a.human_test_key,root+'/control.key')
                if '-rw-------' not in adb('shell','ls','-l',root+'/control.key'):
                    raise RuntimeError('isolated test key permissions are not 0600')
            plan=dict(schema='spine-plan-v1',plan_id=a.prefix+'-p'+str(n),version=1,
                      tasks=[dict(task_id=ids[i],tag_id=tags[i],robot_id='S'+str(i+1),revision=1) for i in range(3)])
            planfile=upload(plan,a.prefix+'-plan'+str(n)+'.json')
            planned=adb('shell','vela_spine','--task-plan',planfile,root)
            if 'PLAN_PERSISTED' not in planned:raise RuntimeError('plan not persisted')
            offline=adb('shell','vela_spine','--task-dispatch',root,'127.0.0.1:9')
            if 'PARTIAL_NETWORK_ERROR' not in offline or any(view(root,t)!='PENDING' for t in ids):
                raise RuntimeError('offline handling failed')
            adb('shell','vela_spine','--task-dispatch',root,a.fleet_endpoint)
            if any(view(root,t)!='DISPATCHED' for t in ids):raise RuntimeError('three dispatches not acknowledged')
            for i in range(3):report('S'+str(i+1),ids[i],'RUNNING',1)
            adb('shell','vela_spine','--task-poll',root,a.fleet_endpoint)
            if any(view(root,t)!='RUNNING' for t in ids):raise RuntimeError('running reports not applied')
            event=dict(event_id=a.prefix+'-risk'+str(n),robot_id='S1',tag_id=tags[0],revision=1,
                policy_version='spine-v2',mode='replay',fresh=True,
                factors=dict(consequence=5,urgency=5,exposure=4,spread=3))
            eventfile=upload(event,a.prefix+'-risk'+str(n)+'.json')
            assessment=adb('shell','vela_spine','--ingest',eventfile,root)
            if 'IMMEDIATE_HUMAN' not in assessment:raise RuntimeError('risk not escalated')
            delivery=adb('shell','vela_spine','--deliver',root,a.platform_endpoint)
            if '"status":"DELIVERED"' not in delivery:raise RuntimeError('simulated platform delivery failed')
            adb('shell','vela_spine','--task-dispatch',root,a.fleet_endpoint)
            if view(root,ids[0])!='STOP_CONFIRMED':raise RuntimeError('risk stop not confirmed')
            if a.human_test_key:
                for step,state in [('CLAIM','CLAIMED'),('HANDLE','HANDLED'),('CLOSE','CLOSED')]:
                    cmd=['env','PYTHONPATH='+a.remote_dir+'/vela_spine','python3','-m',
                         'host.acceptance_operator','--db',a.operator_db,'--key-file',a.human_test_key,
                         '--event',event['event_id'],'--step',step]
                    queued=json.loads(vm(*cmd))
                    if queued.get('phase')!='QUEUED':raise RuntimeError('operator action not queued')
                    adb('shell','vela_spine','--watch',root,a.platform_endpoint,'1')
                    cmd[-1]='STATE'; actual=json.loads(vm(*cmd))
                    if actual.get('state')!=state:raise RuntimeError('operator confirmation missing: '+step)
                if view(root,ids[0])!='STOP_CONFIRMED':raise RuntimeError('operator close changed task ownership')
                if human_state(root,event['event_id'])!=('CLOSED',False):
                    raise RuntimeError('board did not persist operator close')
            for i in (1,2):report('S'+str(i+1),ids[i],'COMPLETED',2)
            adb('shell','vela_spine','--task-poll',root,a.fleet_endpoint)
            if [view(root,t) for t in ids]!=['STOP_CONFIRMED','COMPLETED','COMPLETED']:
                raise RuntimeError('terminal reports not applied')
            if a.reboot:
                proof=vm('env','PYTHONPATH='+a.remote_dir+'/vela_spine','python3','-m',
                         'host.acceptance_reboot','--root',root,'--task',ids[0],
                         '--bus',a.usb_bus,'--usbip-host',a.bind,timeout=150)
                if 'STABLE_30_SECONDS' not in proof:raise RuntimeError('board reboot check failed')
                wait_wifi()
                if [view(root,t) for t in ids]!=['STOP_CONFIRMED','COMPLETED','COMPLETED']:
                    raise RuntimeError('tasks lost on restart')
                if a.human_test_key and human_state(root,event['event_id'])!=('CLOSED',False):
                    raise RuntimeError('human close lost on restart')
            results.append(dict(round=n,board_root=root,tasks=ids,offline_pending=True,
                fleet_accept_run_complete=True,risk_score=92,risk_stop_confirmed=True,
                simulated_platform_ack=True,human_steps_verified=bool(a.human_test_key),
                reboot_verified=a.reboot,motion=False))
            out.write_text(json.dumps({'rounds':results,'all_passed':False},indent=2),encoding='utf-8')
            print('ROUND_%d_PASS'%n,flush=True)
        out.write_text(json.dumps({'rounds':results,'all_passed':True},indent=2),encoding='utf-8')
    except Exception as error:
        out.write_text(json.dumps({'rounds':results,'all_passed':False,'error':str(error)},indent=2),encoding='utf-8')
        raise

if __name__=='__main__':main()
