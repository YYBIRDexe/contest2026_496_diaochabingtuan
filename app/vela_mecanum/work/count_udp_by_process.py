"""Read-only AF_PACKET sampler that attributes outgoing peer UDP by socket owner."""

import argparse
from collections import Counter, defaultdict
import json
import os
import socket
import struct
import time


def udp_inodes():
    by_port = defaultdict(set)
    for path in ("/proc/net/udp", "/proc/net/udp6"):
        try:
            lines = open(path).read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            port = int(fields[1].split(":")[1], 16)
            inode = fields[9]
            by_port[port].add(inode)
    return by_port


def owners():
    inode_to_owner = defaultdict(set)
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    target = os.readlink(f"/proc/{pid}/fd/{fd}")
                except OSError:
                    continue
                if target.startswith("socket:["):
                    inode_to_owner[target[8:-1]].add((int(pid), cmdline))
        except OSError:
            continue
    return inode_to_owner


def label(cmdline):
    for name in ("fleet_bridge.py", "reconfiguration_agent.py", "command_bridge.py", "reconfiguration_ros.py", "cmd_vel_watchdog.py"):
        if name in cmdline:
            return name
    if cmdline:
        return cmdline.split()[0].rsplit("/", 1)[-1]
    return "unknown"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--interface", default="wlan0")
    p.add_argument("--local", required=True)
    p.add_argument("--peers", nargs="+", required=True)
    p.add_argument("--seconds", type=float, default=10)
    a = p.parse_args()
    ports, inode_owners = udp_inodes(), owners()
    port_labels = {}
    for port, inodes in ports.items():
        found = set()
        for inode in inodes:
            for _, cmdline in inode_owners.get(inode, ()):
                found.add(label(cmdline))
        port_labels[port] = "+".join(sorted(found)) if found else "kernel_or_unknown"

    counts, sizes = Counter(), Counter()
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800))
    sock.bind((a.interface, 0))
    sock.settimeout(0.25)
    start, end = time.monotonic(), time.monotonic() + a.seconds
    peers = set(a.peers)
    while time.monotonic() < end:
        try:
            frame = sock.recv(65535)
        except socket.timeout:
            continue
        if len(frame) < 42 or struct.unpack("!H", frame[12:14])[0] != 0x0800:
            continue
        ip = frame[14:]
        ihl = (ip[0] & 15) * 4
        if len(ip) < ihl + 8 or ip[9] != 17:
            continue
        src, dst = socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20])
        if dst != a.local or src not in peers:
            continue
        sport, dport, length = struct.unpack("!HHH", ip[ihl:ihl + 6])
        owner = port_labels.get(dport, "kernel_or_unknown")
        key = (owner, dport)
        counts[key] += 1
        sizes[key] += length
    elapsed = time.monotonic() - start
    rows = []
    for key, packets in counts.most_common():
        owner, port = key
        rows.append({"owner": owner, "source_port": port, "packets": packets,
                     "packets_per_s": round(packets / elapsed, 1),
                     "kbit_per_s": round(sizes[key] * 8 / elapsed / 1000, 1)})
    print(json.dumps({"elapsed_s": elapsed, "rows": rows}))


if __name__ == "__main__":
    main()
