"""Exercise the actual C preflight with a recording official-registry callback."""
import ctypes as C
import json
import os
import unittest
import zlib

LIB = os.environ.get('SPINE_ADAPTER_LIB')

@unittest.skipUnless(LIB, 'set SPINE_ADAPTER_LIB')
class QueryContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = C.CDLL(LIB)
        cls.callback_type = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_char_p, C.c_void_p, C.c_size_t)
        cls.lib.sp_query_context.argtypes = [C.c_char_p, cls.callback_type]
        cls.lib.sp_query_context.restype = C.c_void_p
        cls.lib.sp_query_matches.argtypes = [C.c_char_p]
        cls.free = C.CDLL(None).free
        cls.free.argtypes = [C.c_void_p]

    def snapshot(self, revision):
        records = [dict(event=dict(event_id='fresh', revision=revision))]
        raw = json.dumps(records, separators=(',', ':'))
        return json.dumps(dict(schema=1, records=records,
                              crc32=f'{zlib.crc32(raw.encode()):08x}'))

    def invoke(self, state, fail=False):
        calls = []
        def execute(tool, args, out, size):
            path = json.loads(args)['path']
            calls.append((tool.decode(), path))
            if fail:
                return -1
            value = 'Read-only project rules' if '/skills/' in path else state
            data = value.encode()[:size-1] + b'\0'
            C.memmove(out, data, len(data))
            return 0
        callback = self.callback_type(execute)
        ptr = self.lib.sp_query_context('查询巡检状态'.encode(), callback)
        if not ptr:
            return None, calls
        try:
            return C.string_at(ptr).decode(), calls
        finally:
            self.free(ptr)

    def test_refreshes_each_time_and_only_fixed_read_calls(self):
        for revision in (1, 2):
            text, calls = self.invoke(self.snapshot(revision))
            self.assertIn(f'"revision": {revision}', text)
            self.assertEqual(calls, [
                ('read_file', '/data/ai_agent/skills/spine-status.md'),
                ('read_file', '/data/ai_agent/sp/state.json')])

    def test_missing_corrupt_or_truncated_never_supplies_context(self):
        for state in ['not JSON', self.snapshot(1).replace('"schema": 1', '"schema": 9'),
                      self.snapshot(1).replace('"revision": 1', '"revision": 2'),
                      '{"schema":1,"records":[]}', 'x'*32768]:
            self.assertIsNone(self.invoke(state)[0])
        self.assertIsNone(self.invoke(self.snapshot(1), fail=True)[0])

    def test_scope_does_not_capture_general_queries(self):
        for text in ['/spine', '查询巡检告警', '脊椎状态', '解释巡检分数']:
            self.assertEqual(self.lib.sp_query_matches(text.encode()), 1)
        for text in ['你好', '查询天气', '播放音乐', '配置巡检任务']:
            self.assertEqual(self.lib.sp_query_matches(text.encode()), 0)
