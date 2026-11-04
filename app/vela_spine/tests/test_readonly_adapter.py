import ctypes,json,os,unittest
LIB=os.environ.get('SPINE_ADAPTER_LIB')
@unittest.skipUnless(LIB,'set SPINE_ADAPTER_LIB')
class ReadonlyAdapter(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.lib=ctypes.CDLL(LIB);cls.lib.sp_parse_readonly_call.argtypes=[ctypes.c_char_p];cls.lib.sp_parse_readonly_call.restype=ctypes.c_void_p
  cls.free=ctypes.CDLL(None).free;cls.free.argtypes=[ctypes.c_void_p]
 def parse(self,text):
  ptr=self.lib.sp_parse_readonly_call(text.encode())
  if not ptr:return None
  try:return json.loads(ctypes.string_at(ptr))
  finally:self.free(ptr)
 def xml(self,obj):return '<tool_call>'+json.dumps(obj)+'</tool_call>'
 def dsml(self,path='/data/ai_agent/sp/state.json'):
  return '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="read_file">\n<｜｜DSML｜｜ parameter name="path" string="true">'+path+'</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>'
 def test_observed_formats(self):
  e=dict(name='read_file',arguments=dict(path='/data/ai_agent/sp/state.json'))
  for text in [self.xml(e),"I'll read the file now.\n"+self.xml(e),self.dsml()]:
   self.assertEqual(self.parse(text),e['arguments'])
 def test_paths_and_other_tools_never_adapted(self):
  for path in ['/data/ai_agent/config/config.json','/data/ai_agent/sp/../config/config.json','/etc/passwd','/data/ai_agent/sp/state.json\x00evil']:
   self.assertIsNone(self.parse(self.xml(dict(name='read_file',arguments=dict(path=path)))))
   self.assertIsNone(self.parse(self.dsml(path)))
  for tool in ['write_file','run_shell','delete_file']:
   self.assertIsNone(self.parse(self.xml(dict(name=tool,arguments=dict(path='/data/ai_agent/sp/state.json')))))
   self.assertIsNone(self.parse(self.dsml().replace('name="read_file"',f'name="{tool}"')))
 def test_malformed_or_ambiguous_is_not_executable(self):
  good=self.xml(dict(name='read_file',arguments=dict(path='/data/ai_agent/sp/state.json')))
  cases=[good+good,good+' trailing',good[:-1],self.dsml()+self.dsml(),self.dsml().replace('string="true"','string="false"'),
   '<tool_call>{"name":"read_file","name":"read_file","arguments":{"path":"/data/ai_agent/sp/state.json"}}</tool_call>',
   '<tool_call>{"name":"read_file","arguments":{"path":"/data/ai_agent/sp/state.json","path":"/etc/passwd"}}</tool_call>',
   self.xml(dict(name='read_file',arguments=dict(path='/data/ai_agent/sp/state.json',extra=1))),
   '<tool_call>'+('['*100)+'0'+(']'*100)+'</tool_call>', 'x'*8193]
  for text in cases:self.assertIsNone(self.parse(text),text[:90])

 def test_native_state_is_reserved_for_file_writes(self):
  fn=self.lib.sp_agent_path_reserved;fn.argtypes=[ctypes.c_char_p];fn.restype=ctypes.c_int
  for path in ['/data/ai_agent/sp','/data/ai_agent/sp/state.json','/data//ai_agent/./sp/state.tmp','/data/ai_agent/sp/endpoint.txt']:
   self.assertEqual(fn(path.encode()),1,path)
  for path in ['/data/ai_agent/spare/a','/data/ai_agent/memory/a.md','/tmp/a']:
   self.assertEqual(fn(path.encode()),0,path)
