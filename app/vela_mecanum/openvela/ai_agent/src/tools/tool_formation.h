/*
 * Copyright (C) 2026 Xiaomi Corporation
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int tool_formation_execute(const char *input_json, char *output,
                           size_t output_size);

#ifdef __cplusplus
}
#endif
