import ctypes as C
import os
import unittest

@unittest.skipUnless(os.environ.get('SPINE_ADAPTER_LIB'), 'set SPINE_ADAPTER_LIB')
class SummaryBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib=C.CDLL(os.environ['SPINE_ADAPTER_LIB'])
        cls.lib.sp_utf8_prefix.argtypes=[C.c_char_p,C.c_size_t]
        cls.lib.sp_utf8_prefix.restype=C.c_size_t
        cls.lib.sp_skill_summary_append.argtypes=[C.c_void_p,C.c_size_t,C.c_size_t,C.c_char_p,C.c_char_p,C.c_char_p]
        cls.lib.sp_skill_summary_append.restype=C.c_size_t
    def test_every_byte_budget_keeps_complete_unicode(self):
        text='查询状态·中文😀'.encode()
        for budget in range(len(text)+1):
            n=self.lib.sp_utf8_prefix(text,budget)
            self.assertLessEqual(n,budget)
            text[:n].decode('utf-8')
        for invalid in [b'\xc0\x80',b'\xed\xa0\x80',b'\xf4\x90\x80\x80',b'\x80']:
            self.assertEqual(self.lib.sp_utf8_prefix(invalid,len(invalid)),0)
    def test_small_summary_preserves_sentinel_and_valid_utf8(self):
        for size in range(1,200):
            buffer=(C.c_ubyte*(size+16))(*([0]*size+[0xa5]*16))
            off=0
            for _ in range(5):
                off=self.lib.sp_skill_summary_append(buffer,size,off,'水利巡检'.encode(),('中文描述'*30).encode()[:255],b'/data/ai_agent/skills/spine-status.md')
                self.assertLess(off,size)
                C.string_at(buffer).decode('utf-8')
                self.assertEqual(bytes(buffer[size:]),b'\xa5'*16)
    def test_long_catalog_stays_within_real_buffer(self):
        buffer=C.create_string_buffer(1024);off=0
        for i in range(20):
            off=self.lib.sp_skill_summary_append(buffer,1024,off,f'技能{i}'.encode(),('回放查询描述'*20).encode(),b'/data/ai_agent/skills/test.md')
        self.assertLess(off,1024)
        self.assertEqual(off,len(buffer.value))
        buffer.value.decode('utf-8')
