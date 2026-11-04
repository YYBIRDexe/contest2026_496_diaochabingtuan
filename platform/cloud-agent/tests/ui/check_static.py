#!/usr/bin/env python3
"""Static checks for the VelaGuard console UI. Standard library only.

This is not a browser test and does not claim visual or backend verification.
Run from platform/cloud-agent:  python3 tests/ui/check_static.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"
APP = STATIC / "app.js"
DEMO = STATIC / "demo-data.js"
STYLES = STATIC / "styles.css"

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def read(path):
    check(path.is_file(), "missing file: %s" % path)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main():
    index = read(INDEX)
    app = read(APP)
    demo = read(DEMO)
    styles = read(STYLES)

    for page in ("tasks", "inbox", "field", "review"):
        check('data-page-panel="%s"' % page in index, "missing page panel: " + page)

    for required_id in (
        "chat-form",
        "chat-transcript",
        "send-button",
        "plans-list",
        "inbox-real",
        "demo-wo-list",
        "demo-wo-detail",
        "demo-topology",
        "review-content",
        "settings-modal",
        "confirm-modal",
    ):
        check('id="%s"' % required_id in index, "missing element id: " + required_id)

    for asset in (
        "styles.css",
        "app.js",
        "demo-data.js",
        "favicon.svg",
        "assets/water-scene.png",
        "assets/water-lines.svg",
        "assets/water-lines-dark.svg",
        "assets/water-dam.svg",
    ):
        check((STATIC / asset).is_file(), "missing static asset: " + asset)

    check("innerHTML" not in app, "app.js must not use innerHTML")
    check("insertAdjacentHTML" not in app, "app.js must not use insertAdjacentHTML")
    check("document.write" not in app, "app.js must not use document.write")
    check("fetch(" not in demo, "demo-data.js must not call fetch")
    check("fetch(" not in app or '/api/chat' in app, "app.js should use the chat API")
    check("conversation_id" in app, "app.js should preserve conversation_id")
    check("/api/proposals/" in app and "/decision" in app, "app.js should keep proposal decisions")
    check("/api/capabilities" in app, "app.js should read capabilities")
    check("cloudAgentToken" in app, "access token should stay in sessionStorage")
    check("224px" in styles, "sidebar width 224px missing")
    check("--teal: #087f9c" in styles.lower(), "river teal token missing")
    check("--navy: #102d46" in styles.lower(), "deep sea navy token missing")
    check("@media (prefers-reduced-motion: reduce)" in styles, "reduced motion rule missing")
    check("示例数据 · 不控制真实设备" in index, "persistent demo warning missing")
    check("不控制真实设备" in index, "demo safety copy missing")
    check("water-scene.png" in index, "Codex water-scene illustration not referenced")
    check("water-dam.svg" not in index, "water-dam.svg should not be the task-page illustration")
    check("WO-DEMO-011" in demo and "WO-DEMO-017" in demo and "WO-DEMO-021" in demo, "demo workorders missing")
    check("RESOLVED" not in index, "internal workorder code leaked into UI")
    check("none_v1" not in index, "internal executor code leaked into index")

    # Reject inline style attributes (CSP style-src 'self') in the page shell.
    check(re.search(r"<[^>]+\sstyle\s*=", index) is None, "inline style attribute found in index.html")

    # Referenced same-origin static assets must exist.
    for ref in sorted(set(re.findall(r"/static/([A-Za-z0-9_./-]+)", index))):
        if ref and not (STATIC / ref).is_file():
            failures.append("index.html references missing /static/" + ref)

    if failures:
        print("FAIL %d static check(s)" % len(failures))
        for item in failures:
            print(" - " + item)
        return 1
    print("PASS static UI checks (not a browser, visual or backend test)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
