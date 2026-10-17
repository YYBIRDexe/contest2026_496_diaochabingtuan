"""Compact read-only audit for remaining service and WLAN blockers."""

from datetime import datetime
import json
from pathlib import Path
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
KEY = BASE / "work/keys/formation_autonomy_ed25519"
HOST_KEYS = BASE / "work/keys/formation_known_hosts"
OUT = BASE / "work/agent-network-audit"
OUT.mkdir(exist_ok=True)


def connect(index: int) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.load_host_keys(str(HOST_KEYS))
    c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(
        f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
        timeout=20, banner_timeout=20, auth_timeout=20,
    )
    c.get_transport().set_keepalive(5)
    return c


def run(c: paramiko.SSHClient, command: str, timeout: int = 35) -> dict:
    started = time.monotonic()
    _, stdout, stderr = c.exec_command(command, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return {
        "exit": stdout.channel.recv_exit_status(),
        "elapsed_s": round(time.monotonic() - started, 3),
        "stdout": out,
        "stderr": err,
    }


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {"started": datetime.now().astimezone().isoformat(), "robots": {}}
    for index in range(1, 5):
        robot = f"robot{index}"
        print(f"{robot}: read-only audit", flush=True)
        c = connect(index)
        try:
            commands = {
                "service": (
                    f"systemctl show formation-agent@{robot}.service "
                    "-p ActiveState -p SubState -p Result -p MainPID -p NRestarts "
                    "-p ExecStartPre -p ExecStart -p ExecStop -p TimeoutStopUSec "
                    "-p KillMode -p KillSignal -p Restart -p FragmentPath; "
                    f"systemctl status formation-agent@{robot}.service --no-pager -l; "
                    "systemd-analyze verify /etc/systemd/system/formation-agent@.service 2>&1 || true"
                ),
                "agent_process": (
                    "docker exec MentorPi /bin/bash -lc '"
                    f"pids=$(pgrep -f \"^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id {robot}$\" || true); "
                    "echo pids=$pids count=$(wc -w <<<\"$pids\"); "
                    "for p in $pids; do ps -p $p -o pid,ppid,lstart,etimes,stat,%cpu,%mem,args; "
                    "echo STATUS; grep -E \"^(Name|State|Threads|VmRSS|voluntary_ctxt_switches|nonvoluntary_ctxt_switches):\" /proc/$p/status; "
                    "echo CGROUP; cat /proc/$p/cgroup; echo SOCKET_FDS; ls -l /proc/$p/fd 2>/dev/null | grep socket | wc -l; done'"
                ),
                "agent_log": (
                    f"journalctl -u formation-agent@{robot}.service -b -n 100 --no-pager "
                    "--output=short-iso"
                ),
                "units": (
                    f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service "
                    "fleet-bridge@" + robot + ".service mentorpi-localization.service "
                    "mentorpi-localization-vendor-domain.service 2>&1 || true"
                ),
                "dds_profile": (
                    "docker exec MentorPi /bin/bash -lc '"
                    "echo PROFILE; sha256sum /home/ubuntu/shared/fleet_udp_unicast.xml; "
                    "sed -n \"1,260p\" /home/ubuntu/shared/fleet_udp_unicast.xml; "
                    "echo ENVIRONMENTS; for p in $(pgrep -f \"reconfiguration_agent[.]py|fleet_bridge[.]py|reconfiguration_ros[.]py\" || true); do "
                    "echo PID=$p; tr \\\"\\\\0\\\" \\\"\\\\n\\\" </proc/$p/environ | grep -E \"ROS_DOMAIN_ID|FASTRTPS|RMW_IMPLEMENTATION\" || true; done'"
                ),
                "wifi": (
                    "echo DRIVER; readlink -f /sys/class/net/wlan0/device/driver || true; "
                    "basename $(readlink -f /sys/class/net/wlan0/device/driver) 2>/dev/null || true; "
                    "echo WPA; wpa_cli -i wlan0 status 2>&1 || true; "
                    "echo PROC; cat /proc/net/wireless; "
                    "echo POWERSAVE; for f in /sys/module/*/parameters/*power* /sys/class/net/wlan0/power/control; do "
                    "test -r $f && printf '%s=' $f && cat $f; done 2>/dev/null || true; "
                    "echo LINK; ip -s link show wlan0; "
                    "echo ETHTOOL; ethtool -S wlan0 2>&1 || true"
                ),
                "load": (
                    "uptime; free -m; ps -eo pid,comm,%cpu,%mem,args --sort=-%cpu | head -n 25; "
                    "docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}} {{.NetIO}}' MentorPi"
                ),
                "network_delta": (
                    "python3 - <<'PY'\n"
                    "import json,time\n"
                    "def snap():\n"
                    " d={}\n"
                    " for line in open('/proc/net/dev'):\n"
                    "  if 'wlan0:' in line:\n"
                    "   v=line.split(':',1)[1].split(); d['rx_bytes']=int(v[0]); d['rx_packets']=int(v[1]); d['rx_drop']=int(v[3]); d['tx_bytes']=int(v[8]); d['tx_packets']=int(v[9]); d['tx_drop']=int(v[11])\n"
                    " snmp={}\n"
                    " lines=open('/proc/net/snmp').read().splitlines()\n"
                    " for i in range(0,len(lines)-1,2):\n"
                    "  if lines[i].startswith('Udp:') and lines[i+1].startswith('Udp:'):\n"
                    "   keys=lines[i].split()[1:]; vals=lines[i+1].split()[1:]; snmp={k:int(v) for k,v in zip(keys,vals)}\n"
                    " d.update({'udp_'+k:v for k,v in snmp.items()}); return d\n"
                    "a=snap(); time.sleep(10); b=snap(); print(json.dumps({k:b[k]-a[k] for k in a},sort_keys=True))\n"
                    "PY"
                ),
                "sockets": (
                    "ss -uapn | grep -E 'python3|179[0-9][0-9]|180[0-9][0-9]' | head -n 240 || true"
                ),
            }
            data = {}
            for name, command in commands.items():
                data[name] = run(c, command, timeout=45)
            report["robots"][robot] = data
        finally:
            c.close()
    report["finished"] = datetime.now().astimezone().isoformat()
    path = OUT / f"blockers-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
