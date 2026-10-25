#ifndef SP_INGRESS_H
#define SP_INGRESS_H
#include "spine.h"
/* Replay ingress only. No motion, durable ACK or live identity claim. */
int sp_ingest_json(const char *json, int threshold);
/* Caller owns both strings and releases them with cJSON_free. */
int sp_decode_event(const char *json,int threshold,char **event,char **assessment);
int sp_json_bounded(const char *json);
#endif
