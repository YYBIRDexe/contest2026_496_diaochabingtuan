import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from compression import zstd

spec = importlib.util.spec_from_file_location('archive', Path(__file__).with_name('project_archive.py'))
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class ArchiveTest(unittest.TestCase):
    def test_scope_boundary_and_raw_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'project'
            cfg = {'project_roots':[str(root)], 'output':str(Path(tmp)/'out')}
            src = Path(tmp)/'rollout.jsonl'
            src.write_text(json.dumps({'payload':{'cwd':str(root),'id':'sample'}})+'\n', encoding='utf-8')
            result = archive.archive(src, 'codex', cfg)
            self.assertIsNotNone(result)
            self.assertEqual((Path(cfg['output'])/'codex/sample/rollout.jsonl').read_bytes(), src.read_bytes())
            self.assertFalse(archive.allowed(str(root)+'-private', cfg['project_roots']))
            src.write_text(json.dumps({'payload':{'cwd':str(root)+'-private','id':'private'}})+'\n', encoding='utf-8')
            self.assertIsNone(archive.archive(src, 'codex', cfg))
            self.assertFalse((Path(cfg['output'])/'codex/private').exists())

    def test_dsh_keeps_tool_identity_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg={'project_roots':[tmp], 'output':str(Path(tmp)/'out')}
            src=Path(tmp)/'session.v4.jsonl.zstd'
            raw=(json.dumps({'type':'session','cwd':tmp,'id':'dsh-test'})+'\n').encode()
            src.write_bytes(zstd.compress(raw))
            meta=archive.archive(src,'dsh',cfg)
            folder=Path(cfg['output'])/'dsh/dsh-test'
            self.assertEqual((folder/src.name).read_bytes(),src.read_bytes())
            self.assertEqual((folder/'transcript.raw.jsonl').read_bytes(),raw)
            self.assertFalse(meta['contest_supported_tool'])
            self.assertFalse(meta['official_collector_output'])


if __name__=='__main__':
    unittest.main()
