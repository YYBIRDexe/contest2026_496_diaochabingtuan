#!/usr/bin/env bash
# Usage: bash build-host-linux.sh /path/to/openvela/apps/netutils/cjson/cJSON
set -euo pipefail
cd -- "$(dirname -- "$0")"
cjson_dir="$(realpath -- "${1:?Pass the official cJSON source directory}")"
test -f "$cjson_dir/cJSON.c"
mkdir -p build
cc="${CC:-gcc}"
flags=(-std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 -I"$cjson_dir")
mbedtls_dir="$(realpath -- "$cjson_dir/../../../crypto/mbedtls/mbedtls")"
flags+=(-I"$mbedtls_dir/include" -I"$PWD/host" '-DMBEDTLS_CONFIG_FILE="spine_mbedtls_config.h"')
sources=(spine_main.c native/spine.c native/ingress.c native/store.c native/transport.c native/watch.c native/human.c native/task.c native/task_watch.c agent_adapter/task_tools.c "$mbedtls_dir/library/md.c" "$mbedtls_dir/library/sha256.c" "$mbedtls_dir/library/platform_util.c")
"$cc" "${flags[@]}" -shared -fPIC native/spine.c -o build/libspine.so
"$cc" "${flags[@]}" "${sources[@]}" "$cjson_dir/cJSON.c" -lm -o build/spine-cli
"$cc" "${flags[@]}" "${sources[@]}" tests/fsync_fault.c "$cjson_dir/cJSON.c" -Wl,--wrap=fsync -lm -o build/spine-cli-fault
"$cc" "${flags[@]}" -shared -fPIC -Wl,--no-undefined agent_adapter/readonly_call.c agent_adapter/query_context.c native/ingress.c native/spine.c "$cjson_dir/cJSON.c" -lm -o build/libspine-adapter.so
"$cc" "${flags[@]}" -Iagent_adapter/board tests/task_tool_choice_test.c "$cjson_dir/cJSON.c" -lm -o build/task-tool-choice-test
build/task-tool-choice-test
SPINE_CLI="$PWD/build/spine-cli" SPINE_FAULT_CLI="$PWD/build/spine-cli-fault" \
SPINE_ADAPTER_LIB="$PWD/build/libspine-adapter.so" python3 -m unittest discover -s tests -v
