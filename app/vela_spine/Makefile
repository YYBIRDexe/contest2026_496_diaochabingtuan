include $(APPDIR)/Make.defs
PROGNAME = vela_spine
PRIORITY = 100
STACKSIZE = 32768
MODULE = $(CONFIG_EXAMPLES_VELA_SPINE)
CSRCS = native/spine.c native/ingress.c native/store.c native/transport.c native/watch.c native/human.c native/task.c native/task_watch.c agent_adapter/readonly_call.c agent_adapter/query_context.c agent_adapter/task_tools.c
CFLAGS += ${INCDIR_PREFIX}$(APPDIR)/netutils/cjson/cJSON
MAINSRC = spine_main.c
include $(APPDIR)/Application.mk
