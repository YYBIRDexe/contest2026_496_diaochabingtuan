include $(APPDIR)/Make.defs
PROGNAME = vela_spine
PRIORITY = 100
STACKSIZE = 16384
MODULE = $(CONFIG_EXAMPLES_VELA_SPINE)
CSRCS = native/spine.c native/ingress.c native/store.c native/transport.c native/watch.c native/human.c agent_adapter/readonly_call.c agent_adapter/query_context.c
CFLAGS += ${INCDIR_PREFIX}$(APPDIR)/netutils/cjson/cJSON
MAINSRC = spine_main.c
include $(APPDIR)/Application.mk
