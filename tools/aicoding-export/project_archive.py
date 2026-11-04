"""Local, project-scoped raw transcript archive. Not a contest adapter for DSH.

Keeps original bytes plus a source hash; never commits or uploads anything.
Uses Python 3.14's standard-library zstd reader for DSH v4 transcripts.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import time
from datetime import datetime, timezone
from compression import zstd

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "settings.json"


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def normalized(path):
    return os.path.normcase(os.path.abspath(path))


def allowed(cwd, roots):
    if not cwd:
        return False
    p = normalized(cwd)
    return any(p == normalized(r) or p.startswith(normalized(r) + os.sep) for r in roots)


def header(path, tool):
    opener = zstd.open if tool == 'dsh' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        first = json.loads(stream.readline())
    meta = first.get('payload', {}) if tool == 'codex' else first
    return meta.get('cwd'), meta.get('session_id') or meta.get('id')


def archive(path, tool, cfg):
    cwd, sid = header(path, tool)
    if not allowed(cwd, cfg['project_roots']) or not sid:
        return None
    # File may be growing. Copy a consistent byte snapshot without altering source.
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return None
    digest = hashlib.sha256(data).hexdigest()
    safe_sid = ''.join(c for c in str(sid) if c.isalnum() or c in '-_')
    folder = Path(cfg['output']) / tool / safe_sid
    dest = folder / path.name
    atomic(dest, data)
    # DSH compressed original is retained byte-for-byte. JSONL is a viewing copy.
    if tool == 'dsh':
        try:
            unpacked = zstd.decompress(data)
            for line in unpacked.splitlines():
                json.loads(line)
            atomic(folder / 'transcript.raw.jsonl', unpacked)
        except (ValueError, zstd.ZstdError):
            pass  # An active stream can end mid-frame; next stable change retries.
    metadata = {
        'tool': tool, 'session_id': sid, 'cwd': cwd,
        'source': str(path), 'sha256': digest, 'bytes': len(data),
        'source_mtime_ns': after.st_mtime_ns,
        'snapshot_at': datetime.now(timezone.utc).isoformat(),
        'format': 'original raw transcript; local supplemental archive',
        'contest_supported_tool': tool == 'codex',
        'official_collector_output': False,
        'official_eligibility': 'not established by this archive',
    }
    atomic(folder / 'source.json', json.dumps(metadata, ensure_ascii=False, indent=2).encode())
    return metadata


def scan(cfg, state):
    results = []
    for tool, root, pattern in [
        ('codex', Path.home()/'.codex/sessions', '*.jsonl'),
        ('dsh', Path.home()/'.dsh/sessions', 'session.v4.jsonl.zstd'),
    ]:
        for path in root.rglob(pattern):
            stat = path.stat()
            # Enroll only sessions modified from installation onwards.
            if (stat.st_mtime < cfg['capture_modified_since']
                    and str(path) not in cfg.get('initial_sources', [])):
                continue
            key = str(path)
            stamp = [stat.st_size, stat.st_mtime_ns]
            if state.get(key) == stamp:
                continue
            try:
                result = archive(path, tool, cfg)
                if result:
                    results.append(result)
                    if tool == 'codex' and cfg.get('official_repo'):
                        from official_capture import capture
                        official = capture({'session_id':result['session_id'],
                            'cwd':result['cwd'], 'transcript_path':result['source'],
                            'hook_event_name':'ArchiveSnapshot'})
                        if official.returncode:
                            print(json.dumps({'tool':'codex','official_capture':'failed',
                                'returncode':official.returncode}), flush=True)
                            continue
                    state[key] = stamp
                else:
                    # Out-of-scope files should not be repeatedly parsed.
                    cwd, _ = header(path, tool)
                    if not allowed(cwd, cfg['project_roots']):
                        state[key] = stamp
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zstd.ZstdError) as exc:
                # No transcript contents or exception string in diagnostic logs.
                print(json.dumps({'tool':tool,'error_type':type(exc).__name__}), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    mutex = None
    if args.watch:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, 'Local\\VelaGuardProjectTranscriptArchive')
        if ctypes.get_last_error() == 183:
            return
    state_path = Path(cfg['output'])/'watcher-state.json'
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    next_upload = 0
    while True:
        results = scan(cfg, state)
        atomic(state_path, json.dumps(state, indent=2).encode())
        atomic(Path(cfg['output'])/'health.json', json.dumps({
            'pid':os.getpid(), 'updated_at':datetime.now(timezone.utc).isoformat(),
            'watching':args.watch, 'sources_seen':len(state),
            'exports_this_scan':len(results), 'interval_seconds':cfg['interval_seconds'],
        }, indent=2).encode())
        if not args.watch:
            print(json.dumps({'exported':len(results),'tools':[r['tool'] for r in results]}))
            break
        if cfg.get('auto_upload_interval_seconds'):
            if time.monotonic() >= next_upload:
                from sync_github import run
                run(cfg)
                next_upload = time.monotonic()+cfg['auto_upload_interval_seconds']
        time.sleep(cfg['interval_seconds'])


if __name__ == '__main__':
    main()
