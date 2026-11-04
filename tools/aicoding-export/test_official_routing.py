import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('official_capture', Path(__file__).with_name('official_capture.py'))
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class RoutingTest(unittest.TestCase):
    def test_routes_to_team_repo_without_changing_original_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root/'team'
            (repo/'.git').mkdir(parents=True)
            (root/'.repo').mkdir()
            (root/'.repo/manifest.xml').write_text('<manifest/>')
            (root/'settings.json').write_text(json.dumps({'official_repo':str(repo)}))
            event = {'cwd':str(root),'session_id':'fixture','transcript_path':'original.jsonl'}
            with patch.object(capture, 'BASE', root), patch.object(capture.subprocess, 'run') as run:
                capture.capture(event)
                self.assertEqual(run.call_args.kwargs['cwd'], repo)
                self.assertEqual(json.loads(run.call_args.kwargs['input']), event)

    def test_similarly_named_outside_directory_is_not_routed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'settings.json').write_text(json.dumps({'official_repo':str(root/'team')}))
            outside = Path(str(root)+'-private')
            event = {'cwd':str(outside),'session_id':'fixture'}
            with patch.object(capture, 'BASE', root), patch.object(capture.subprocess, 'run') as run:
                capture.capture(event)
                self.assertEqual(run.call_args.kwargs['cwd'], outside)


if __name__ == '__main__':
    unittest.main()
