"""Synthetic fixture only. No real conversations enter contest logs here."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OfficialHookTest(unittest.TestCase):
    def test_cross_day_export_counts_all_files_without_rewriting_events(self):
        core_path = Path.home()/'.claude/contest-shared/snapshot_core.py'
        sys.path.insert(0,str(core_path.parent))
        spec = importlib.util.spec_from_file_location('core_crossday_test',core_path)
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root/'repo'
            member = root/'staging'/'test'
            old = repo/'logs/test/2026-10-20/codex__fixture.jsonl'
            new = member/'2026-10-21/codex__fixture.jsonl'
            old.parent.mkdir(parents=True)
            new.parent.mkdir(parents=True)
            old.write_text('{"seq":0}\n',encoding='utf-8')
            new.write_text('{"seq":1}\n',encoding='utf-8')
            before = old.read_bytes()
            (member/'manifest.json').write_text(json.dumps({'team_id':'test-team','github_login':'test','sessions':[{
                'session_id':'fixture','event_count':2,
                'file_path':'logs/test/2026-10-21/codex__fixture.jsonl'}]}),encoding='utf-8')
            core.auto_export_to_repo(repo,member,new,'fixture','test-team','test','codex')
            manifest = json.loads((repo/'logs/test/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['sessions'][0]['event_count'],2)
            self.assertEqual(old.read_bytes(),before)
            self.assertEqual((repo/'logs/test/2026-10-21/codex__fixture.jsonl').read_bytes(),new.read_bytes())

    def test_export_validate_and_idempotency(self):
        core=Path.home()/'.claude/contest-shared/snapshot_core.py'
        validator=Path(__file__).resolve().parents[1]/'official-contest-collector/skills/contest-log-collector/tools/validate-log.py'
        with tempfile.TemporaryDirectory(prefix='collector-synthetic-test-') as tmp:
            root=Path(tmp)
            (root/'.repo').mkdir()  # Isolated upstream gate test fixture, not a real workspace.
            transcript=root/'synthetic.jsonl'
            transcript.write_text('\n'.join(json.dumps(x) for x in [
                {'timestamp':'2026-10-17T00:00:00Z','type':'session_meta','payload':{'id':'install-smoke','cwd':str(root)}},
                {'timestamp':'2026-10-17T00:00:01Z','type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'Synthetic collector installation test.'}]}},
                {'timestamp':'2026-10-17T00:00:02Z','type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Synthetic response.'}]}}
            ])+'\n',encoding='utf-8')
            env=dict(os.environ,SESSION_LOG_DIR=str(root/'staging'),TEAM_ID='contest2026_test_install',GITHUB_LOGIN='installation-test',PYTHONUTF8='1')
            payload=json.dumps({'session_id':'install-smoke','cwd':str(root),'transcript_path':str(transcript),'hook_event_name':'Stop'})
            for _ in range(2):
                result=subprocess.run([sys.executable,str(core),'--tool','codex'],cwd=root,env=env,input=payload,capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stderr)
            logs=list((root/'logs').rglob('*.jsonl'))
            self.assertEqual(len(logs),1)
            self.assertEqual(len(logs[0].read_text(encoding='utf-8').splitlines()),2)
            valid=subprocess.run([sys.executable,str(validator),str(root/'logs')],env=env,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(valid.returncode,0,valid.stdout+valid.stderr)


if __name__=='__main__':
    unittest.main()
