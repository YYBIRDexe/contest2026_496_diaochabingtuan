"""Windows entry point for the official openvela Codex collector.

Uses the real interpreter and subprocess cwd from the hook, retaining upstream
workspace gating. No notify replacement and no automatic Git operations.
"""
import json
from pathlib import Path
import sys
from official_capture import capture

payload = sys.stdin.read()
try:
    event = json.loads(payload)
except ValueError:
    sys.exit(0)
cwd = event.get('cwd')
if not cwd or not Path(cwd).is_dir():
    sys.exit(0)
result = capture(event)
# Upstream stderr is diagnostic only. Never expose converted transcript content.
sys.stderr.write(result.stderr)
sys.exit(result.returncode)
