"""Count IPv4 UDP frames by peer and RTPS port range without changing networking."""

import argparse
from collections import Counter
import json
import socket
import struct
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", default="wlan0")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--local", required=True)
    parser.add_argument("--peers", nargs="+", required=True)
    args = parser.parse_args()

    peers = set(args.peers)
    counts = Counter()
    sizes = Counter()
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800))
    sock.bind((args.interface, 0))
    sock.settimeout(0.25)
    start = time.monotonic()
    deadline = start + args.seconds
    while time.monotonic() < deadline:
        try:
            frame = sock.recv(65535)
        except socket.timeout:
            continue
        if len(frame) < 42 or struct.unpack("!H", frame[12:14])[0] != 0x0800:
            continue
        ip = frame[14:]
        ihl = (ip[0] & 0x0F) * 4
        if len(ip) < ihl + 8 or ip[9] != socket.IPPROTO_UDP:
            continue
        src = socket.inet_ntoa(ip[12:16])
        dst = socket.inet_ntoa(ip[16:20])
        src_port, dst_port, udp_len = struct.unpack("!HHH", ip[ihl : ihl + 6])
        if src == args.local and dst in peers:
            direction, peer = "tx", dst
        elif dst == args.local and src in peers:
            direction, peer = "rx", src
        else:
            continue
        counts[(direction, peer, "all_udp")] += 1
        sizes[(direction, peer, "all_udp")] += udp_len
        if 17900 <= src_port <= 18150 or 17900 <= dst_port <= 18150:
            counts[(direction, peer, "domain42_rtps")] += 1
            sizes[(direction, peer, "domain42_rtps")] += udp_len

    elapsed = time.monotonic() - start
    rows = []
    for key in sorted(counts):
        direction, peer, category = key
        packets = counts[key]
        rows.append(
            {
                "direction": direction,
                "peer": peer,
                "category": category,
                "packets": packets,
                "bytes": sizes[key],
                "packets_per_s": round(packets / elapsed, 2),
                "bytes_per_s": round(sizes[key] / elapsed, 2),
            }
        )
    print(json.dumps({"elapsed_s": elapsed, "rows": rows}, sort_keys=True))


if __name__ == "__main__":
    main()
