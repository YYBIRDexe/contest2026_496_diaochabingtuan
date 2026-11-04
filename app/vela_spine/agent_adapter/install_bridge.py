from pathlib import Path
import shutil
# Preserve pristine sources before any of the idempotent edits below.
source=Path('/home/ggbird/openvela/packages/ai_agent/src')
for rel in ['llm/llm_parse.c','llm/llm_proxy.c','core/agent_loop.c','tools/tool_files.c','tools/skill_loader.c']:
 original=source/rel
 backup=original.with_name(original.name+'.codex-pre-spine-readonly')
 if not backup.exists():shutil.copy2(original,backup)
base=Path('/home/ggbird/openvela/packages/ai_agent/src/llm')
p=base/'llm_parse.c';s=p.read_text()
marker='/* CODEX_SPINE_READONLY_BRIDGE */'
if marker not in s:
 s+='''
/* CODEX_SPINE_READONLY_BRIDGE */
#ifdef CONFIG_EXAMPLES_VELA_SPINE
extern char *sp_parse_readonly_call(const char *text);
void parse_spine_readonly_tool_call(llm_response_t *resp)
{
    char *args;
    if (!resp || resp->call_count || !resp->text) return;
    args = sp_parse_readonly_call(resp->text);
    if (!args) return;
    snprintf(resp->calls[0].id, sizeof(resp->calls[0].id), "spine_read_0");
    snprintf(resp->calls[0].name, sizeof(resp->calls[0].name), "read_file");
    resp->calls[0].input = args;
    resp->calls[0].input_len = strlen(args);
    resp->call_count = 1;
    resp->tool_use = true;
    free(resp->text);
    resp->text = NULL;
    resp->text_len = 0;
    syslog(LOG_INFO, "[spine] readonly format bridge accepted fixed status view\\n");
}
#endif
'''
 p.write_text(s)
# Bound snprintf's actual output and keep all summary fields valid UTF-8.
p=source/'tools/skill_loader.c';s=p.read_text();marker='/* CODEX_SPINE_UTF8_SUMMARY */'
if marker not in s:
 anchor='size_t skill_loader_build_summary(char *buf, size_t size)\n{'
 assert s.count(anchor)==1
 s=s.replace(anchor,anchor+'\n    if (!buf || !size) return 0;')
 anchor='''        off += snprintf(buf + off, size - off,
            "- **%s**: %s (read with: read_file %s)\\n",
            title, desc, full_path);'''
 assert s.count(anchor)==1
 s=s.replace(anchor,'''        /* CODEX_SPINE_UTF8_SUMMARY */
#ifdef CONFIG_EXAMPLES_VELA_SPINE
        extern size_t sp_skill_summary_append(char *,size_t,size_t,const char *,const char *,const char *);
        off = sp_skill_summary_append(buf, size, off, title, desc, full_path);
#else
        int written = snprintf(buf + off, size - off,
            "- **%s**: %s (read with: read_file %s)\\n", title, desc, full_path);
        if (written < 0) break;
        off += (size_t)written < size - off ? (size_t)written : size - off - 1;
#endif
        if (size - off < 4) break;''')
 p.write_text(s)
# Refresh domain queries before the LLM, without stale conversation history.
p=Path('/home/ggbird/openvela/packages/ai_agent/src/core/agent_loop.c')
s=p.read_text();marker='/* CODEX_SPINE_FRESH_QUERY */'
if marker not in s:
 anchor='        cJSON* messages = build_messages(msg.chat_id, msg.content,\n            history_json, hist_size);'
 assert s.count(anchor)==1
 s=s.replace(anchor,'''        /* CODEX_SPINE_FRESH_QUERY */
        bool spine_query = false;
        cJSON* messages = NULL;
#ifdef CONFIG_EXAMPLES_VELA_SPINE
        extern int sp_query_matches(const char *text);
        extern char *sp_query_context(const char *text,
            int (*execute)(const char *,const char *,char *,size_t));
        spine_query = sp_query_matches(msg.content);
        if (spine_query) {
            char *fresh = sp_query_context(msg.content, tool_registry_execute);
            if (!fresh) {
                dispatch_response(&msg, strdup("无法确认：本轮只读技能或告警快照读取/校验失败。"));
                free(msg.image_b64);
                free(msg.content);
                continue;
            }
            messages = cJSON_CreateArray();
            cJSON *current = cJSON_CreateObject();
            cJSON_AddStringToObject(current, "role", "user");
            cJSON_AddStringToObject(current, "content", fresh);
            cJSON_AddItemToArray(messages, current);
            free(fresh);
            syslog(LOG_INFO, "[spine] fresh readonly query; conversation history omitted\\n");
        }
#endif
        if (!messages) {
            messages = build_messages(msg.chat_id, msg.content,
                history_json, hist_size);
        }''')
 anchor='                tools_json, tool_output, tool_size, &msg);'
 assert s.count(anchor)==1
 s=s.replace(anchor,'                spine_query ? NULL : tools_json, tool_output, tool_size, &msg);')
 p.write_text(s)
 p=base/'llm_proxy.c';s=p.read_text();marker='/* CODEX_SPINE_READONLY_BRIDGE */'
