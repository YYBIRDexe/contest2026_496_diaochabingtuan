"""Register task tools in the actual NuttX Makefile-based ai_agent tree."""
import argparse
import json
import shutil
from pathlib import Path

MARKER='VELAGUARD_SPINE_TASK_TOOLS'
ANCHOR='    build_tools_json_locked();\n    syslog(LOG_INFO, "[%s] Tool registry initialized\\n", TAG);'
MAKE_ANCHOR='CSRCS += src/tools/tool_registry.c\n'

def registration():
    identifier={'type':'string','minLength':1,'maxLength':64}
    task={'type':'object','properties':{'task_id':{'type':'string','minLength':1,'maxLength':55},'tag_id':identifier,
           'robot_id':{'type':'string','enum':['S1','S2','S3','AUTO']},
           'revision':{'type':'integer','minimum':1},'priority':{'type':'integer','minimum':1,'maximum':1000}},
          'required':['task_id','tag_id','robot_id','revision'],'additionalProperties':False}
    specs=[('task_status','Read the current board task ledger.',
            {'type':'object','properties':{'task_id':identifier},'additionalProperties':False}),
           ('task_submit','Submit a versioned simulation plan; persistence is not execution.',
            {'type':'object','properties':{'schema':{'type':'string','enum':['spine-plan-v1']},
             'plan_id':identifier,'version':{'type':'integer','minimum':1},
             'tasks':{'type':'array','minItems':1,'maxItems':3,'items':task}},
             'required':['schema','plan_id','version','tasks'],'additionalProperties':False}),
           ('task_stop','Request task stop; wait for STOP_CONFIRMED before treating it as stopped.',
            {'type':'object','properties':{'task_id':identifier},'required':['task_id'],'additionalProperties':False})]
    lines=['#ifdef CONFIG_EXAMPLES_VELA_SPINE','    /* '+MARKER+' */']
    for name,description,schema in specs:
        lines.append('    extern int tool_%s_execute(const char *, char *, size_t);'%name)
        lines.append('    REGISTER_TOOL(%s, %s, %s, tool_%s_execute);' % (
            json.dumps(name),json.dumps(description),json.dumps(json.dumps(schema,separators=(',',':'))),name))
    lines.append('#endif')
    return '\n'.join(lines)+'\n'

def main():
 p=argparse.ArgumentParser();p.add_argument('--ai-agent',required=True);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
 root=Path(a.ai_agent).resolve();here=Path(__file__).resolve().parent
 registry=root/'src/tools/tool_registry.c';make=root/'Makefile';tools=root/'src/tools'
 original=registry.read_text();build=make.read_text()
 if MARKER not in original:
  if original.count(ANCHOR)!=1:raise ValueError('unexpected actual registry')
  patched=original.replace(ANCHOR,registration()+'\n'+ANCHOR,1)
 else:
  if any(name not in original for name in ('tool_task_status_execute','tool_task_submit_execute','tool_task_stop_execute')):
   raise ValueError('incomplete registry')
  start=original.rfind('#ifdef CONFIG_EXAMPLES_VELA_SPINE\n',0,original.index(MARKER))
  end=original.find('#endif\n',original.index(MARKER))
  if start<0 or end<0 or original.count(MARKER)!=1:raise ValueError('unexpected task registry block')
  patched=original[:start]+registration()+original[end+len('#endif\n'):]
 if MARKER not in build:
  if build.count(MAKE_ANCHOR)!=1:raise ValueError('unexpected NuttX Makefile')
  patched_make=build.replace(MAKE_ANCHOR,MAKE_ANCHOR+'# '+MARKER+'\nifeq ($(CONFIG_EXAMPLES_VELA_SPINE),y)\nCSRCS += src/tools/tool_task.c\nendif\n',1)
 else:
  if 'CSRCS += src/tools/tool_task.c' not in build:raise ValueError('incomplete Makefile')
  patched_make=build
 changes=[]
 for target,content in [(registry,patched.encode()),(make,patched_make.encode()),
                         (tools/'tool_task.c',(here/'board/tool_task.c').read_bytes()),
                         (tools/'tool_task.h',(here/'board/tool_task.h').read_bytes())]:
  if not target.exists() or target.read_bytes()!=content:
   changes.append(target.name)
   if not a.dry_run:
    if target.exists():
     backup=target.with_name(target.name+'.before-spine-task-20261027')
     if not backup.exists():shutil.copy2(target,backup)
    target.write_bytes(content)
 print(('DRY_RUN' if a.dry_run else 'PATCHED' if changes else 'UNCHANGED'),','.join(changes))
if __name__=='__main__':main()
