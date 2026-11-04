"""Append the project query policy to official USER.md, preserving user text.

Run on the Linux ADB host. Private backups stay outside the source repository.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--serial', default='1234')
p.add_argument('--backup-dir', type=Path, required=True)
a = p.parse_args()
policy = Path(__file__).with_name('context-policy.md').read_text()
start, end = '<!-- VELA_SPINE_QUERY_POLICY_V1 -->', '<!-- /VELA_SPINE_QUERY_POLICY_V1 -->'
remote = '/data/ai_agent/config/USER.md'
a.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(a.backup_dir, 0o700)
with tempfile.TemporaryDirectory(dir=a.backup_dir) as tmp:
    path = Path(tmp)/'USER.md'
    def adb(*args):
        subprocess.run(['adb', '-s', a.serial, *args], check=True, capture_output=True)
    adb('pull', remote, str(path))  # Missing or unreadable USER.md is an error.
    original = path.read_bytes()
    backup = a.backup_dir/'USER.pre-spine.md'
    if not backup.exists():
        with backup.open('xb') as f:
            os.chmod(backup, 0o600)
            f.write(original)
    text = original.decode('utf-8')
    if start in text:
        assert text.count(start) == 1 and text.count(end) == 1
        left, rest = text.split(start)
        _, right = rest.split(end)
        text = left + policy.strip() + right
    else:
        assert end not in text
        text = text.rstrip() + '\n\n' + policy
    path.write_text(text)
    os.chmod(path, 0o600)
    adb('push', str(path), remote)
print('Project query policy installed; original user context preserved privately.')
