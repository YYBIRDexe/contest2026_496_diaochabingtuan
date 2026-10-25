#include "native/spine.h"
#include "native/ingress.h"
#include "native/store.h"
#include "native/watch.h"
#include "native/human.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static int parse(const char *s, int low, int high, int *value)
{
  char *end; long n;
  errno=0; n=strtol(s,&end,10);
  if (errno || end==s || *end || n<low || n>high) return -1;
  *value=(int)n; return 0;
}

int main(int argc, char **argv)
{
  sp_event e; sp_assessment a;
  int threshold;
  const char *decision[] = {"AUTO", "HUMAN_REVIEW", "IMMEDIATE_HUMAN"};
  if(argc==2 && !strcmp(argv[1],"--service"))return sp_service();
  if(argc==3 && !strcmp(argv[1],"--pending")) return sp_store_pending(argv[2]);
  if(argc==4 && !strcmp(argv[1],"--deliver")) return sp_store_deliver(argv[2],argv[3]);
  if((argc==4 || argc==5) && !strcmp(argv[1],"--watch")) {
    int cycles=0;
    if(argc==5 && parse(argv[4],1,10000,&cycles)) return 2;
    return sp_watch(argv[2],argv[3],(unsigned)cycles);
  }
  if((argc==3 && !strcmp(argv[1],"--event")) ||
     (argc==4 && (!strcmp(argv[1],"--ingest")||!strcmp(argv[1],"--human")))) {
    char buf[4098]; size_t n; FILE *fp=fopen(argv[2],"rb");
    if(!fp) return 2;
    n=fread(buf,1,sizeof(buf)-1,fp);
    if(ferror(fp)||n>4096||!feof(fp)||memchr(buf,0,n)) { fclose(fp);return 2; }
    fclose(fp);buf[n]=0;
    if(!strcmp(argv[1],"--human")) {
      char *reply=NULL;int code=sp_human_apply_signed(argv[3],buf,&reply);
      if(reply){puts(reply);cJSON_free(reply);}return code;
    }
    return argc==4?sp_store_ingest(argv[3],buf):sp_ingest_json(buf,70);
  }
  if (argc==2 && !strcmp(argv[1],"--selftest")) {
    sp_problem p={0}; sp_allocation r;
    p.tags=2;p.robots=2;p.budget[0]=1;p.budget[1]=1;
    p.priority[0]=1;p.priority[1]=1;
    p.eligible[0]=1;p.energy[0]=1;p.cost[0]=1;
    p.eligible[1]=1;p.energy[1]=1;p.cost[1]=2;
    p.eligible[4]=1;p.energy[4]=1;p.cost[4]=1;
    if(sp_allocate(&p,&r) || r.owner[0]!=1 || r.owner[1]!=0) return 1;
    printf("{\"selftest\":\"PASS\",\"allocation\":[%d,%d],\"motion\":false}\n",r.owner[0],r.owner[1]);
    return 0;
  }
  if ((argc!=6 && argc!=7) ||
      parse(argv[1],-1,5,&e.consequence) || parse(argv[2],-1,5,&e.urgency) ||
      parse(argv[3],-1,5,&e.exposure) || parse(argv[4],-1,5,&e.spread) ||
      parse(argv[5],0,100,&threshold)) {
    fprintf(stderr,"usage: vela_spine C T P G threshold [fresh:0|1] | --selftest\n");return 2;
  }
  e.fresh=1;
  if(argc==7 && parse(argv[6],0,1,&e.fresh)) return 2;
  if(sp_assess(&e,threshold,&a)) return 2;
  printf("{\"score\":%d,\"decision\":\"%s\",\"unknown_mask\":%d,\"motion\":false}\n",a.score,decision[a.decision],a.unknown_mask);
  return 0;
}
