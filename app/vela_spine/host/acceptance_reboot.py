"""Verify a real board's normal reboot and one isolated task's persistence."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--task',required=True)
    p.add_argument('--bus',default='6-1');p.add_argument('--usbip-host',default='192.168.6.1')
    p.add_argument('--usbip',default='/usr/lib/linux-tools/6.8.0-40-generic/usbip')
    a=p.parse_args()
    if not re.fullmatch(r'/data/vg-[A-Za-z0-9_-]+',a.root):raise ValueError('invalid isolated root')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',a.task):raise ValueError('invalid task')
    if not re.fullmatch(r'[0-9]+-[0-9]+',a.bus):raise ValueError('invalid bus')
    if not ipaddress.IPv4Address(a.usbip_host).is_private:raise ValueError('invalid USB/IP host')
    def run(*args,timeout=5):
        try:return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired:return None
    def adb(*args,timeout=5):return run('adb','-s','1234',*args,timeout=timeout)
    r=adb('shell','uname','-a')
    if not r or r.returncode:raise RuntimeError('board unavailable before reboot')
    r=adb('reboot')
    if not r or r.returncode:raise RuntimeError('reboot request failed')
    deadline=time.monotonic()+100;lost=False
    while time.monotonic()<deadline:
        ports=run(a.usbip,'port')
        if ports and '<Port in Use>' not in ports.stdout:
            run('sudo',a.usbip,'attach','-r',a.usbip_host,'-b',a.bus)
        state=adb('get-state')
        online=state and state.returncode==0 and state.stdout.strip()=='device'
        if not online:lost=True
        if lost and online:
            r=adb('shell','uname','-a')
            if r and r.returncode==0:break
        time.sleep(.3)
    else:raise RuntimeError('board did not return after reboot')
    test=adb('shell','vela_spine','--selftest')
    if not test or '"selftest":"PASS"' not in test.stdout:raise RuntimeError('selftest failed')
    command='vela_spine --task-view '+a.root+' '+a.task+' > '+a.root+'/reboot-view.json'
    r=adb('shell',command)
    if not r or r.returncode or 'nsh: ' in r.stdout:raise RuntimeError('cannot read task')
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'view.json';r=adb('pull',a.root+'/reboot-view.json',str(path))
        if not r or r.returncode:raise RuntimeError('task readback failed')
        if json.loads(path.read_text())['tasks'][0]['state']!='STOP_CONFIRMED':
            raise RuntimeError('task state not retained')
        r=adb('shell','ps > '+a.root+'/reboot-ps.txt')
        if not r or r.returncode or 'nsh: ' in r.stdout:raise RuntimeError('cannot inspect services')
        ps_path=Path(tmp)/'ps.txt';r=adb('pull',a.root+'/reboot-ps.txt',str(ps_path))
        if not r or r.returncode:raise RuntimeError('service readback failed')
        if not any(re.search(r'\svela_spine --task-service(?:\s|$)',line) and
                   'sh -c' not in line for line in ps_path.read_text().splitlines()):
            raise RuntimeError('task service did not start after reboot')
    for _ in range(15):
        r=adb('shell','uname','-a')
        if not r or r.returncode:raise RuntimeError('ADB interrupted')
        time.sleep(2)
    print('STABLE_30_SECONDS')

if __name__=='__main__':main()
