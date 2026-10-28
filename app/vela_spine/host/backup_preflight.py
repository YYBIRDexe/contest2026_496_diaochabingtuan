"""Read-only verification of an existing private, two-copy board backup.

Never contacts a device, restores files, reads credentials into output, or
claims that the target hardware or firmware has been validated.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)


def relative_path(name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('invalid backup relative path')
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or '..' in path.parts or str(path) != name or ':' in name:
        raise ValueError('backup path escapes snapshot')
    return path


def contained_file(root, name):
    rel = relative_path(name)
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink in snapshot')
    return current


def verify_backup(base, supported_states):
    base = Path(base)
    if base.is_symlink():
        raise ValueError('symlink backup root')
    manifest = read_json(base / 'manifest.json')
    modes = read_json(base / 'modes.json')
    if not isinstance(manifest, dict) or not manifest or not isinstance(modes, dict):
        raise ValueError('missing backup manifests')
    if not supported_states or any(not re.fullmatch(r'[A-Z_]+', s) for s in supported_states):
        raise ValueError('explicit target task states required')
    for name, digest in manifest.items():
        relative_path(name)
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('invalid content digest')
        if name not in modes:
            raise ValueError('missing file permission record')
        for copy in ('first', 'check'):
            root = base / copy
            if root.is_symlink() or not root.is_dir():
                raise ValueError('missing independent copy')
            file = contained_file(root, name)
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                raise ValueError('snapshot file missing or hash mismatch')
    for name, mode in modes.items():
        relative_path(name)
        if type(mode) is not int or not 0 <= mode <= 0o7777:
            raise ValueError('invalid permission record')
        if any(not contained_file(base / copy, name).exists() for copy in ('first', 'check')):
            raise ValueError('permission record references missing entry')
    for copy in ('first', 'check'):
        for path in (base / copy).rglob('*'):
            if path.is_symlink():
                raise ValueError('symlink in snapshot tree')
            name = path.relative_to(base / copy).as_posix()
            if path.is_file() and path.name != 'lock' and not path.name.endswith(('.lock', '.tmp')):
                if name not in manifest:
                    raise ValueError('unmanifested file in backup')
            if path.is_dir() and name not in modes:
                raise ValueError('missing directory permission record')
    main_name = 'ai_agent/sp/tasks.json'
    counts = {}
    if main_name in manifest:
        ledger = read_json(contained_file(base / 'first', main_name))
        if not isinstance(ledger, dict) or type(ledger.get('schema')) is not int or ledger['schema'] != 1:
            raise ValueError('unsupported live task ledger schema')
        tasks = ledger.get('tasks')
        if not isinstance(tasks, list):
            raise ValueError('invalid live task ledger')
        for task in tasks:
            state = task.get('state') if isinstance(task, dict) else None
            if state not in supported_states:
                raise ValueError('target firmware does not support a live task state')
            counts[state] = counts.get(state, 0) + 1
    return {'backup_content_verified': True, 'copies': 2,
            'files_per_copy': len(manifest), 'permission_records': len(modes),
            'live_task_states': counts, 'target_state_list_checked': True,
            'live_task_ledger_present': main_name in manifest,
            'target_firmware_verified': False, 'restore_performed': False,
            'hardware_compatibility_verified': False,
            'note': 'Checks saved permission records, not current board permissions; '
                    'does not verify board ledger CRC or validate a firmware image.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--target-task-states', nargs='+', required=True)
    args = parser.parse_args()
    try:
        result = verify_backup(args.backup, set(args.target_task_states))
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({'backup_content_verified': False,
                          'error_type': type(error).__name__,
                          'reason': 'Backup preflight failed; preserve files and inspect locally.',
                          'restore_performed': False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
