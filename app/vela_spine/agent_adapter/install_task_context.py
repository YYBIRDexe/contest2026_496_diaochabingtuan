"""Install only task policy in USER.md; preserve private text and mode 0600.

Run on the Linux ADB host with no ai_agent process. --rollback restores the
original bytes only if the board still matches this install's recorded result.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', type=Path, required=True)
    parser.add_argument('--serial', default='1234')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    base = args.backup_dir.resolve()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if base.stat().st_mode & 0o077:
        raise RuntimeError('private backup directory required')
    remote = '/data/ai_agent/config/USER.md'
    temporary = '/data/ai_agent/config/USER.spine-task-policy-new'
    def adb(*parts):
        result = subprocess.run(['adb', '-s', args.serial, *parts],
                                capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError('ADB operation failed: ' + parts[0])
        return result.stdout
    # Read complete process output through a file: the microADB shell output
    # transport can truncate long ps responses when printed directly.
    adb('shell', 'ps > /data/spine-task-policy-ps.txt')
    adb('pull', '/data/spine-task-policy-ps.txt', str(base/'processes.txt'))
    if re.search(r'\bai_agent(?:\s|$)', (base/'processes.txt').read_text()):
        raise RuntimeError('stop ai_agent before updating its context')
    adb('pull', remote, str(base/'current.md'))
    original = (base/'current.md').read_bytes()
    digest = lambda data: hashlib.sha256(data).hexdigest()
    record = base/'installation.json'
    backup = base/'USER.original.md'
    if args.rollback:
        proof = json.loads(record.read_text())
        if digest(original) != proof['installed_sha256']:
            raise RuntimeError('context changed since install; preserve it')
        replacement = backup.read_bytes()
        if digest(replacement) != proof['original_sha256']:
            raise RuntimeError('original backup changed')
    else:
        policy = Path(__file__).with_name('task-context-policy.md').read_bytes()
        marker = b'<!-- VELA_SPINE_TASK_POLICY_V1 -->'
        if marker in original:
            raise RuntimeError('task policy already present; inspect existing install')
        with backup.open('xb') as stream:
            stream.write(original)
        replacement = original + b'\n\n' + policy
    staged = base/'staged.md'
    staged.write_bytes(replacement)
    staged.chmod(0o600)
    adb('push', str(staged), temporary)
    adb('pull', temporary, str(base/'readback.md'))
    if (base/'readback.md').read_bytes() != replacement:
        raise RuntimeError('staged content mismatch; original untouched')
    if '-rw-------' not in adb('shell', 'ls -l ' + temporary).decode():
        raise RuntimeError('staged context must be mode 0600; original untouched')
    adb('shell', 'mv ' + temporary + ' ' + remote)
    adb('pull', remote, str(base/'installed.md'))
    if (base/'installed.md').read_bytes() != replacement:
        raise RuntimeError('installed content readback mismatch')
    if not args.rollback:
        record.write_text(json.dumps({'original_sha256': digest(original),
                                      'installed_sha256': digest(replacement)}, indent=2))
    print(json.dumps({'context_installed': not args.rollback,
                      'context_restored': args.rollback, 'readback_verified': True,
                      'mode_0600': True}))

if __name__ == '__main__':
    main()
