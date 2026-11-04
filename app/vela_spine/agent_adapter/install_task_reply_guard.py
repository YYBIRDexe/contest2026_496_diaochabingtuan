"""Install a fail-closed task reply guard into the NuttX ai_agent loop."""
import argparse
from pathlib import Path
import shutil

MARK='VELAGUARD_TASK_REPLY_GUARD'
def replace_once(text, old, new):
    if text.count(old)!=1:raise ValueError('unexpected upstream anchor: '+old[:80])
    return text.replace(old,new,1)

def patch(text):
    if MARK in text:
        for token in ('spine_task_required_tool(msg->content)',
                      'spine_task_required_tool(msg.content)',
                      'task tool result is unavailable'):
            if token not in text:raise ValueError('incomplete guard')
        return text
    anchor='/* Run the ReAct tool-calling loop. Returns final_text (caller owns). */'
    text=replace_once(text,anchor,'#ifdef CONFIG_EXAMPLES_VELA_SPINE\n/* '+MARK+' */\n#include "task_reply_guard.h"\n#endif\n\n'+anchor)
    anchor='    int last_total_tokens = 0;\n    bool watchdog_fired = false;'
    text=replace_once(text,anchor,anchor+'''
#ifdef CONFIG_EXAMPLES_VELA_SPINE
    const char *spine_required = spine_task_required_tool(msg->content);
#else
    const char *spine_required = NULL;
#endif
    if (spine_required && !*spine_required) {
        return strdup("任务请求含多个操作或否定，无法安全确认；请明确指定一个操作。");
    }
''')
    text=replace_once(text,'    if (msg->content && complexity == LLM_COMPLEXITY_SIMPLE) {',
                      '    if (!spine_required && msg->content && complexity == LLM_COMPLEXITY_SIMPLE) {')
    anchor='        if (!resp.tool_use) {\n            /* Cascade routing:'
    text=replace_once(text,anchor,'''        if (!resp.tool_use && spine_required) {
            llm_response_free(&resp);
            final_text = strdup("本轮未执行指定任务工具，无法确认结果。");
            break;
        }
        if (!resp.tool_use) {
            /* Cascade routing:''')
    anchor='        /* Duplicate detection — break if stuck in a loop */'
    text=replace_once(text,anchor,'''        /* Fail closed before executing a different or parallel tool. */
        if (spine_required && (resp.call_count != 1 ||
            strcmp(resp.calls[0].name, spine_required) != 0)) {
            llm_response_free(&resp);
            final_text = strdup("任务工具调用不匹配，未执行，无法确认结果。");
            break;
        }

'''+anchor)
    anchor='''        add_tool_result_messages(messages, &resp, tool_output,
            tool_size, msg->channel, msg->chat_id);

        /* Local tool shortcut:'''
    text=replace_once(text,anchor,'''        add_tool_result_messages(messages, &resp, tool_output,
            tool_size, msg->channel, msg->chat_id);

        if (spine_required) {
            cJSON *result_doc = cJSON_ParseWithOpts(tool_output, NULL, 1);
            cJSON *result_name = result_doc ? cJSON_GetObjectItemCaseSensitive(result_doc, "tool") : NULL;
            cJSON *result_ok = result_doc ? cJSON_GetObjectItemCaseSensitive(result_doc, "ok") : NULL;
            cJSON *result_body = result_doc ? cJSON_GetObjectItemCaseSensitive(result_doc, "result") : NULL;
            if (cJSON_IsObject(result_doc) && cJSON_IsString(result_name) &&
                strcmp(result_name->valuestring, spine_required) == 0 &&
                cJSON_IsBool(result_ok) && result_body) {
                final_text = strdup(tool_output);
            } else {
                final_text = strdup("task tool result is unavailable; 无法确认结果。");
            }
            cJSON_Delete(result_doc);
            llm_response_free(&resp);
            break;
        }

        /* Local tool shortcut:''')
    text=replace_once(text,'    if (final_text && msg->content\n        && complexity == LLM_COMPLEXITY_SIMPLE) {',
                      '    if (!spine_required && final_text && msg->content\n        && complexity == LLM_COMPLEXITY_SIMPLE) {')
    text=replace_once(text,'        spine_query = sp_query_matches(msg.content);',
                      '        spine_query = sp_query_matches(msg.content) && !spine_task_required_tool(msg.content);')
    return text

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--ai-agent',required=True);parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();root=Path(args.ai_agent).resolve();source=root/'src/core/agent_loop.c'
    header=source.with_name('task_reply_guard.h');body=source.read_text(encoding='utf-8');updated=patch(body)
    content=(Path(__file__).resolve().parent/'board/task_reply_guard.h').read_bytes()
    changed=updated!=body or not header.exists() or header.read_bytes()!=content
    if changed and not args.dry_run:
        backup=source.with_name(source.name+'.before-task-reply-guard-20261028')
        if not backup.exists():shutil.copy2(source,backup)
        source.write_text(updated,encoding='utf-8');header.write_bytes(content)
    print(('DRY_RUN' if args.dry_run else 'PATCHED' if changed else 'UNCHANGED'))
if __name__=='__main__':main()
