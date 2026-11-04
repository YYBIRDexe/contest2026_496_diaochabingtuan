/* Narrow, fail-closed routing for recognizable task requests. */
#ifndef VELAGUARD_TASK_REPLY_GUARD_H
#define VELAGUARD_TASK_REPLY_GUARD_H
#include <string.h>

/* NULL: ordinary conversation. Empty string: ambiguous or negated request. */
static const char *spine_task_required_tool(const char *text)
{
  int status,stop,submit;
  if (!text) return NULL;
  status = strstr(text,"task_status") != NULL;
  stop = strstr(text,"task_stop") != NULL;
  submit = strstr(text,"task_submit") != NULL;
  if (strstr(text,"任务")) {
    status |= strstr(text,"状态") != NULL || strstr(text,"进度") != NULL ||
              strstr(text,"查询") != NULL || strstr(text,"查看") != NULL;
    stop |= strstr(text,"停止") != NULL || strstr(text,"停下") != NULL;
    submit |= strstr(text,"提交") != NULL || strstr(text,"派发") != NULL ||
              strstr(text,"派单") != NULL;
  }
  if (!status && !stop && !submit) return NULL;
  if ((status+stop+submit)!=1 || strstr(text,"不要") || strstr(text,"不调用") ||
      strstr(text,"禁止") || strstr(text,"不必")) return "";
  return status ? "task_status" : stop ? "task_stop" : "task_submit";
}
#endif
