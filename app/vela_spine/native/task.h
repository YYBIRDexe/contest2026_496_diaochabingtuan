#ifndef SP_TASK_H
#define SP_TASK_H
/* Board-side task ledger. An executor ACK is never completion and a timeout
   never releases ownership: only a terminal state confirmed by the executor
   (COMPLETED/FAILED/STOP_CONFIRMED) or a never-dispatched CANCELLED frees a
   robot. Root must already exist. */
#define SP_TASK_CAPACITY 24
#define SP_TASK_SNAPSHOT_MAX 131072
int sp_task_plan_apply(const char *root,const char *json,char **reply);
int sp_task_dispatch(const char *root,const char *endpoint,char **reply);
int sp_task_poll(const char *root,const char *endpoint,char **reply);
int sp_task_stop(const char *root,const char *task_id,const char *reason,char **reply);
int sp_task_stop_sync(const char *root,const char *endpoint,char **reply);
int sp_task_view(const char *root,const char *task_id,char **reply);
#endif
