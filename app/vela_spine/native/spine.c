#include "spine.h"
#include <limits.h>

int sp_assess(const sp_event *e, int threshold, sp_assessment *out)
{
  int i, sum = 0, mask = 0;
  int value[4];
  const int weight[4] = {40, 30, 20, 10};
  if (!e || !out || threshold < 0 || threshold > 100 ||
      (e->fresh != 0 && e->fresh != 1)) return -1;
  value[0]=e->consequence; value[1]=e->urgency;
  value[2]=e->exposure; value[3]=e->spread;
  for (i=0; i<4; ++i) {
    if (value[i] < -1 || value[i] > 5) return -1;
    if (value[i] == -1) mask |= 1 << i;
    else sum += value[i] * weight[i];
  }
  /* Score is a known-evidence lower bound if fields are unknown. */
  out->score = sum / 5;
  out->unknown_mask = mask;
  out->decision = out->score > threshold ? SP_IMMEDIATE :
                  (mask || !e->fresh ? SP_REVIEW : SP_AUTO);
  return 0;
}

static void search(const sp_problem *p, int t, int *remaining, int *owner,
                   int missed, int cost, sp_allocation *best)
{
  int r, i;
  if (missed > best->uncovered_priority ||
      (missed == best->uncovered_priority && cost >= best->total_cost)) return;
  if (t == p->tags) {
    best->uncovered_priority=missed; best->total_cost=cost;
    for (i=0; i<SP_MAX_TAGS; ++i) best->owner[i]=owner[i];
    return;
  }
  for (r=0; r<p->robots; ++r) {
    i=t*SP_MAX_ROBOTS+r;
    if (!p->eligible[i] || p->energy[i] > remaining[r]) continue;
    owner[t]=r; remaining[r]-=p->energy[i];
    search(p,t+1,remaining,owner,missed,cost+p->cost[i],best);
    remaining[r]+=p->energy[i];
  }
  owner[t]=-1;
  search(p,t+1,remaining,owner,missed+p->priority[t],cost,best);
}

int sp_allocate(const sp_problem *p, sp_allocation *out)
{
  int i,r,remaining[SP_MAX_ROBOTS],owner[SP_MAX_TAGS];
  if (!p || !out || p->tags<0 || p->tags>SP_MAX_TAGS ||
      p->robots<1 || p->robots>SP_MAX_ROBOTS) return -1;
  for(r=0;r<p->robots;++r) {
    if(p->budget[r]<0 || p->budget[r]>1000000) return -1;
    remaining[r]=p->budget[r];
  }
  for(i=0;i<SP_MAX_TAGS;++i) owner[i]=-1;
  for(i=0;i<p->tags;++i) {
    if(p->priority[i]<1 || p->priority[i]>1000) return -1;
    for(r=0;r<p->robots;++r) {
      int k=i*SP_MAX_ROBOTS+r;
      if(p->eligible[k]!=0 && p->eligible[k]!=1) return -1;
      if(p->energy[k]<0 || p->energy[k]>1000000 ||
         p->cost[k]<0 || p->cost[k]>1000000) return -1;
    }
  }
  out->uncovered_priority=INT_MAX; out->total_cost=INT_MAX;
  search(p,0,remaining,owner,0,0,out);
  return 0;
}
