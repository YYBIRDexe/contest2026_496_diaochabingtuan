"""Exercise the task-request classifier that gates actual Agent replies."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HEADER=Path(__file__).resolve().parents[1]/'agent_adapter/board/task_reply_guard.h'

@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class TaskReplyGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        source=Path(cls.temp.name)/'guard.c';lib=Path(cls.temp.name)/'guard.so'
        source.write_text('#include "task_reply_guard.h"\nconst char *classify(const char *s){return spine_task_required_tool(s);}\n')
        subprocess.run(['cc','-std=c11','-Wall','-Werror','-shared','-fPIC','-I',str(HEADER.parent),str(source),'-o',str(lib)],check=True)
        cls.lib=ctypes.CDLL(str(lib));cls.lib.classify.argtypes=[ctypes.c_char_p];cls.lib.classify.restype=ctypes.c_char_p
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def classify(self,text):
        value=self.lib.classify(text.encode())
        return value.decode() if value is not None else None
    def test_explicit_and_chinese_requests(self):
        self.assertEqual(self.classify('请用task_status查询sim-T3的状态'),'task_status')
        self.assertEqual(self.classify('查询巡检任务状态'),'task_status')
        self.assertEqual(self.classify('停止任务T3'),'task_stop')
        self.assertEqual(self.classify('提交任务计划'),'task_submit')
    def test_ambiguous_and_negated_requests_fail_closed(self):
        self.assertEqual(self.classify('查询任务状态并停止任务'),'')
        self.assertEqual(self.classify('不要调用task_stop'),'')
    def test_ordinary_chat_is_unaffected(self):
        self.assertIsNone(self.classify('今天天气怎么样'))
        self.assertIsNone(self.classify('查询巡检异常状态'))

if __name__=='__main__':unittest.main()
