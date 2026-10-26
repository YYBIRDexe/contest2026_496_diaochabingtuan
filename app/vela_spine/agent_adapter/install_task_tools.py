#!/usr/bin/env python3
"""Register the three spine task tools in the official ai_agent application.

The script is idempotent and path agnostic:

  python3 install_task_tools.py --ai-agent /path/to/app/ai_agent [--dry-run]

It performs three edits, each guarded by the VELAGUARD_SPINE_TASK_TOOLS marker:

  1. copy board/tool_task.c and board/tool_task.h into <ai_agent>/src/tools/
  2. register task_status / task_submit / task_stop after formation_control,
     with local extern declarations (same style as the verified read-only
     bridge, so no include ordering can break the patch)
  3. append src/tools/tool_task.c to AGENT_SRCS in CMakeLists.txt

Every file is backed up once as <name>.codex-pre-spine-tasks before the first
edit. A second run must report "unchanged". The script never touches the
board, never rebuilds, and never claims a tool executed on the vehicle.
"""

import argparse
import shutil
import sys
from pathlib import Path

MARKER = "VELAGUARD_SPINE_TASK_TOOLS"
BACKUP_SUFFIX = ".codex-pre-spine-tasks"

INCLUDE_ANCHOR = '#include "tools/tool_formation.h"'
INCLUDE_BLOCK = ""  # kept for old patches; the extern declarations below win

REGISTER_ANCHOR = "tool_formation_execute);"
REGISTER_BLOCK = """

#ifdef CONFIG_EXAMPLES_VELA_SPINE
    /* %s: three narrow business tools, every argument is validated by the
     * board task ledger; a persisted plan is not an executed task.
     */

    extern int tool_task_status_execute(const char *input_json, char *output,
                                        size_t output_size);
    extern int tool_task_submit_execute(const char *input_json, char *output,
                                        size_t output_size);
    extern int tool_task_stop_execute(const char *input_json, char *output,
                                      size_t output_size);

    REGISTER_TOOL(
        "task_status",
        "Read the board task ledger. Optional argument {\\"task_id\\":\\"...\\"}. "
        "The answer is the durable board state, not a cached acknowledgement.",
        "{\\"type\\":\\"object\\",\\"properties\\":{\\"task_id\\":{\\"type\\":\\"string\\"}}}",
        tool_task_status_execute);

    REGISTER_TOOL(
        "task_submit",
        "Submit a structured mission plan to the board task ledger. The ledger "
        "checks fields, plan version, single ownership and risk holds; a plan "
        "that is persisted has not been executed by any vehicle yet.",
        "{\\"type\\":\\"object\\",\\"properties\\":{"
        "\\"plan_id\\":{\\"type\\":\\"string\\"},"
        "\\"version\\":{\\"type\\":\\"integer\\",\\"minimum\\":1},"
        "\\"tasks\\":{\\"type\\":\\"array\\",\\"items\\":{\\"type\\":\\"object\\","
        "\\"properties\\":{\\"task_id\\":{\\"type\\":\\"string\\"},"
        "\\"tag_id\\":{\\"type\\":\\"string\\"},"
        "\\"robot_id\\":{\\"type\\":\\"string\\",\\"enum\\":[\\"S1\\",\\"S2\\",\\"S3\\",\\"AUTO\\"]},"
        "\\"revision\\":{\\"type\\":\\"integer\\",\\"minimum\\":1},"
        "\\"priority\\":{\\"type\\":\\"integer\\",\\"minimum\\":0,\\"maximum\\":1000}},"
        "\\"required\\":[\\"task_id\\",\\"tag_id\\"]}}}},"
        "\\"required\\":[\\"plan_id\\",\\"version\\",\\"tasks\\"]}",
        tool_task_submit_execute);

    REGISTER_TOOL(
        "task_stop",
        "Request a stop for one task. The owner is only released after the "
        "executor reports STOP_CONFIRMED, so treat this result as a request "
        "until the ledger state says STOP_CONFIRMED.",
        "{\\"type\\":\\"object\\",\\"properties\\":{\\"task_id\\":{\\"type\\":\\"string\\"}},"
        "\\"required\\":[\\"task_id\\"]}",
        tool_task_stop_execute);
#endif
""" % MARKER

CMAKE_ANCHOR = """  if(CONFIG_AI_AGENT_FORMATION_TOOL)
    list(APPEND AGENT_SRCS src/tools/tool_formation.c)
  endif()"""

CMAKE_BLOCK = CMAKE_ANCHOR + """

  # %s
  if(CONFIG_EXAMPLES_VELA_SPINE)
    list(APPEND AGENT_SRCS src/tools/tool_task.c)
  endif()""" % MARKER


def read_text(path):
    return path.read_text(encoding="utf-8")


def backup_once(path):
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)
        return backup
    return None


def insert_after(text, anchor, block, label, apply):
    """Insert block after the first line containing anchor."""
    position = text.find(anchor)
    if position < 0:
        raise SystemExit("anchor not found for %s: %r" % (label, anchor))

    end = text.find("\n", position)
    if end < 0:
        end = len(text)
    else:
        end += 1

    updated = text[:end] + block + text[end:]
    if apply:
        return updated
    return updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-agent", required=True,
                        help="directory of the official ai_agent application")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the edits without writing anything")
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    board = here / "board"
    agent = Path(args.ai_agent).resolve()
    tools_dir = agent / "src" / "tools"
    registry = tools_dir / "tool_registry.c"
    cmake = agent / "CMakeLists.txt"

    for required in (board / "tool_task.c", board / "tool_task.h", registry, cmake):
        if not required.is_file():
            raise SystemExit("missing required file: %s" % required)

    changes = []
    dry = args.dry_run

    for name in ("tool_task.c", "tool_task.h"):
        source = board / name
        target = tools_dir / name
        same = target.is_file() and target.read_bytes() == source.read_bytes()
        if not same:
            changes.append("copy %s -> %s" % (source.name, target))
            if not dry:
                if target.is_file():
                    backup_once(target)
                shutil.copy2(source, target)

    text = read_text(registry)
    if MARKER not in text:
        changes.append("patch tool_registry.c registrations")
        if not dry:
            backup_once(registry)
            text = insert_after(text, REGISTER_ANCHOR, REGISTER_BLOCK, "register", True)
            registry.write_text(text, encoding="utf-8")
    else:
        missing = REGISTER_BLOCK.strip().splitlines()[0]
        if "tool_task_status_execute" not in text or missing.strip() not in text:
            raise SystemExit("registry marker present but registrations are incomplete")

    text = read_text(cmake)
    if MARKER not in text:
        changes.append("patch CMakeLists.txt")
        if not dry:
            backup_once(cmake)
            if CMAKE_ANCHOR not in text:
                raise SystemExit("CMakeLists.txt formation block not found")
            text = text.replace(CMAKE_ANCHOR, CMAKE_BLOCK, 1)
            cmake.write_text(text, encoding="utf-8")
    else:
        if "src/tools/tool_task.c" not in text:
            raise SystemExit("CMake marker present but source entry is missing")

    if not changes:
        print('{"status": "UNCHANGED", "ai_agent": "%s"}' % agent)
        return 0

    for item in changes:
        print(("DRY " if dry else "APPLY ") + item)

    print('{"status": "%s", "ai_agent": "%s", "edits": %d, '
          '"note": "source patch only; not a board registration or execution"}'
          % ("DRY_RUN" if dry else "PATCHED", agent, len(changes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
