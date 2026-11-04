#include "task_tool_choice.h"
#include <assert.h>
#include <stdio.h>

static void check(const char *message, const char *role, const char *tools,
                  int expected_rc, const char *expected_name)
{
  cJSON *body = cJSON_CreateObject(), *messages = cJSON_CreateArray();
  cJSON *user = cJSON_CreateObject(), *choice, *name;
  char *before, *after;
  cJSON_AddItemToObject(body, "tools", cJSON_Parse(tools));
  cJSON_AddStringToObject(user, "role", role);
  cJSON_AddStringToObject(user, "content", message);
  cJSON_AddItemToArray(messages, user);
  before = cJSON_PrintUnformatted(messages);
  assert(spine_task_add_tool_choice(body, messages) == expected_rc);
  after = cJSON_PrintUnformatted(messages);
  assert(!strcmp(before, after)); /* No user values or history rewritten. */
  choice = cJSON_GetObjectItemCaseSensitive(body, "tool_choice");
  if (expected_name) {
    assert(cJSON_IsObject(choice));
    name = cJSON_GetObjectItemCaseSensitive(
        cJSON_GetObjectItemCaseSensitive(choice, "function"), "name");
    assert(cJSON_IsString(name) && !strcmp(name->valuestring, expected_name));
    assert(cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(body,"tools")) == 3);
  } else assert(!choice);
  cJSON_free(before); cJSON_free(after);
  cJSON_Delete(body); cJSON_Delete(messages);
}
int main(void)
{
  const char *tools = "[{\"type\":\"function\",\"function\":{\"name\":\"task_status\"}},"
      "{\"type\":\"function\",\"function\":{\"name\":\"task_submit\"}},"
      "{\"type\":\"function\",\"function\":{\"name\":\"task_stop\"}}]";
  check("请调用task_stop停止sim-T2", "user", tools, 0, "task_stop");
  check("task_submit {\"schema\":\"spine-plan-v1\",\"tasks\":[]}",
        "user", tools, 0, "task_submit");
  check("查询任务状态", "user", tools, 0, "task_status");
  check("今天天气怎么样", "user", tools, 0, NULL);
  check("task_stop", "tool", tools, 0, NULL);
  check("不要调用task_stop", "user", tools, -1, NULL);
  check("task_stop task_submit", "user", tools, -1, NULL);
  check("task_stop", "user", "[]", -1, NULL);
  check("task_stop", "user",
        "[{\"type\":\"function\",\"function\":{\"name\":\"task_stop\"}},"
        "{\"type\":\"function\",\"function\":{\"name\":\"task_stop\"}}]", -1, NULL);
  puts("native task choice: 9 request boundary cases PASS");
  return 0;
}
