/*
 * Copyright (C) 2026 VelaGuard team
 * SPDX-License-Identifier: Apache-2.0
 *
 * Board side executors for the three narrow spine business tools.
 *
 * The official ai_agent calls these through REGISTER_TOOL(); each one hands
 * the structured arguments straight to the vela_spine task ledger, which owns
 * field/version/ownership/risk validation and the durable task file. No shell
 * command, no file path, no wheel speed and no arbitrary URL can be expressed
 * here: the executor only forwards the tool name and the JSON object.
 */

#include "tools/tool_task.h"

#include "cJSON.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef SPINE_TASK_ROOT
#  define SPINE_TASK_ROOT "/data/ai_agent/sp"
#endif
#ifndef SPINE_TASK_ENDPOINT_FILE
#  define SPINE_TASK_ENDPOINT_FILE SPINE_TASK_ROOT "/task-end.txt"
#endif
#ifndef ERROR
#  define ERROR -1
#endif
#ifndef OK
#  define OK 0
#endif

#define SPINE_TOOL_INPUT_MAX 4096
#define SPINE_ENDPOINT_MAX 64

#if defined(__NuttX__)
#  include <syslog.h>
#  define SPINE_LOG(fmt, ...) syslog(LOG_INFO, "[spine-tool] " fmt, ##__VA_ARGS__)
#else
/* Host builds compile this file for unit tests; keep the arguments used so
 * -Werror=unused-but-set-variable stays meaningful, but emit nothing.
 */

#  define SPINE_LOG(fmt, ...) do { if (0) { printf(fmt, ##__VA_ARGS__); } } while (0)
#endif

/* Implemented by the vela_spine application in the same firmware image
 * (flat build), exactly like the verified read-only bridge.
 */

extern int sp_task_tool_call(const char *root, const char *endpoint,
                             const char *name, const char *args_json,
                             char **reply);

static const char *g_spine_tool_tag = "task_tool";

static int tool_fail(char *output, size_t output_size, const char *code,
                     const char *message)
{
  snprintf(output, output_size,
           "{\"tool\":\"%s\",\"ok\":false,\"motion\":false,\"error\":"
           "{\"code\":\"%s\",\"message\":\"%s\"}}",
           g_spine_tool_tag, code, message);
  return ERROR;
}

static int read_endpoint(char *buffer, size_t size)
{
  FILE *file = NULL;
  size_t length;

  buffer[0] = '\0';
  file = fopen(SPINE_TASK_ENDPOINT_FILE, "rb");
  if (file == NULL)
    {
      return ERROR;
    }

  if (fgets(buffer, (int)size, file) == NULL)
    {
      fclose(file);
      buffer[0] = '\0';
      return ERROR;
    }

  fclose(file);
  length = strlen(buffer);
  while (length > 0 && (buffer[length - 1] == '\n' || buffer[length - 1] == '\r'))
    {
      buffer[--length] = '\0';
    }

  if (length == 0 || length >= SPINE_ENDPOINT_MAX)
    {
      buffer[0] = '\0';
      return ERROR;
    }

  return OK;
}

static int run_tool(const char *name, const char *input_json, char *output,
                    size_t output_size)
{
  char endpoint[SPINE_ENDPOINT_MAX + 1];
  char *reply = NULL;
  int result;

  if (output == NULL || output_size == 0)
    {
      return ERROR;
    }

  output[0] = '\0';
  if (name == NULL || input_json == NULL)
    {
      return tool_fail(output, output_size, "bad_request",
                       "missing tool name or arguments");
    }

  if (strlen(input_json) > SPINE_TOOL_INPUT_MAX)
    {
      return tool_fail(output, output_size, "tool_input_too_large",
                       "arguments must stay below 4096 bytes");
    }

  if (read_endpoint(endpoint, sizeof(endpoint)) != OK)
    {
      endpoint[0] = '\0';
    }

  result = sp_task_tool_call(SPINE_TASK_ROOT,
                             endpoint[0] != '\0' ? endpoint : NULL,
                             name, input_json, &reply);
  if (reply == NULL)
    {
      SPINE_LOG("%s: ledger returned no result rc=%d", name, result);
      return tool_fail(output, output_size, "tool_execution_failed",
                       "task ledger did not answer");
    }

  if (strlen(reply) >= output_size)
    {
      cJSON_free(reply);
      return tool_fail(output, output_size, "tool_output_too_large",
                       "result does not fit the tool output buffer");
    }

  snprintf(output, output_size, "%s", reply);
  cJSON_free(reply);
  SPINE_LOG("%s accepted rc=%d", name, result);
  return OK;
}

int tool_task_status_execute(const char *input_json, char *output,
                             size_t output_size)
{
  return run_tool("task_status", input_json, output, output_size);
}

int tool_task_submit_execute(const char *input_json, char *output,
                             size_t output_size)
{
  return run_tool("task_submit", input_json, output, output_size);
}

int tool_task_stop_execute(const char *input_json, char *output,
                           size_t output_size)
{
  return run_tool("task_stop", input_json, output, output_size);
}
