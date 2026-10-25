#ifndef SP_STORE_H
#define SP_STORE_H
/* Root must already exist. Local storage ACK never means remote delivery. */
int sp_store_ingest(const char *root,const char *json);
int sp_store_pending(const char *root);
int sp_store_deliver(const char *root,const char *endpoint);
/* Quiet step. Outcome is meaningful only when return code is zero. */
enum sp_delivery_outcome { SP_SENT, SP_EMPTY, SP_SUPERSEDED };
int sp_store_delivery_step(const char *root,const char *endpoint,int *outcome);
#endif