if marker not in s:
 anchor='    parse_ns_xml_tool_calls(resp);'
 assert s.count(anchor)==1
 s=s.replace(anchor,anchor+'''
#ifdef CONFIG_EXAMPLES_VELA_SPINE
    /* CODEX_SPINE_READONLY_BRIDGE */
    extern void parse_spine_readonly_tool_call(llm_response_t *resp);
    parse_spine_readonly_tool_call(resp);
#endif''')
 p.write_text(s)
# Protect the native service directory from generic Agent file writes/edits.
p=Path('/home/ggbird/openvela/packages/ai_agent/src/tools/tool_files.c')
s=p.read_text();marker='/* CODEX_SPINE_RESERVED_FILES */'
if marker not in s:
 import shutil
 if not p.with_name(p.name+'.codex-pre-spine-readonly').exists():
  shutil.copy2(p,p.with_name(p.name+'.codex-pre-spine-readonly'))
 anchor='    for (int i = 0; s_protected_files[i]; i++) {'
 assert s.count(anchor)==1
 s=s.replace(anchor,'''#ifdef CONFIG_EXAMPLES_VELA_SPINE
    /* CODEX_SPINE_RESERVED_FILES */
    extern int sp_agent_path_reserved(const char *path);
    if (sp_agent_path_reserved(path) || sp_agent_path_reserved(check)) return true;
#endif

'''+anchor)
 p.write_text(s)
# The official local-file shortcut must let the LLM interpret the status view.
p=Path('/home/ggbird/openvela/packages/ai_agent/src/core/agent_loop.c')
s=p.read_text();marker='/* CODEX_SPINE_STATUS_CONTEXT */'
if marker not in s:
 import shutil
 if not p.with_name(p.name+'.codex-pre-spine-readonly').exists():
  shutil.copy2(p,p.with_name(p.name+'.codex-pre-spine-readonly'))
 start=s.index('bool is_skill_read = false;')
 pos=s.index('                        cJSON_Delete(input_obj);',start)
 s=s[:pos]+'''#ifdef CONFIG_EXAMPLES_VELA_SPINE
                        /* CODEX_SPINE_STATUS_CONTEXT */
                        if (cJSON_IsString(path_obj) && strcmp(path_obj->valuestring,
                                "/data/ai_agent/sp/state.json") == 0) {
                            is_skill_read = true;
                        }
#endif
'''+s[pos:]
 p.write_text(s)
# Elapsed request durations must not use a wall clock that NTP can adjust.
p=Path('/home/ggbird/openvela/packages/ai_agent/src/core/agent_loop.c')
s=p.read_text();marker='/* CODEX_SPINE_MONOTONIC_DURATION */'
if marker not in s:
 anchor='/* ── Clock-safe elapsed time calculation'
 pos=s.index(anchor)
 s=s[:pos]+'''/* CODEX_SPINE_MONOTONIC_DURATION */
static void agent_measure_time(struct timeval *tv)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) == 0) {
        tv->tv_sec = ts.tv_sec;
        tv->tv_usec = ts.tv_nsec / 1000;
    } else {
        gettimeofday(tv, NULL);
    }
}

'''+s[pos:]
 if '#include <time.h>' not in s:s=s.replace('#include <sys/time.h>','#include <sys/time.h>\n#include <time.h>')
 for var in ['t0','t1','tv_start','tv_end']:
  s=s.replace('gettimeofday(&'+var+', NULL);','agent_measure_time(&'+var+');')
 p.write_text(s)
