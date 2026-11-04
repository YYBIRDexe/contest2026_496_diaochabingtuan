"""Route project Codex snapshots to its real repo; keep upstream gating intact."""
import json
import os
from pathlib import Path
import subprocess
import sys
from collector_lock import collector_lock

BASE = Path(__file__).resolve().parent


def capture(event):
    with collector_lock():
        return _capture(event)


def _capture(event):
    cfg = json.loads((BASE / 'settings.json').read_text(encoding='utf-8-sig'))
    if cfg.get('privacy_pause'):
        return subprocess.CompletedProcess([], 0, stdout='', stderr='')
    cwd = Path(event['cwd']).resolve()
    target = cwd
    configured = cfg.get('official_repo')
    if configured:
        repo = Path(configured).resolve()
        workspace = repo.parent
        if cwd == workspace or workspace in cwd.parents:
            # These are products of a real repo init/sync, not a marker fixture.
            if not (workspace / '.repo/manifest.xml').is_file():
                raise RuntimeError('Official manifest is not initialized')
            if not (repo / '.git').exists():
                raise RuntimeError('Official team checkout is missing')
            target = repo
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run(
        [sys.executable, str(Path.home()/'.claude/contest-shared/snapshot_core.py'),
         '--tool', 'codex'], input=json.dumps(event), cwd=target,
        env=env, capture_output=True, text=True, encoding='utf-8', timeout=25)
    return result
