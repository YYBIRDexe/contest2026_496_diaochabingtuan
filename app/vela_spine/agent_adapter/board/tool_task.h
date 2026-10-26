/*
 * Copyright (C) 2026 VelaGuard team
 * SPDX-License-Identifier: Apache-2.0
 *
 * Three narrow business tools for the official ai_agent:
 *   task_status / task_submit / task_stop
 *
 * The tool never accepts a shell command, a file path, a wheel speed or an
 * arbitrary URL: every argument is validated by the board task ledger
 * (vela_spine native/task.c) and the result is the ledger's own execution
 * reply. Registration lives in tool_registry.c under
 * CONFIG_EXAMPLES_VELA_SPINE.
 */

#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int tool_task_status_execute(const char *input_json, char *output,
                             size_t output_size);
int tool_task_submit_execute(const char *input_json, char *output,
                             size_t output_size);
int tool_task_stop_execute(const char *input_json, char *output,
                           size_t output_size);

#ifdef __cplusplus
}
#endif
