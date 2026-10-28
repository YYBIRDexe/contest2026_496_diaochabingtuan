# Native task requests

The existing reply guard requires a real call to the task tool selected from an
unambiguous user request. In the observed SDK, the API instead used its default
automatic choice and returned plain text despite all three registered tools
being present. Adding task context alone did not correct the observed stop call.

`install_task_tool_choice.py --ai-agent /path/to/packages/ai_agent` inserts a
request-builder hook after the SDK tools conversion. It copies the same task
classifier used by the reply guard and the portable `task_tool_choice.h` helper.
For the final user message only, a recognized task operation sets native
`tool_choice={"type":"function","function":{"name":...}}`. The named tool
must occur exactly once in the offered tools. Ambiguous/negated requests and
missing or duplicate tools fail closed. Other conversations and tool result
messages keep the ordinary SDK request. No arguments, history, risk checks,
reply parsing, execution or confirmation rules are rewritten.

This changes statically linked SDK code: rebuild and deploy before device tests.
The installer preserves `llm_proxy.c.pre-native-task-choice`; restore that file
and rebuild to undo the SDK change. Other installed SDK changes remain in that
backup, including the structural observation logging.

The installer also invalidates `tool_registry.c`'s JSON cache at initialization
and cleanup. The SDK previously freed the cache on exit while leaving it clean;
the next ai_agent start therefore produced no tool definitions. Its original
source is preserved as `tool_registry.c.pre-native-task-choice`. Restore both
backups and rebuild to undo both integration changes. Runtime acceptance must
include exiting and restarting ai_agent, not just its first start after reboot.

Named choice requires backend support. DeepSeek documents that it is supported
in non-thinking mode and rejected in thinking mode:
https://api-docs.deepseek.com/api/create-chat-completion/
The hook never changes the backend, model, thinking configuration or retry
policy. An incompatible backend must be reported as a failed model request;
do not fall back to executing parsed text or bypass the execution guard.

`install_task_context.py --backup-dir /private/new-directory` separately installs
the checked-in task policy in the runtime USER.md context while ai_agent is
stopped. It preserves all original bytes privately, stages mode 0600, verifies
the readback and then renames. Roll back with the same directory and
`--rollback`; a changed installed file is protected against overwrite. Firmware
rebuild is not needed for this runtime policy. No private configuration belongs
in the repository.

The Linux host build runs nine request boundary cases against actual cJSON.
These are request construction checks, not evidence that a real model executed
a tool. Device acceptance requires native response calls, executor receipts and
the corresponding durable task state, with simulation clearly identified.
