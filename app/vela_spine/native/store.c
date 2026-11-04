#include "store.h"
#include "ingress.h"
#include "transport.h"
#include "human.h"
#include "cJSON.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>

#define CAPACITY 32
#define SNAPSHOT_MAX 65536
static const char *const decisions[]={"AUTO","HUMAN_REVIEW","IMMEDIATE_HUMAN"};
static cJSON *get(const cJSON *o,const char *s)
{ return cJSON_GetObjectItemCaseSensitive(o,s); }
static int path(char *out,size_t size,const char *root,const char *name)
{ int n=snprintf(out,size,"%s/%s",root,name);return n<0||(size_t)n>=size?-1:0; }
static int level(const cJSON *a)
{
  cJSON *v=get(a,"decision");int i;
  if(!cJSON_IsString(v)) return -1;
  for(i=0;i<3;i++) if(!strcmp(v->valuestring,decisions[i])) return i;
  return -1;
}
static void checksum(const char *s,char out[9])
{
  uint32_t crc=~(uint32_t)0;int i;
  for(;*s;s++) { crc^=(unsigned char)*s;for(i=0;i<8;i++) crc=(crc>>1)^((crc&1)?0xedb88320U:0); }
  snprintf(out,9,"%08lx",(unsigned long)(~crc));
}
static int lock_store(const char *root)
{
  char p[256];struct stat st;struct flock lock;int fd;
  if(stat(root,&st)||!S_ISDIR(st.st_mode)||path(p,sizeof(p),root,"lock")) return -1;
  fd=open(p,O_RDWR|O_CREAT,0600);if(fd<0) return -1;
  memset(&lock,0,sizeof(lock));lock.l_type=F_WRLCK;lock.l_whence=SEEK_SET;
  if(fcntl(fd,F_SETLK,&lock)<0) {close(fd);return -1;}
  return fd;
}
/* Missing snapshot is empty; malformed/unreadable snapshots are never reset. */
static cJSON *load(const char *root)
{
  char p[256],sum[9],*buf=NULL,*text=NULL;FILE *fp=NULL;
  cJSON *doc=NULL,*records=NULL,*v,*row;size_t n;int ok=0;
  if(path(p,sizeof(p),root,"state.json")) return NULL;
  fp=fopen(p,"rb");
  if(!fp) return errno==ENOENT?cJSON_CreateArray():NULL;
  buf=malloc(SNAPSHOT_MAX+2);if(!buf) goto done;
  n=fread(buf,1,SNAPSHOT_MAX+1,fp);
  if(ferror(fp)||n>SNAPSHOT_MAX||!feof(fp)||memchr(buf,0,n)) goto done;
  buf[n]=0;if(!sp_json_bounded(buf)) goto done;
  doc=cJSON_ParseWithOpts(buf,NULL,1);if(!cJSON_IsObject(doc)) goto done;
  v=get(doc,"schema");if(!cJSON_IsNumber(v)||v->valuedouble!=1) goto done;
  records=get(doc,"records");
  if(!cJSON_IsArray(records)||cJSON_GetArraySize(records)>CAPACITY) goto done;
  text=cJSON_PrintUnformatted(records);if(!text) goto done;
  checksum(text,sum);v=get(doc,"crc32");
  if(!cJSON_IsString(v)||strcmp(v->valuestring,sum)) goto done;
  cJSON_ArrayForEach(row,records) {
    char *raw=NULL,*canonical=NULL,*assessment=NULL;int bad; cJSON *other;
    if(!cJSON_IsObject(row)||!cJSON_IsObject(get(row,"event"))||
       !cJSON_IsObject(get(row,"assessment"))||level(get(row,"assessment"))<0||
       !cJSON_IsBool(get(row,"pending"))||
       (get(row,"delivered")&&!cJSON_IsBool(get(row,"delivered")))||
       !sp_human_record_valid(row)) goto done;
    raw=cJSON_PrintUnformatted(get(row,"event"));if(!raw) goto done;
    bad=sp_decode_event(raw,70,&canonical,&assessment);
    cJSON_free(raw);cJSON_free(canonical);cJSON_free(assessment);if(bad) goto done;
    if(get(row,"escalation_event")) {
      v=get(row,"escalation_score");
      if(!cJSON_IsNumber(v)||v->valuedouble<0||v->valuedouble>100||
         v->valuedouble!=(double)v->valueint) goto done;
      raw=cJSON_PrintUnformatted(get(row,"escalation_event"));if(!raw) goto done;
      canonical=assessment=NULL;
      bad=sp_decode_event(raw,70,&canonical,&assessment);
      cJSON_free(raw);cJSON_free(canonical);cJSON_free(assessment);if(bad) goto done;
    } else if(get(row,"escalation_score")) goto done;
    for(other=records->child;other!=row;other=other->next)
      if(!strcmp(get(get(other,"event"),"event_id")->valuestring,
                 get(get(row,"event"),"event_id")->valuestring)) goto done;
  }
  ok=1;
done:
  if(fp) fclose(fp);
  free(buf);cJSON_free(text);
  if(ok) records=cJSON_DetachItemFromObjectCaseSensitive(doc,"records");
  else records=NULL;
  cJSON_Delete(doc);return records;
}
static int save(const char *root,cJSON *records)
{
  cJSON *doc=NULL;char *body=NULL,*rows=NULL,sum[9],tmp[256],dst[256];
  int fd=-1,ret=-1,owned=0;size_t size,off=0;
  if(path(tmp,sizeof(tmp),root,"state.tmp")||path(dst,sizeof(dst),root,"state.json")) return -1;
  rows=cJSON_PrintUnformatted(records);if(!rows) goto done;
  checksum(rows,sum);doc=cJSON_CreateObject();if(!doc) goto done;
  if(!cJSON_AddNumberToObject(doc,"schema",1)||!cJSON_AddStringToObject(doc,"crc32",sum)) goto done;
  {cJSON *copy=cJSON_Duplicate(records,1);if(!copy) goto done;
   if(!cJSON_AddItemToObject(doc,"records",copy)){cJSON_Delete(copy);goto done;}}
  body=cJSON_PrintUnformatted(doc);if(!body) goto done;
  size=strlen(body);if(size>SNAPSHOT_MAX) goto done;
  fd=open(tmp,O_WRONLY|O_CREAT|O_TRUNC,0600);if(fd<0) goto done;owned=1;
  while(off<size) {
    ssize_t n=write(fd,body+off,size-off);
    if(n<0&&errno==EINTR) continue;
    if(n<=0) goto done;
    off+=(size_t)n;
  }
  if(fsync(fd)) goto done;
  if(close(fd)) {fd=-1;goto done;}fd=-1;
  if(rename(tmp,dst)) goto done;
  owned=0;ret=0;
done:
  if(fd>=0) close(fd);
  if(owned) unlink(tmp);
  cJSON_Delete(doc);cJSON_free(body);cJSON_free(rows);return ret;
}
static int emit(cJSON *assessment,const char *status,int ack,int pending,int delivered)
{
  char *s;
  cJSON_DeleteItemFromObjectCaseSensitive(assessment,"status");
  cJSON_DeleteItemFromObjectCaseSensitive(assessment,"durable_ack");
  if(!cJSON_AddStringToObject(assessment,"status",status)||
     !cJSON_AddBoolToObject(assessment,"durable_ack",ack)||
     !cJSON_AddStringToObject(assessment,"ack_scope","LOCAL_STORAGE_ONLY")||
     !cJSON_AddStringToObject(assessment,"delivery_status",pending?(delivered?"DELIVERED":"PENDING"):"NOT_REQUIRED")) return 3;
  s=cJSON_PrintUnformatted(assessment);if(!s) return 3;
  puts(s);cJSON_free(s);return 0;
}
int sp_store_ingest(const char *root,const char *json)
{
  char *canonical=NULL,*text=NULL;int fd=-1,ret=3,newlevel,observed,oldlevel=0;
  cJSON *event=NULL,*a=NULL,*records=NULL,*old=NULL,*row,*record=NULL,*v;
  if(sp_decode_event(json,70,&canonical,&text)) {fputs("event rejected\n",stderr);return 2;}
  event=cJSON_Parse(canonical);a=cJSON_Parse(text);if(!event||!a) goto done;
  fd=lock_store(root);if(fd<0) goto done;
  records=load(root);if(!records) goto done;
  cJSON_ArrayForEach(row,records)
    if(!strcmp(get(get(row,"event"),"event_id")->valuestring,get(event,"event_id")->valuestring)) {old=row;break;}
  if(old) {
    cJSON *prev=get(old,"event");int rev=get(event,"revision")->valueint,prior=get(prev,"revision")->valueint;
    if(strcmp(get(prev,"robot_id")->valuestring,get(event,"robot_id")->valuestring)||
       strcmp(get(prev,"tag_id")->valuestring,get(event,"tag_id")->valuestring)) goto done;
    if(rev<=prior) {
      if(rev==prior&&!cJSON_Compare(prev,event,1)) goto done;
      cJSON_Delete(a);a=cJSON_Duplicate(get(old,"assessment"),1);if(!a) goto done;
      ret=emit(a,rev==prior?"DUPLICATE":"STALE_IGNORED",rev==prior,cJSON_IsTrue(get(old,"pending")),cJSON_IsTrue(get(old,"delivered")));
      goto done;
    }
    oldlevel=!strcmp(sp_human_state(old),"CLOSED")?0:level(get(old,"assessment"));
  } else if(cJSON_GetArraySize(records)>=CAPACITY) goto done;
  newlevel=level(a);if(newlevel<0) goto done;observed=newlevel;
  v=get(a,"decision");
  if(!cJSON_AddStringToObject(a,"current_decision",v->valuestring)) goto done;
  if(oldlevel>newlevel) {
    if(!cJSON_SetValuestring(v,decisions[oldlevel])) goto done;
    newlevel=oldlevel;
  }
  if(!cJSON_AddBoolToObject(a,"latched",oldlevel>0&&strcmp(get(a,"current_decision")->valuestring,get(a,"decision")->valuestring))) goto done;
  record=cJSON_CreateObject();if(!record) goto done;
  if(!cJSON_AddItemToObject(record,"event",event)) goto done;
  event=NULL;
  {cJSON *copy=cJSON_Duplicate(a,1);if(!copy) goto done;
   cJSON_DeleteItemFromObjectCaseSensitive(copy,"status");
   cJSON_DeleteItemFromObjectCaseSensitive(copy,"durable_ack");
   if(!cJSON_AddItemToObject(record,"assessment",copy)){cJSON_Delete(copy);goto done;}}
  if(!cJSON_AddBoolToObject(record,"pending",newlevel>0)||
     !cJSON_AddBoolToObject(record,"delivered",0)) goto done;
  if(old&&get(old,"human")) {
    cJSON *previous=cJSON_Duplicate(get(old,"human"),1);
    if(!previous||!cJSON_AddItemToObject(record,"previous_human",previous)){cJSON_Delete(previous);goto done;}
  }
  if(newlevel>0) {
    cJSON *trigger=get(record,"event"),*previous=NULL,*copy;
    double trigger_score=get(a,"score")->valuedouble;
    if(old&&oldlevel>observed) {
      previous=get(old,"escalation_event");
      trigger=previous?previous:get(old,"event");
      previous=get(old,"escalation_score");
      trigger_score=previous?previous->valuedouble:get(get(old,"assessment"),"score")->valuedouble;
    }
    copy=cJSON_Duplicate(trigger,1);if(!copy) goto done;
    if(!cJSON_AddItemToObject(record,"escalation_event",copy)){cJSON_Delete(copy);goto done;}
    if(!cJSON_AddNumberToObject(record,"escalation_score",trigger_score)) goto done;
  }
  if(old) {
    if(!cJSON_ReplaceItemViaPointer(records,old,record)) goto done;
  } else if(!cJSON_AddItemToArray(records,record)) goto done;
  record=NULL;
  if(save(root,records)) goto done;
  ret=emit(a,"ACCEPTED_PERSISTED",1,newlevel>0,0);
done:
  if(fd>=0) close(fd);
  cJSON_free(canonical);cJSON_free(text);cJSON_Delete(event);cJSON_Delete(a);
  cJSON_Delete(record);cJSON_Delete(records);
  if(ret==3) fputs("store rejected: unavailable, full, corrupt or revision conflict\n",stderr);
  return ret;
}
int sp_store_pending(const char *root)
{
  int fd=lock_store(root),ret=3,priority;cJSON *records=NULL,*out=NULL,*row;char *text=NULL;
  if(fd<0) goto done;
  records=load(root);out=cJSON_CreateArray();if(!records||!out) goto done;
  for(priority=2;priority>=1;priority--) cJSON_ArrayForEach(row,records)
    if(cJSON_IsTrue(get(row,"pending"))&&level(get(row,"assessment"))==priority) {
      cJSON *copy=cJSON_Duplicate(row,1);if(!copy) goto done;
      if(!cJSON_AddItemToArray(out,copy)){cJSON_Delete(copy);goto done;}
    }
  text=cJSON_PrintUnformatted(out);if(!text) goto done;
  puts(text);ret=0;
done:
  if(fd>=0) close(fd);
  cJSON_Delete(records);cJSON_Delete(out);cJSON_free(text);
  if(ret) fputs("store unavailable or corrupt\n",stderr);
  return ret;
}

