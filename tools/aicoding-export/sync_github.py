"""Upload only validated official Codex logs to the explicitly configured fork."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from collector_lock import collector_lock

BASE = Path(__file__).resolve().parent
# The watcher runs under pythonw.exe (GUI subsystem, no console). Without this
# flag every console child (git.exe) would get its own visible console window.
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def allowed_path(path, login):
    p = Path(path)
    root = Path('logs')/login
    return p == root/'manifest.json' or (
        root in p.parents and p.name.startswith('codex__') and p.suffix == '.jsonl')


def sync(cfg):
    repo = Path(cfg['official_repo'])
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', PYTHONUTF8='1')
    def git(*args):
        r = subprocess.run(['git','-c','http.version=HTTP/1.1',*args],cwd=repo,
            env=env,capture_output=True,text=True,encoding='utf-8',timeout=60,
            creationflags=CREATE_NO_WINDOW)
        if r.returncode:
            raise RuntimeError('git_'+args[0]+'_exit_'+str(r.returncode))
        return r.stdout.strip()
    login = cfg['github_login']
    branch = cfg['upload_branch']
    remote = cfg['upload_remote']
    if remote != 'https://github.com/YYBIRDexe/contest2026_496_diaochabingtuan.git':
        raise RuntimeError('Unexpected upload destination')
    with collector_lock():
        if git('branch','--show-current') != branch:
            raise RuntimeError('Unexpected upload branch')
        staged = git('diff','--cached','--name-only').splitlines()
        if any(not allowed_path(p,login) for p in staged):
            raise RuntimeError('Unrelated staged files')
        tracked = git('diff','--name-only','--',f'logs/{login}').splitlines()
        untracked = git('ls-files','--others','--exclude-standard','--',f'logs/{login}').splitlines()
        paths = sorted(set(tracked+untracked+staged))
        if any(not allowed_path(p,login) for p in paths):
            raise RuntimeError('Non-Codex changes in log directory')
        for rel in paths:
            text = (repo/rel).read_text(encoding='utf-8')
            if re.search(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|(?<![\w-])sk-[A-Za-z0-9_-]{24,}|Bearer\s+[A-Za-z0-9._-]{24,}',text):
                raise RuntimeError('Credential pattern detected; upload stopped')
        validator = BASE.parent/'official-contest-collector/skills/contest-log-collector/tools/validate-log.py'
        checked = subprocess.run([sys.executable,str(validator),str(repo/'logs')],
            env=env,capture_output=True,timeout=30)
        if checked.returncode:
            raise RuntimeError('Official validation failed')
        if paths:
            git('add','--',*paths)
            if git('diff','--cached','--name-only'):
                git('commit','-s','-m','logs: sync official Codex development sessions')
        head = git('rev-parse','HEAD')
    # Network work does not block the hook or background snapshot writer.
    git('push',remote,f'HEAD:refs/heads/{branch}')
    actual = git('ls-remote',remote,f'refs/heads/{branch}').split()[0]
    if actual != head:
        raise RuntimeError('Remote commit mismatch')
    return {'status':'synced','commit':head,'remote':remote,'branch':branch,
            'changed_paths':len(paths),'updated_at':datetime.now(timezone.utc).isoformat()}


def run(cfg):
    try:
        result = sync(cfg)
    except Exception as exc:
        result = {'status':'failed','error_type':type(exc).__name__,
                  'reason':str(exc) if isinstance(exc,RuntimeError) else 'Retry on next cycle',
                  'updated_at':datetime.now(timezone.utc).isoformat()}
    output = Path(cfg['output'])/'upload-health.json'
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(output)
    return result


if __name__ == '__main__':
    cfg = json.loads((BASE/'settings.json').read_text(encoding='utf-8'))
    result = run(cfg)
    print(json.dumps(result,ensure_ascii=False))
    sys.exit(0 if result['status']=='synced' else 1)
