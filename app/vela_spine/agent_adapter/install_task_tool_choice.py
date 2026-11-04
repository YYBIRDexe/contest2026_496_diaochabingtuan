"""Bind native task choice into the actual SDK request builder; keep a backup."""
import argparse
from pathlib import Path
import shutil

MARK = 'VELAGUARD_NATIVE_TASK_CHOICE'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ai-agent', type=Path, required=True)
args = parser.parse_args()
source = args.ai_agent/'src/llm/llm_proxy.c'
text = source.read_text()
include = '#ifdef CONFIG_EXAMPLES_VELA_SPINE\n#include "task_tool_choice.h"\n#endif\n'
anchor = '    /* Convert tools to OpenAI format */'
old = '''    if (tools_arr) {
        cJSON_AddItemToObject(body, "tools", tools_arr);
    }

    char* post_data = cJSON_PrintUnformatted(body);'''
new = old.replace('    char* post_data', '''#ifdef CONFIG_EXAMPLES_VELA_SPINE
    /* VELAGUARD_NATIVE_TASK_CHOICE: fail closed; never rewrite tool arguments. */
    if (spine_task_add_tool_choice(body, msgs) != 0) {
        cJSON_Delete(body);
        return ERROR;
    }
#endif

    char* post_data''')
if MARK not in text:
    if text.count(anchor) != 1 or text.count(old) != 1:
        raise RuntimeError('unexpected SDK request builder; no changes made')
    backup = source.with_suffix('.c.pre-native-task-choice')
    if backup.exists():
        raise RuntimeError('existing SDK backup; inspect before applying')
    shutil.copy2(source, backup)
    config_anchor = '#include "agent_config.h"\n'
    if text.count(config_anchor) != 1:
        raise RuntimeError('missing SDK configuration include')
    text = text.replace(config_anchor, config_anchor + include, 1).replace(old, new, 1)
    source.write_text(text)
else:
    if new not in text or include not in text:
        raise RuntimeError('incomplete native task choice integration')
board = Path(__file__).with_name('board')
for name in ('task_tool_choice.h', 'task_reply_guard.h'):
    shutil.copy2(board/name, args.ai_agent/'src/llm'/name)
print('Native task choice installed; ordinary chat and execution guards preserved.')

# SDK cleanup frees the cached JSON but used to leave its dirty flag false.
# A later ai_agent start then offered no tools. Rebuild on every lifecycle init.
registry = args.ai_agent/'src/tools/tool_registry.c'
registry_text = registry.read_text()
registry_marker = 'VELAGUARD_TASK_REGISTRY_RESTART'
if registry_marker not in registry_text:
    init = 'int tool_registry_init(void)\n{\n    s_tool_count = 0;'
    cleanup = '    s_tools_json = NULL;\n    s_tool_count = 0;'
    if registry_text.count(init) != 1 or registry_text.count(cleanup) != 1:
        raise RuntimeError('unexpected registry lifecycle; inspect before applying')
    registry_backup = registry.with_suffix('.c.pre-native-task-choice')
    if registry_backup.exists():
        raise RuntimeError('existing registry backup; inspect before applying')
    shutil.copy2(registry, registry_backup)
    registry_text = registry_text.replace(init, init + '\n    /* ' + registry_marker + ' */\n    s_tools_dirty = true;', 1)
    registry_text = registry_text.replace(cleanup, cleanup + '\n    s_tools_dirty = true;', 1)
    registry.write_text(registry_text)
else:
    if '    s_tools_dirty = true;' not in registry_text:
        raise RuntimeError('incomplete registry lifecycle fix')
print('Tool JSON cache invalidated on initialization and cleanup.')