static int delivery_result(const char *status,const char *id,int remote,int code)
{
  cJSON *o=cJSON_CreateObject();char *s=NULL;
  if(!o) return 3;
  if(!cJSON_AddStringToObject(o,"status",status)||
     !cJSON_AddStringToObject(o,"notification_id",id)||
     !cJSON_AddBoolToObject(o,"remote_ack",remote)||
     !cJSON_AddStringToObject(o,"ack_scope","REMOTE_STORAGE_ONLY")||
     !cJSON_AddStringToObject(o,"human_status",id[0]?"REQUIRED":"NOT_APPLICABLE")||
     !cJSON_AddBoolToObject(o,"motion",0)) goto done;
  s=cJSON_PrintUnformatted(o);if(s) puts(s);
done:
  cJSON_Delete(o);if(!s)return 3;cJSON_free(s);return code;
}
static int deliver(const char *root,const char *endpoint,int *outcome)
{
  cJSON *records=NULL,*row=NULL,*selected=NULL,*payload=NULL,*copy=NULL;
  char *body=NULL,id[96],eid[65];int fd=-1,ret=3,revision=0,priority,remote=0;
  const char *status="RETRY_PENDING";
  id[0]=eid[0]=0;
  fd=lock_store(root);if(fd<0) {if(errno==EAGAIN||errno==EACCES)ret=4;goto done;}
  records=load(root);if(!records) goto done;
  for(priority=2;priority>=1&&!selected;priority--) cJSON_ArrayForEach(row,records)
    if(cJSON_IsTrue(get(row,"pending"))&&!cJSON_IsTrue(get(row,"delivered"))&&
       level(get(row,"assessment"))==priority) {selected=row;break;}
  if(!selected) {status="EMPTY";ret=0;goto done;}
  strncpy(eid,get(get(selected,"event"),"event_id")->valuestring,sizeof(eid)-1);eid[64]=0;
  revision=get(get(selected,"event"),"revision")->valueint;
  snprintf(id,sizeof(id),"%s:%d",eid,revision);
  payload=cJSON_CreateObject();if(!payload) goto done;
  if(!cJSON_AddStringToObject(payload,"notification_id",id)||
     !cJSON_AddStringToObject(payload,"human_status","REQUIRED")||
     !cJSON_AddStringToObject(payload,"execution","NONE")) goto done;
#ifdef CONFIG_EXAMPLES_VELA_SPINE
  if(!cJSON_AddStringToObject(payload,"source","GEMINI_REPLAY_NATIVE_C")) goto done;
#else
  if(!cJSON_AddStringToObject(payload,"source","HOST_NATIVE_C_TRANSPORT_TEST")) goto done;
#endif
  copy=cJSON_Duplicate(get(selected,"event"),1);if(!copy) goto done;
  if(!cJSON_AddItemToObject(payload,"event",copy)) goto done;
  copy=NULL;
  copy=cJSON_Duplicate(get(selected,"assessment"),1);if(!copy) goto done;
  cJSON_DeleteItemFromObjectCaseSensitive(copy,"status");
  cJSON_DeleteItemFromObjectCaseSensitive(copy,"durable_ack");
  if(!cJSON_AddItemToObject(payload,"assessment",copy)) goto done;
  copy=NULL;
  if(get(selected,"escalation_event")) {
    copy=cJSON_Duplicate(get(selected,"escalation_event"),1);if(!copy) goto done;
    if(!cJSON_AddItemToObject(payload,"escalation_event",copy)) goto done;
    copy=NULL;
    if(!cJSON_AddNumberToObject(payload,"escalation_score",get(selected,"escalation_score")->valuedouble)) goto done;
  }
  body=cJSON_PrintUnformatted(payload);if(!body) goto done;
  /* Never hold the state lock during network I/O. */
  close(fd);fd=-1;cJSON_Delete(records);records=NULL;
  ret=1;
  if(sp_http_post(endpoint,body,id)) goto done;
  remote=1;
  fd=lock_store(root);if(fd<0) goto done;
  records=load(root);if(!records) goto done;
  selected=NULL;
  cJSON_ArrayForEach(row,records)
    if(!strcmp(get(get(row,"event"),"event_id")->valuestring,eid)) {selected=row;break;}
  if(!selected) goto done;
  if(get(get(selected,"event"),"revision")->valueint!=revision) {
    status="ACK_FOR_OLDER_REVISION";ret=0;goto done;
  }
  copy=cJSON_CreateTrue();if(!copy) goto done;
  if(get(selected,"delivered")) {
    if(!cJSON_ReplaceItemInObjectCaseSensitive(selected,"delivered",copy)) goto done;
  } else if(!cJSON_AddItemToObject(selected,"delivered",copy)) goto done;
  copy=NULL;
  if(save(root,records)) goto done;
  status="DELIVERED";ret=0;
done:
  if(fd>=0)close(fd);
  cJSON_Delete(copy);cJSON_Delete(records);cJSON_Delete(payload);cJSON_free(body);
  if(ret==3) {fputs("delivery store unavailable\n",stderr);return ret;}
  if(outcome) {
    if(ret==0)*outcome=!strcmp(status,"EMPTY")?SP_EMPTY:
                      !strcmp(status,"ACK_FOR_OLDER_REVISION")?SP_SUPERSEDED:SP_SENT;
    return ret;
  }
  return delivery_result(status,id,remote,ret);
}
int sp_store_deliver(const char *root,const char *endpoint)
{ return deliver(root,endpoint,NULL); }
int sp_store_delivery_step(const char *root,const char *endpoint,int *outcome)
{ return deliver(root,endpoint,outcome); }

