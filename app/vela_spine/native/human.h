#ifndef SP_HUMAN_H
#define SP_HUMAN_H
#include <stddef.h>
#include "cJSON.h"
/* The key remains on the board and controller; it is never sent over HTTP. */
int sp_human_sync_step(const char *root,const char *endpoint);
int sp_human_apply_signed(const char *root,const char *envelope,char **reply);
cJSON *sp_human_parse_command(const char *payload);
int sp_human_record_valid(const cJSON *record);
const char *sp_human_state(const cJSON *record);
#endif
