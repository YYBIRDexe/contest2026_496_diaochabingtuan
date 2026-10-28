/* Bind a recognized task request to a native function call, not text parsing.
 * The reply guard and ledger still validate every returned call and argument.
 */
#ifndef VELAGUARD_TASK_TOOL_CHOICE_H
#define VELAGUARD_TASK_TOOL_CHOICE_H
#include "cJSON.h"
#include "task_reply_guard.h"

static int spine_task_add_tool_choice(cJSON *body, const cJSON *messages)
{
  const cJSON *last, *role, *content, *tools, *tool;
  const char *required;
  cJSON *choice, *function;
  int matches = 0;
  if (!cJSON_IsObject(body) || !cJSON_IsArray(messages)) return -1;
  last = cJSON_GetArrayItem(messages, cJSON_GetArraySize(messages) - 1);
  role = cJSON_GetObjectItemCaseSensitive(last, "role");
  content = cJSON_GetObjectItemCaseSensitive(last, "content");
  if (!cJSON_IsString(role) || strcmp(role->valuestring, "user") ||
      !cJSON_IsString(content)) return 0;
  required = spine_task_required_tool(content->valuestring);
  if (!required) return 0;
  if (!*required) return -1;
  tools = cJSON_GetObjectItemCaseSensitive(body, "tools");
  if (!cJSON_IsArray(tools)) return -1;
  cJSON_ArrayForEach(tool, tools) {
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(tool, "type");
    const cJSON *fn = cJSON_GetObjectItemCaseSensitive(tool, "function");
    const cJSON *name = cJSON_GetObjectItemCaseSensitive(fn, "name");
    if (cJSON_IsString(type) && !strcmp(type->valuestring, "function") &&
        cJSON_IsString(name) && !strcmp(name->valuestring, required)) matches++;
  }
  if (matches != 1 || cJSON_GetObjectItemCaseSensitive(body, "tool_choice"))
    return -1;
  choice = cJSON_CreateObject();
  function = cJSON_CreateObject();
  if (!choice || !function ||
      !cJSON_AddStringToObject(choice, "type", "function") ||
      !cJSON_AddStringToObject(function, "name", required)) {
    cJSON_Delete(choice); cJSON_Delete(function); return -1;
  }
  if (!cJSON_AddItemToObject(choice, "function", function)) {
    cJSON_Delete(choice); cJSON_Delete(function); return -1;
  }
  if (!cJSON_AddItemToObject(body, "tool_choice", choice)) {
    cJSON_Delete(choice); return -1;
  }
  return 0;
}
#endif
