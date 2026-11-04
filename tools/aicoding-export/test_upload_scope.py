import unittest
from sync_github import allowed_path


class UploadScopeTest(unittest.TestCase):
    def test_only_official_codex_paths_for_exact_member(self):
        self.assertTrue(allowed_path('logs/YYBIRDexe/manifest.json','YYBIRDexe'))
        self.assertTrue(allowed_path('logs/YYBIRDexe/2026-10-21/codex__session.jsonl','YYBIRDexe'))
        for path in ['logs/YYBIRDexe-private/2026-10-21/codex__x.jsonl',
                     'logs/YYBIRDexe/2026-10-21/dsh__x.jsonl',
                     'logs/YYBIRDexe/2026-10-21/transcript.raw.jsonl',
                     'src/agent.c', 'credentials/id_ed25519']:
            self.assertFalse(allowed_path(path,'YYBIRDexe'),path)
