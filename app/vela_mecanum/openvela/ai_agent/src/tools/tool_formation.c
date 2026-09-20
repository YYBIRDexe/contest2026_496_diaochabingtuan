/*
 * Copyright (C) 2026 Xiaomi Corporation
 * SPDX-License-Identifier: Apache-2.0
 */

#include "tools/tool_formation.h"

#include "agent_compat.h"
#include "infra/vela_tls.h"

#include "cJSON.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>

static const char *TAG = "tool_formation";

static bool action_allowed(const char *action)
{
    return strcmp(action, "start") == 0 || strcmp(action, "status") == 0 ||
           strcmp(action, "stop") == 0 || strcmp(action, "reset") == 0 ||
           strcmp(action, "capabilities") == 0;
}

static bool formation_allowed(const char *formation)
{
    return strcmp(formation, "square") == 0 ||
           strcmp(formation, "line") == 0 ||
           strcmp(formation, "circle") == 0 ||
           strcmp(formation, "diamond") == 0;
}

static bool control_mode_allowed(const char *control_mode)
{
    return strcmp(control_mode, "anchored") == 0 ||
           strcmp(control_mode, "laplacian") == 0 ||
           strcmp(control_mode, "second_order") == 0;
}

static int fail(char *output, size_t output_size, const char *code,
                const char *message)
{
    snprintf(output, output_size,
             "{\"ok\":false,\"error\":{\"code\":\"%s\",\"message\":\"%s\"}}",
             code, message);
    return ERROR;
}

int tool_formation_execute(const char *input_json, char *output,
                           size_t output_size)
{
    if (!input_json || !output || output_size == 0) {
        return ERROR;
    }

    cJSON *input = cJSON_Parse(input_json);
    if (!input || !cJSON_IsObject(input)) {
        cJSON_Delete(input);
        return fail(output, output_size, "invalid_json", "input must be a JSON object");
    }

    cJSON *action_item = cJSON_GetObjectItemCaseSensitive(input, "action");
    if (!cJSON_IsString(action_item) || !action_item->valuestring ||
        !action_allowed(action_item->valuestring)) {
        cJSON_Delete(input);
        return fail(output, output_size, "invalid_action",
                    "action must be start, status, stop, reset, or capabilities");
    }

    char action[20];
    snprintf(action, sizeof(action), "%s", action_item->valuestring);

    if (strcmp(action_item->valuestring, "start") == 0) {
        cJSON *formation = cJSON_GetObjectItemCaseSensitive(input, "formation");
        cJSON *control_mode = cJSON_GetObjectItemCaseSensitive(input, "control_mode");
        cJSON *spacing = cJSON_GetObjectItemCaseSensitive(input, "spacing_m");
        cJSON *duration = cJSON_GetObjectItemCaseSensitive(input, "duration_s");
        if (formation && (!cJSON_IsString(formation) ||
                          !formation_allowed(formation->valuestring))) {
            cJSON_Delete(input);
            return fail(output, output_size, "invalid_formation",
                        "formation must be square, line, circle, or diamond");
        }
        if (control_mode && (!cJSON_IsString(control_mode) ||
                            !control_mode_allowed(control_mode->valuestring))) {
            cJSON_Delete(input);
            return fail(output, output_size, "invalid_control_mode",
                        "control_mode must be anchored, laplacian, or second_order");
        }
        if (spacing && (!cJSON_IsNumber(spacing) || spacing->valuedouble < 0.35 ||
                        spacing->valuedouble > 2.5)) {
            cJSON_Delete(input);
            return fail(output, output_size, "unsafe_spacing",
                        "spacing_m must be between 0.35 and 2.5");
        }
        if (duration && (!cJSON_IsNumber(duration) || duration->valuedouble < 1 ||
                         duration->valuedouble > 300)) {
            cJSON_Delete(input);
            return fail(output, output_size, "unsafe_duration",
                        "duration_s must be between 1 and 300");
        }
    }

    char *body = cJSON_PrintUnformatted(input);
    cJSON_Delete(input);
    if (!body) {
        return fail(output, output_size, "out_of_memory",
                    "failed to serialize formation request");
    }

    syslog(LOG_INFO, "[%s] POST http://%s:%s%s action=%s\n", TAG,
           CONFIG_AI_AGENT_FORMATION_HOST, CONFIG_AI_AGENT_FORMATION_PORT,
           CONFIG_AI_AGENT_FORMATION_PATH, action);

    int status = vela_http_post_json(
        CONFIG_AI_AGENT_FORMATION_HOST,
        CONFIG_AI_AGENT_FORMATION_PORT,
        CONFIG_AI_AGENT_FORMATION_PATH,
        NULL, body, output, output_size);
    free(body);

    if (status >= 200 && status < 300) {
        if (output[0] == '\0') {
            return fail(output, output_size, "empty_response",
                        "formation service returned no response body");
        }
        return OK;
    }

    if (status < 0) {
        syslog(LOG_ERR, "[%s] connection failed: %d\n", TAG, status);
        return fail(output, output_size, "service_unreachable",
                    "cannot connect to the local formation service");
    }

    syslog(LOG_WARNING, "[%s] service returned HTTP %d: %.160s\n", TAG,
           status, output);
    return ERROR;
}
