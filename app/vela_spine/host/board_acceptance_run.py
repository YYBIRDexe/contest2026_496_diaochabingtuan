"""Launch isolated simulators, run real-board acceptance, and stop only our services."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex
import socket
import socketserver
import subprocess
import sys
import threading
import time
from .board_sim_network import RestrictedRelay

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True);p.add_argument('--prefix',required=True)
    p.add_argument('--identity',required=True);p.add_argument('--test-key',required=True)
    p.add_argument('--pc-ip',required=True);p.add_argument('--board-ip',required=True)
    p.add_argument('--bind',default='192.168.6.1');p.add_argument('--vm',default='ggbird@192.168.6.129')
    p.add_argument('--usb-bus',default='6-1')
    p.add_argument('--remote-dir',default='/home/ggbird/codex-five-20261027')
    p.add_argument('--fleet-port',type=int,default=18161);p.add_argument('--platform-port',type=int,default=18162)
    p.add_argument('--tunnel-port',type=int,default=18163);p.add_argument('--vm-receiver-port',type=int,default=18172)
    p.add_argument('--vm-operator-port',type=int,default=18173);p.add_argument('--rounds',type=int,default=3)
    p.add_argument('--reboot',action='store_true')
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,24}',a.prefix):raise ValueError('invalid prefix')
    if not re.fullmatch(r'[0-9]+-[0-9]+',a.usb_bus):raise ValueError('invalid USB bus')
    for value in (a.pc_ip,a.board_ip,a.bind):
        ip=ipaddress.IPv4Address(value)
        if not ip.is_private or ip.is_loopback:raise ValueError('private non-loopback IP required')
    for value in (a.test_key,a.remote_dir):
        if not re.fullmatch(r'/home/[A-Za-z0-9_./-]+',value):raise ValueError('invalid VM path')
    if any(not 1024<=v<=65535 for v in (a.fleet_port,a.platform_port,a.tunnel_port,a.vm_receiver_port,a.vm_operator_port)):
        raise ValueError('invalid port')
    out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=False)
    vm_base='/home/ggbird/.spine-acceptance-private'
    remote_db=vm_base+'/'+a.prefix+'.sqlite';remote_pid=vm_base+'/'+a.prefix+'.pid'
    ssh=['ssh','-b',a.bind,'-i',a.identity,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes']
    def remote(*args,timeout=10):
        return subprocess.run(ssh+[a.vm,shlex.join(args)],capture_output=True,text=True,timeout=timeout)
    for target in (remote_db,remote_pid):
        r=remote('test','-e',target)
        if r.returncode==0:raise FileExistsError('VM test artifact already exists')
        if r.returncode!=1:raise RuntimeError('cannot inspect VM test artifacts')
    for target in (a.test_key,a.remote_dir+'/vela_spine/host/acceptance_operator.py',
                   a.remote_dir+'/vela_spine/host/acceptance_reboot.py'):
        if remote('test','-f',target).returncode:raise RuntimeError('VM test prerequisite missing')
    real_key=remote('realpath','-e',a.test_key)
    if real_key.returncode or not real_key.stdout.strip().startswith(vm_base+'/'):
        raise ValueError('test key must resolve inside the isolated acceptance directory')
    perms=remote('stat','-c','%a',a.test_key)
    if perms.returncode or perms.stdout.strip()!='600':raise ValueError('test key must have mode 0600')
    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    children=[];logs=[];relay=None;thread=None
    def start(cmd,name):
        f=(out/name).open('w',encoding='utf-8');logs.append(f)
        proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,creationflags=creationflags)
        children.append(proc);return proc
    def wait_port(address,port,proc):
        for _ in range(60):
            if proc.poll() is not None:raise RuntimeError('service exited during startup')
            try:
                with socket.create_connection((address,port),timeout=.3):return
            except OSError:time.sleep(.1)
        raise RuntimeError('service did not listen')
    try:
        fleet_db=str((out/'fleet.sqlite3').resolve())
        fleet=start([sys.executable,'-m','host.board_sim_network','--database',fleet_db,
            '--bind',a.pc_ip,'--board',a.board_ip,'--port',str(a.fleet_port)],'fleet.log')
        wait_port(a.pc_ip,a.fleet_port,fleet)
        # A unique private PID file allows bounded cleanup of this exact remote server.
        inner='umask 077; echo $$ > '+shlex.quote(remote_pid)+'; exec '+shlex.join([
            'env','PYTHONPATH='+a.remote_dir+'/vela_spine','timeout','900','python3','-m',
            'host.simulated_platform','--db',remote_db,'--key-file',a.test_key,
            '--receiver-port',str(a.vm_receiver_port),'--operator-port',str(a.vm_operator_port)])
        platform=start(ssh+[a.vm,shlex.join(['sh','-c',inner])],'platform.log')
        time.sleep(.8)
        if platform.poll() is not None:raise RuntimeError('VM platform exited during startup')
        tunnel=start(ssh+['-N','-o','ExitOnForwardFailure=yes','-L',
            '127.0.0.1:%d:127.0.0.1:%d'%(a.tunnel_port,a.vm_receiver_port),a.vm],'tunnel.log')
        wait_port('127.0.0.1',a.tunnel_port,tunnel)
        relay=RestrictedRelay((a.pc_ip,a.platform_port),a.board_ip,('127.0.0.1',a.tunnel_port))
        thread=threading.Thread(target=relay.serve_forever,daemon=True);thread.start()
        cmd=[sys.executable,'-m','host.real_board_acceptance','--database',fleet_db,
             '--output',str((out/'report.json').resolve()),'--identity',a.identity,'--bind',a.bind,
             '--vm',a.vm,'--remote-dir',a.remote_dir,'--prefix',a.prefix,'--rounds',str(a.rounds),
             '--fleet-endpoint',a.pc_ip+':'+str(a.fleet_port),'--platform-endpoint',a.pc_ip+':'+str(a.platform_port),
             '--board-ip',a.board_ip,'--usb-bus',a.usb_bus,'--human-test-key',a.test_key,'--operator-db',remote_db]
        if a.reboot:cmd.append('--reboot')
        result=subprocess.run(cmd,timeout=700,creationflags=creationflags)
        if result.returncode:raise RuntimeError('board acceptance failed; see report.json')
        print('ACCEPTANCE_COMPLETE',flush=True)
    finally:
        if relay:relay.shutdown();relay.server_close()
        if thread:thread.join(timeout=5)
        # Verify PID command line before signalling; never stop another service.
        code=('import os,signal; p='+repr(remote_pid)+'; db='+repr(remote_db)+'; '
              'pid=int(open(p).read()); cmd=open("/proc/%d/cmdline"%pid,"rb").read(); '
              'assert b"host.simulated_platform" in cmd and db.encode() in cmd; os.kill(pid,signal.SIGTERM)')
        try:remote('python3','-c',code)
        except (OSError,subprocess.TimeoutExpired):pass
        for child in reversed(children):
            if child.poll() is None:child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        for f in logs:f.close()

if __name__=='__main__':main()
