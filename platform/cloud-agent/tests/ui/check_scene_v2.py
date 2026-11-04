#!/usr/bin/env python3
"""Static checks for the isolated scene-v2 sample. Standard library only.

This is not a browser test and does not claim visual, microphone or ASR verification.
Run from platform/cloud-agent:  python3 tests/ui/check_scene_v2.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static" / "scene-v2"
INDEX = STATIC / "index.html"
CSS = STATIC / "scene.css"
SCENE = STATIC / "scene.js"
VOICE = STATIC / "voice.js"
CONFIG = STATIC / "scene-config.js"
ASR = STATIC / "asr-config.json"
API = ROOT / "cloud_agent" / "http_api.py"

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def read(path):
    check(path.is_file(), "missing file: %s" % path)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main():
    index = read(INDEX)
    css = read(CSS)
    scene = read(SCENE)
    voice = read(VOICE)
    config = read(CONFIG)
    api = read(API)

    for asset in ("assets/scene-draft.svg", "assets/scene-hero.svg", "asr-config.json", "assets/README.md"):
        check((STATIC / asset).is_file(), "missing scene-v2 asset: " + asset)

    for spot in ("dam", "river", "building"):
        check('data-spot="%s"' % spot in index, "missing hotspot: " + spot)
        check('"%s":' % spot in config, "missing hotspot coordinate: " + spot)

    check("scene-v2.png" not in index, "old scene-v2.png must not be referenced by the page")
    check("scene-draft.svg" in index, "committed draft art must stay as the page default image")
    check('"scene-v2.png"' not in config and '"/scene-v2.png"' not in config, "old scene-v2.png must not be configured")
    check("1600" in config and "900" in config, "scene asset size should match the draft art")

    # The delivered slot is either explicit null (nothing delivered yet) or a local,
    # existing asset under /static/scene-v2/assets/ with a version and a size.
    config_code = re.sub(r"/\*.*?\*/", "", config, flags=re.S)
    match = re.search(r'asset:\s*(null|"([^"]*)")', config_code)
    check(match is not None, "scene config must declare the delivered asset slot")
    if match and match.group(1) != "null":
        configured = match.group(2)
        check(configured.startswith("/static/scene-v2/assets/"),
              "delivered asset must be a local file under /static/scene-v2/assets/")
        check((ROOT / configured.lstrip("/")).is_file(),
              "configured asset does not exist: " + configured)
        check(re.search(r'assetVersion:\s*"[^"]+"', config_code) is not None,
              "delivered asset needs assetVersion for cache busting")
        check(re.search(r'assetSize:\s*\{\s*w:\s*\d+,\s*h:\s*\d+\s*\}', config_code) is not None,
              "delivered asset needs assetSize")

    check("/api/chat" in scene, "scene.js should keep the real /api/chat call")
    check("conversation_id" in scene, "scene.js should keep conversation_id")
    check("textContent" in scene and "innerHTML" not in scene, "scene.js must build DOM with textContent")
    check("innerHTML" not in voice, "voice.js must not use innerHTML")
    check("voice_trigger" not in scene and "voice_trigger" not in voice, "old voice_trigger must not be called")
    check("vcmd" not in scene and "vcmd" not in voice, "old vcmd execution must not be wired")
    check("SpeechRecognition" not in scene and "SpeechRecognition" not in voice, "do not pretend Web Speech exists")
    check("MediaRecorder" in voice, "voice.js should use real MediaRecorder capture")
    check("getUserMedia" in voice, "voice.js should request real microphone capture")
    check("AbortController" in voice, "voice.js should bound ASR requests")
    check("onText" in voice and "receiveTranscript" in scene, "transcript should enter the editable draft")

    check("prefers-reduced-motion" in css, "reduced-motion rule missing")
    check("data-static" in css and "data-static" in scene, "static display switch missing")
    check("@keyframes glint-drift" in css, "local water glint animation missing")
    check("mix-blend-mode" in css, "water glint should stay a light local layer")
    check(re.search(r"\.hotspot\s*\{[^}]*width:\s*72px", css) is not None, "hotspot hit area should be 72px")
    check(re.search(r"\.voice-btn\s*\{[^}]*min-height:\s*84px", css, re.S) is not None, "voice entry should be >=64px")
    check(re.search(r"\.send-btn\s*\{[^}]*min-height:\s*56px", css, re.S) is not None, "send target should be >=56px")

    check(re.search(r"<[^>]+\sstyle\s*=", index) is None, "inline style attribute found in index.html")
    check(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", index) is None, "inline script found in index.html")
    check("Content-Security-Policy" in api, "CSP header missing")
    check('path in ("/static/scene-v2/", "/static/scene-v2/index.html")' in api, "microphone policy is not scoped to scene-v2")
    check('mic_policy = "(self)"' in api and 'else "()"' in api, "non-scene pages must keep microphone=()")
    check("microphone=%s" in api, "microphone policy should be built from the scoped value")

    try:
        asr = json.loads(ASR.read_text(encoding="utf-8")) if ASR.is_file() else {}
    except ValueError:
        asr = {}
        failures.append("asr-config.json is not valid JSON")
    check(asr.get("endpoint") is None, "ASR endpoint must stay null until a real same-origin service exists")
    check(asr.get("credentials") == "same-origin", "ASR config must not carry credentials")
    check("voice_trigger" not in (asr.get("request", "") + asr.get("response", "")), "ASR contract must not use voice_trigger")

    if failures:
        print("FAIL %d scene-v2 static check(s)" % len(failures))
        for item in failures:
            print(" - " + item)
        return 1
    print("PASS scene-v2 static checks (not a browser, microphone, ASR or visual test)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