int sp_store_human_apply(const char *root,const cJSON *command,const char *payload,char **result)
{
  cJSON *records=NULL,*row=NULL,*r,*h=NULL,*history,*entry,*copy,*o=NULL,*p;
  const char *status="STATE_REJECTED",*state="NOT_FOUND",*step=get(command,"step")->valuestring;
  const char *id=get(command,"action_id")->valuestring,*eid=get(command,"event_id")->valuestring;
  int fd=-1,ret=3,current=0,rev=get(command,"revision")->valueint;
  *result=NULL;
  fd=lock_store(root);if(fd<0)goto done;
  records=load(root);if(!records)goto done;
  cJSON_ArrayForEach(r,records)
    if(!strcmp(get(get(r,"event"),"event_id")->valuestring,eid)){row=r;break;}
  if(!row)goto response;
  current=get(get(row,"event"),"revision")->valueint;state=sp_human_state(row);
  if(current!=rev){status="STALE_REJECTED";goto response;}
  cJSON_ArrayForEach(r,records) {
    cJSON *entries=get(get(r,"human"),"actions");
    cJSON_ArrayForEach(entry,entries) {
      if(!strcmp(get(entry,"action_id")->valuestring,id)) {
        status=r==row&&!strcmp(get(entry,"payload")->valuestring,payload)?"DUPLICATE":"STATE_REJECTED";
        goto response;
      }
    }
  }
  if(!cJSON_IsTrue(get(row,"pending")))goto response;
  if((!strcmp(step,"CLAIM")&&strcmp(state,"REQUIRED"))||
     (!strcmp(step,"HANDLE")&&strcmp(state,"CLAIMED"))||
     (!strcmp(step,"CLOSE")&&strcmp(state,"HANDLED")))goto response;
  if(strcmp(step,"CLAIM")) {
    p=get(get(row,"human"),"actor");
    if(!cJSON_IsString(p)||strcmp(p->valuestring,get(command,"actor")->valuestring))goto response;
  }
  h=get(row,"human")?cJSON_Duplicate(get(row,"human"),1):cJSON_CreateObject();if(!h)goto done;
  cJSON_DeleteItemFromObjectCaseSensitive(h,"state");
  cJSON_DeleteItemFromObjectCaseSensitive(h,"actor");
  cJSON_DeleteItemFromObjectCaseSensitive(h,"note");
  cJSON_DeleteItemFromObjectCaseSensitive(h,"verified");
  if(!cJSON_AddStringToObject(h,"state",!strcmp(step,"CLAIM")?"CLAIMED":!strcmp(step,"HANDLE")?"HANDLED":"CLOSED")||
     !cJSON_AddStringToObject(h,"actor",get(command,"actor")->valuestring)||
     !cJSON_AddStringToObject(h,"note",get(command,"note")->valuestring)||
     !cJSON_AddBoolToObject(h,"verified",cJSON_IsTrue(get(command,"verified"))))goto done;
  history=get(h,"actions");
  if(!history){history=cJSON_AddArrayToObject(h,"actions");if(!history)goto done;}
  entry=cJSON_CreateObject();if(!entry)goto done;
  if(!cJSON_AddStringToObject(entry,"action_id",id)||!cJSON_AddStringToObject(entry,"payload",payload)||
     !cJSON_AddItemToArray(history,entry)){cJSON_Delete(entry);goto done;}
  if(get(row,"human")) {
    if(!cJSON_ReplaceItemInObjectCaseSensitive(row,"human",h))goto done;
  }else if(!cJSON_AddItemToObject(row,"human",h))goto done;
  h=NULL;
  if(!strcmp(step,"CLOSE")) {
    copy=cJSON_CreateFalse();if(!copy)goto done;
    if(!cJSON_ReplaceItemInObjectCaseSensitive(row,"pending",copy)){cJSON_Delete(copy);goto done;}
  }
  if(save(root,records))goto done;
  status="APPLIED";state=sp_human_state(row);
response:
  o=cJSON_CreateObject();if(!o)goto done;
  if(!cJSON_AddStringToObject(o,"action_id",id)||!cJSON_AddStringToObject(o,"event_id",eid)||
     !cJSON_AddNumberToObject(o,"revision",rev)||!cJSON_AddNumberToObject(o,"current_revision",current)||
     !cJSON_AddStringToObject(o,"status",status)||!cJSON_AddStringToObject(o,"human_state",state)||
     !cJSON_AddBoolToObject(o,"pending",row&&cJSON_IsTrue(get(row,"pending"))))goto done;
  *result=cJSON_PrintUnformatted(o);if(*result)ret=0;
done:
  if(fd>=0)close(fd);
  cJSON_Delete(records);cJSON_Delete(h);cJSON_Delete(o);return ret;
}

/* Highest unresolved escalation level recorded for one tag. Only a human CLOSE
   clears an entry, so a hold survives unrelated traffic. */
int sp_store_tag_risk(const char *root,const char *tag_id,int *out)
{
  int fd,ret=3,worst=0;cJSON *records=NULL,*row,*event;const char *t;
  if(!out||!tag_id)return 3;
  *out=0;
  fd=lock_store(root);if(fd<0)return 3;
  records=load(root);if(!records){close(fd);return 3;}
  cJSON_ArrayForEach(row,records){
    event=get(row,"event");
    t=get(event,"tag_id")?get(event,"tag_id")->valuestring:NULL;
    if(!t||strcmp(t,tag_id))continue;
    if(!cJSON_IsTrue(get(row,"pending")))continue;
    {int l=level(get(row,"assessment"));if(l>worst)worst=l;}
  }
  *out=worst;ret=0;
  close(fd);cJSON_Delete(records);
  return ret;
}
