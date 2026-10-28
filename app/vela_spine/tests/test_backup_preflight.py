import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from host.backup_preflight import relative_path, verify_backup


class BackupPreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        data = b'{"schema":1,"tasks":[{"state":"DISPATCHING"}]}'
        name = 'ai_agent/sp/tasks.json'
        for copy in ('first', 'check'):
            file = self.base / copy / name
            file.parent.mkdir(parents=True)
            file.write_bytes(data)
        self.manifest = {name: hashlib.sha256(data).hexdigest()}
        self.modes = {'ai_agent': 0o755, 'ai_agent/sp': 0o777, name: 0o600}
        self.write_manifests()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifests(self):
        (self.base / 'manifest.json').write_text(json.dumps(self.manifest))
        (self.base / 'modes.json').write_text(json.dumps(self.modes))

    def test_verified_copies_report_limits_without_restoring(self):
        result = verify_backup(self.base, {'DISPATCHING'})
        self.assertTrue(result['backup_content_verified'])
        self.assertEqual(result['live_task_states'], {'DISPATCHING': 1})
        self.assertFalse(result['restore_performed'])
        self.assertFalse(result['target_firmware_verified'])

    def test_old_target_state_list_rejects_new_ledger(self):
        with self.assertRaises(ValueError):
            verify_backup(self.base, {'PENDING', 'DISPATCHED'})

    def test_mismatch_and_missing_copy_are_rejected(self):
        file = self.base / 'check/ai_agent/sp/tasks.json'
        file.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            verify_backup(self.base, {'DISPATCHING'})
        file.unlink()
        with self.assertRaises(ValueError):
            verify_backup(self.base, {'DISPATCHING'})

    def test_path_traversal_and_normalization_rejected(self):
        for name in ('../private', '/absolute', 'a/../b', 'a//b', '.', 'C:/secret', 'a\\b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_path(name)

    def test_unmanifested_file_is_rejected(self):
        (self.base / 'first/private-key').write_bytes(b'fixture')
        with self.assertRaises(ValueError):
            verify_backup(self.base, {'DISPATCHING'})

    def test_bad_permission_record_and_duplicate_manifest_rejected(self):
        self.modes['ai_agent'] = True
        self.write_manifests()
        with self.assertRaises(ValueError):
            verify_backup(self.base, {'DISPATCHING'})
        (self.base / 'manifest.json').write_text('{"a":"x","a":"y"}')
        with self.assertRaises(ValueError):
            verify_backup(self.base, {'DISPATCHING'})


if __name__ == '__main__':
    unittest.main()
