#!/usr/bin/env python3
"""Print a safe health summary and fail if the execution boundary is wrong."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main(argv=None):
    parser = argparse.ArgumentParser(description="cloud-agent health summary")
    parser.add_argument("--base-url", default=os.environ.get("CLOUD_AGENT_URL", "http://127.0.0.1:8130"))
    args = parser.parse_args(argv)
    url = args.base_url.rstrip("/") + "/api/health"
    try:
        with OPENER.open(url, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError) as exc:
        print("health request failed: %s" % exc, file=sys.stderr)
        return 2
    summary = {
        "service": data.get("service"),
        "version": data.get("version"),
        "status": data.get("status"),
        "configured": bool((data.get("llm") or {}).get("configured")),
        "model": (data.get("llm") or {}).get("model"),
        "base_url": (data.get("llm") or {}).get("base_url"),
        "execution_available": (data.get("execution") or {}).get("available"),
        "proposals": (data.get("store") or {}).get("proposals"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if summary["service"] != "velaguard-cloud-agent":
        print("unexpected service", file=sys.stderr)
        return 1
    if summary["execution_available"] is not False:
        print("execution must be unavailable in v1", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
