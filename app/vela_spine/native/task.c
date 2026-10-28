#include "task.h"
#include "spine.h"
#include "ingress.h"
#include "store.h"
#include "transport.h"
#include "cJSON.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/stat.h>

#define COMMAND_KEEP 64
#define ID_MAX 64
/* PENDING never reached the executor; CANCELLED only applies there. Everything
   else changes only through a persisted executor report. */
static const char *const states[]={"PENDING","DISPATCHED","RUNNING","BLOCKED","STOP_REQUESTED","STOP_CONFIRMED","COMPLETED","FAILED","CANCELLED"};
static const char *const terminal_states[]={"STOP_CONFIRMED","COMPLETED","FAILED","CANCELLED"};
#define STATE_COUNT (sizeof(states)/sizeof(*states))
#define TERMINAL_COUNT (sizeof(terminal_states)/sizeof(*terminal_states))

struct plan_task {char task_id[ID_MAX+1];char tag_id[ID_MAX+1];char robot[8];long revision;long priority;};
struct dispatch_item {char task_id[ID_MAX+1];char tag_id[ID_MAX+1];char robot[8];long revision;long sequence;char command_id[104];char note[32];int frozen;int outcome;};

static cJSON *get(const cJSON *o,const char *k){return cJSON_GetObjectItemCaseSensitive(o,k);}
static const char *text_of(const cJSON *o,const char *k){const cJSON *v=get(o,k);return cJSON_IsString(v)?v->valuestring:NULL;}
static int one_of(const char *s,const char *const *list,size_t n)
{size_t i;if(!s)return 0;for(i=0;i<n;i++)if(!strcmp(s,list[i]))return 1;return 0;}
static int is_terminal(const char *s){return one_of(s,terminal_states,TERMINAL_COUNT);}
static int id_ok(const char *s)
{
  size_t i,n;if(!s||(n=strlen(s))<1||n>ID_MAX)return 0;
  for(i=0;i<n;i++){char c=s[i];
    if(!((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'||c=='-'))return 0;}
  return 1;
}
static int number_of(const cJSON *o,const char *k,long low,long high,long *out)
{
  const cJSON *v=get(o,k);double d;
  if(!cJSON_IsNumber(v))return -1;
  d=v->valuedouble;
  if(d<(double)low||d>(double)high||(double)(long)d!=d)return -1;
  if(out)*out=(long)d;
  return 0;
}
static int robot_index(const char *s)
{
  int i;static const char *const robots[]={"S1","S2","S3","S4"};
  if(!s)return -1;
  for(i=0;i<SP_MAX_ROBOTS;i++)if(!strcmp(s,robots[i]))return i;
  return -1;
}
static int duplicate_key(const cJSON *o)
{
  const cJSON *a,*b;
  for(a=o->child;a;a=a->next)for(b=o->child;b!=a;b=b->next)
    if(a->string&&b->string&&!strcmp(a->string,b->string))return 1;
  return 0;
}
static int keys_within(const cJSON *o,const char *const *names,int n)
{
  const cJSON *e;int i,hit;
  if(!cJSON_IsObject(o))return -1;
  cJSON_ArrayForEach(e,o){
    if(!e->string)return -1;
    hit=0;for(i=0;i<n;i++)if(!strcmp(e->string,names[i]))hit++;
    if(hit!=1)return -1;
  }
  return 0;
}
static unsigned long crc_of(const char *data)
{
  unsigned long crc=0xffffffffUL;int k;
  while(*data){crc^=(unsigned long)(unsigned char)*data++;
    for(k=0;k<8;k++)crc=(crc>>1)^(0xedb88320UL&(unsigned long)(-(long)(crc&1UL)));}
  return crc^0xffffffffUL;
}
static int path_of(char *out,size_t size,const char *root,const char *name)
{
  int n=snprintf(out,size,"%s/%s",root,name);
  return (n<0||(size_t)n>=(size_t)size)?-1:0;
}
static int lock_ledger(const char *root)
{
  char p[512];int fd;struct stat st;struct flock l;
  if(stat(root,&st)||!S_ISDIR(st.st_mode))return -1;
  if(path_of(p,sizeof(p),root,"task.lock"))return -1;
  fd=open(p,O_RDWR|O_CREAT,0600);
  if(fd<0)return -1;
  memset(&l,0,sizeof(l));l.l_type=F_WRLCK;l.l_whence=SEEK_SET;
  if(fcntl(fd,F_SETLK,&l)){close(fd);return -1;}
  return fd;
}
static int task_valid(const cJSON *t)
{
  static const char *const fields[]={"task_id","plan_id","tag_id","robot_id","plan_version","revision","state","vehicle_state","sequence","dispatch_id","stop_id","note"};
  if(!cJSON_IsObject(t)||duplicate_key(t)||keys_within(t,fields,12))return 0;
  if(!id_ok(text_of(t,"task_id"))||!id_ok(text_of(t,"plan_id"))||!id_ok(text_of(t,"tag_id")))return 0;
  if(robot_index(text_of(t,"robot_id"))<0)return 0;
  if(!one_of(text_of(t,"state"),states,STATE_COUNT))return 0;
  if(!cJSON_IsString(get(t,"vehicle_state"))||!cJSON_IsString(get(t,"dispatch_id"))||
     !cJSON_IsString(get(t,"stop_id"))||!cJSON_IsString(get(t,"note")))return 0;
  if(number_of(t,"plan_version",1,INT_MAX,NULL)||number_of(t,"revision",1,INT_MAX,NULL)||
     number_of(t,"sequence",0,INT_MAX,NULL))return 0;
  return 1;
}
static int command_valid(const cJSON *c)
{
  static const char *const fields[]={"command_id","kind","request_crc","result"};
  if(!cJSON_IsObject(c)||duplicate_key(c)||keys_within(c,fields,4))return 0;
  if(!id_ok(text_of(c,"command_id"))||!cJSON_IsString(get(c,"kind"))||
     !cJSON_IsString(get(c,"request_crc"))||!cJSON_IsString(get(c,"result")))return 0;
  return 1;
}
static int new_ledger(cJSON **out)
{
  cJSON *doc=cJSON_CreateObject(),*tasks=cJSON_CreateArray(),*cmds=cJSON_CreateArray();
  if(!doc||!tasks||!cmds){cJSON_Delete(doc);cJSON_Delete(tasks);cJSON_Delete(cmds);return -1;}
  if(!cJSON_AddNumberToObject(doc,"schema",1)||!cJSON_AddStringToObject(doc,"crc32","00000000")||
     !cJSON_AddStringToObject(doc,"plan_id","-")||!cJSON_AddNumberToObject(doc,"plan_version",0)||
     !cJSON_AddItemToObject(doc,"tasks",tasks)){
    cJSON_Delete(tasks);cJSON_Delete(cmds);cJSON_Delete(doc);return -1;}
  tasks=NULL; /* ownership moved to doc */
  if(!cJSON_AddItemToObject(doc,"commands",cmds)){
    cJSON_Delete(cmds);cJSON_Delete(doc);return -1;}
  *out=doc;return 0;
}
static cJSON *load(const char *root)
{
  char p[512],*buf=NULL;int fd;ssize_t n;cJSON *doc=NULL,*tasks,*cmds,*rows,*c;
  const char *sum;
  if(path_of(p,sizeof(p),root,"tasks.json"))return NULL;
  fd=open(p,O_RDONLY);
  if(fd<0){
    if(errno!=ENOENT)return NULL;
    return new_ledger(&doc)?NULL:doc;
  }
  buf=malloc(SP_TASK_SNAPSHOT_MAX+1);
  if(!buf){close(fd);return NULL;}
  n=read(fd,buf,SP_TASK_SNAPSHOT_MAX+1);close(fd);
  if(n<=0||n>(ssize_t)SP_TASK_SNAPSHOT_MAX){free(buf);return NULL;}
  buf[n]=0;
  if(memchr(buf,0,(size_t)n)||!sp_json_bounded(buf)){free(buf);return NULL;}
  doc=cJSON_Parse(buf);
  free(buf);
  if(!doc)return NULL;
  tasks=get(doc,"tasks");cmds=get(doc,"commands");sum=text_of(doc,"crc32");
  if(!cJSON_IsNumber(get(doc,"schema"))||get(doc,"schema")->valueint!=1)goto bad;
  if(!cJSON_IsString(get(doc,"plan_id"))||!sum)goto bad;
  if(number_of(doc,"plan_version",0,INT_MAX,NULL))goto bad;
  if(!cJSON_IsArray(tasks)||cJSON_GetArraySize(tasks)>SP_TASK_CAPACITY)goto bad;
  if(!cJSON_IsArray(cmds)||cJSON_GetArraySize(cmds)>COMMAND_KEEP)goto bad;
  {
    char *rows_text=cJSON_PrintUnformatted(tasks);char digest[9];
    if(!rows_text)goto bad;
    snprintf(digest,sizeof(digest),"%08lx",crc_of(rows_text));
    cJSON_free(rows_text);
    if(strcmp(digest,sum))goto bad;
  }
  {
    int seen=0;
    cJSON_ArrayForEach(rows,tasks){
      cJSON *prev;if(!task_valid(rows))goto bad;
      cJSON_ArrayForEach(prev,tasks){
        if(prev==rows)break;
        if(!strcmp(text_of(prev,"task_id"),text_of(rows,"task_id")))goto bad;}
      seen++;
    }
    if(seen>SP_TASK_CAPACITY)goto bad;
  }
  cJSON_ArrayForEach(c,cmds)if(!command_valid(c))goto bad;
  return doc;
bad:
  cJSON_Delete(doc);return NULL;
}
static int write_all(int fd,const char *data,size_t len)
{
  while(len){ssize_t w=write(fd,data,len);
    if(w<0){if(errno==EINTR)continue;return -1;}
    if(w==0)return -1;
    data+=w;len-=(size_t)w;}
  return 0;
}
static int save(const char *root,cJSON *doc)
{
  char p[512],tmp[512]={0},digest[9],*rows_text=NULL,*body=NULL;int fd=-1,ret=3;
  size_t len;
  rows_text=cJSON_PrintUnformatted(get(doc,"tasks"));
  if(!rows_text)return 3;
  snprintf(digest,sizeof(digest),"%08lx",crc_of(rows_text));
  cJSON_free(rows_text);
  cJSON_DeleteItemFromObjectCaseSensitive(doc,"crc32");
  if(!cJSON_AddStringToObject(doc,"crc32",digest))return 3;
  body=cJSON_PrintUnformatted(doc);
  if(!body)return 3;
  if(strlen(body)>(size_t)SP_TASK_SNAPSHOT_MAX)goto done;
  if(path_of(p,sizeof(p),root,"tasks.json")||path_of(tmp,sizeof(tmp),root,"tasks.tmp"))goto done;
  fd=open(tmp,O_WRONLY|O_CREAT|O_TRUNC,0600);
  if(fd<0)goto done;
  len=strlen(body);
  if(write_all(fd,body,len)||fsync(fd))goto done;
  if(close(fd)){fd=-1;goto done;}
  fd=-1;
  if(rename(tmp,p))goto done;
  ret=0;
done:
  if(fd>=0)close(fd);
  if(ret&&tmp[0])unlink(tmp);
  cJSON_free(body);
  return ret;
}
static int finish(cJSON *o,char **reply,int code)
{
  char *s;
  if(!o)return 3;
  s=cJSON_PrintUnformatted(o);
  cJSON_Delete(o);
  if(!s)return 3;
  if(reply)*reply=s;else cJSON_free(s);
  return code;
}
static cJSON *brief(const cJSON *t)
{
  cJSON *o=cJSON_CreateObject();
  if(!o)return NULL;
  if(!cJSON_AddStringToObject(o,"task_id",text_of(t,"task_id"))||
     !cJSON_AddStringToObject(o,"tag_id",text_of(t,"tag_id"))||
     !cJSON_AddStringToObject(o,"robot_id",text_of(t,"robot_id"))||
     !cJSON_AddNumberToObject(o,"revision",(double)get(t,"revision")->valueint)||
     !cJSON_AddStringToObject(o,"state",text_of(t,"state"))||
     !cJSON_AddStringToObject(o,"note",text_of(t,"note"))){cJSON_Delete(o);return NULL;}
  return o;
}
static cJSON *brief_all(const cJSON *tasks)
{
  cJSON *out=cJSON_CreateArray(),*row;const cJSON *t;
  if(!out)return NULL;
  cJSON_ArrayForEach(t,tasks){
    row=brief(t);
    if(!row||!cJSON_AddItemToArray(out,row)){cJSON_Delete(row);cJSON_Delete(out);return NULL;}
  }
  return out;
}
static cJSON *find_task(cJSON *tasks,const char *task_id)
{
  cJSON *t;
  cJSON_ArrayForEach(t,tasks)
    if(!strcmp(text_of(t,"task_id"),task_id))return t;
  return NULL;
}
static cJSON *find_command(cJSON *commands,const char *command_id)
{
  cJSON *c;
  cJSON_ArrayForEach(c,commands)
    if(!strcmp(text_of(c,"command_id"),command_id))return c;
  return NULL;
}
/* Deterministic command identity: a retry with different content must be
   rejected instead of silently overwriting the journal. */
static int command_note(cJSON *doc,const char *command_id,const char *kind,const char *request,const char *result)
{
  cJSON *commands=get(doc,"commands"),*existing,*entry;char digest[9];
  if(!commands)return -1;
  snprintf(digest,sizeof(digest),"%08lx",crc_of(request));
  existing=find_command(commands,command_id);
  if(existing){
    if(strcmp(text_of(existing,"request_crc"),digest))return -1;
    cJSON_DeleteItemFromObjectCaseSensitive(existing,"result");
    return cJSON_AddStringToObject(existing,"result",result)?0:-1;
  }
  entry=cJSON_CreateObject();
  if(!entry)return -1;
  if(!cJSON_AddStringToObject(entry,"command_id",command_id)||!cJSON_AddStringToObject(entry,"kind",kind)||
     !cJSON_AddStringToObject(entry,"request_crc",digest)||!cJSON_AddStringToObject(entry,"result",result)||
     !cJSON_AddItemToArray(commands,entry)){cJSON_Delete(entry);return -1;}
  if(cJSON_GetArraySize(commands)>COMMAND_KEEP)cJSON_DeleteItemFromArray(commands,0);
  return 0;
}

/* ---------- plan ---------- */
static int auto_assign(struct plan_task *plan,int count,const cJSON *existing)
{
  sp_problem p;sp_allocation a;char pool[SP_MAX_ROBOTS][8];char free_robots[SP_MAX_ROBOTS][8];
  int pool_n=0,free_n=0,auto_n=0,auto_idx[SP_TASK_CAPACITY],i,k,used=0;
  memset(&p,0,sizeof(p));
  /* Simulation candidate set is always the three configured vehicles;
     explicit assignments consume slots, they do not define the whole pool. */
  snprintf(pool[0],sizeof(pool[0]),"S1");snprintf(pool[1],sizeof(pool[1]),"S2");
  snprintf(pool[2],sizeof(pool[2]),"S3");pool_n=3;
  for(i=0;i<count;i++)if(!strcmp(plan[i].robot,"AUTO"))auto_idx[auto_n++]=i;
  if(!auto_n)return 0;
  if(auto_n>SP_MAX_TAGS)return -1;
  for(k=0;k<pool_n;k++){
    int taken=0;const cJSON *row;
    for(i=0;i<count;i++)if(!strcmp(plan[i].robot,pool[k]))taken=1;
    /* Existing pending or in-flight ownership also consumes a robot. */
    cJSON_ArrayForEach(row,existing){
      const char *robot=text_of(row,"robot_id"),*state=text_of(row,"state");
      if(robot&&state&&!strcmp(robot,pool[k])&&!is_terminal(state))taken=1;
    }
    if(!taken)memcpy(free_robots[free_n++],pool[k],sizeof(free_robots[0]));
  }
  if(auto_n>free_n)return -1;
  p.tags=auto_n;p.robots=free_n;
  for(i=0;i<auto_n;i++){
    p.priority[i]=(int)plan[auto_idx[i]].priority;
    for(k=0;k<free_n;k++){
      p.eligible[i*SP_MAX_ROBOTS+k]=1;p.energy[i*SP_MAX_ROBOTS+k]=1;p.cost[i*SP_MAX_ROBOTS+k]=1;
    }
  }
  for(k=0;k<free_n;k++)p.budget[k]=1;
  if(sp_allocate(&p,&a)||a.uncovered_priority)return -1;
  for(i=0;i<auto_n;i++){
    if(a.owner[i]<0||a.owner[i]>=free_n)return -1;
    snprintf(plan[auto_idx[i]].robot,sizeof(plan[auto_idx[i]].robot),"%s",free_robots[a.owner[i]]);
    used++;
  }
  return used==auto_n?0:-1;
}
int sp_task_plan_apply(const char *root,const char *json,char **reply)
{
  static const char *const plan_keys[]={"schema","plan_id","version","tasks"};
  static const char *const task_keys[]={"task_id","tag_id","robot_id","revision","priority"};
  struct plan_task *plan=NULL;int count=0,i,ret=3,fd=-1,status_bad=0,invalid=0;
  cJSON *doc=NULL,*tasks=NULL,*ledger=NULL,*rows=NULL,*o=NULL;
  const char *plan_id,*status="REJECTED";char *plan_body=NULL;long version=0,stored=0;
#define REJECT do{invalid=1;goto done;}while(0)
  if(reply)*reply=NULL;
  if(!json||strlen(json)>8192||!sp_json_bounded(json))return 2;
  doc=cJSON_Parse(json);
  if(!doc||duplicate_key(doc)||keys_within(doc,plan_keys,4))REJECT;
  plan_body=cJSON_PrintUnformatted(doc);if(!plan_body)goto done;
  if(!cJSON_IsString(get(doc,"schema"))||strcmp(get(doc,"schema")->valuestring,"spine-plan-v1"))REJECT;
  plan_id=text_of(doc,"plan_id");
  if(!id_ok(plan_id)||number_of(doc,"version",1,INT_MAX,&version))REJECT;
  tasks=get(doc,"tasks");
  if(!cJSON_IsArray(tasks))REJECT;
  count=cJSON_GetArraySize(tasks);
  if(count<1||count>SP_TASK_CAPACITY)REJECT;
  plan=calloc((size_t)count,sizeof(*plan));
  if(!plan)goto done;
  for(i=0;i<count;i++){
    cJSON *item=cJSON_GetArrayItem(tasks,i);const char *tid,*tag,*robot;long rev,prio=50;int j;
    char command_id[104];
    if(!cJSON_IsObject(item)||duplicate_key(item)||keys_within(item,task_keys,5))REJECT;
    tid=text_of(item,"task_id");tag=text_of(item,"tag_id");robot=text_of(item,"robot_id");
    if(!id_ok(tid)||!id_ok(tag)||!robot)REJECT;
    if(strcmp(robot,"AUTO")&&robot_index(robot)<0)REJECT;
    if(number_of(item,"revision",1,INT_MAX,&rev))REJECT;
    /* Both generated protocol IDs must fit the same 64-byte identifier
       limit enforced by the simulator and persisted command ledger. */
    if(snprintf(command_id,sizeof(command_id),"assign-%s-%ld",tid,rev)<0 ||
       !id_ok(command_id))REJECT;
    if(get(item,"priority")&&number_of(item,"priority",1,1000,&prio))REJECT;
    snprintf(plan[i].task_id,sizeof(plan[i].task_id),"%s",tid);
    snprintf(plan[i].tag_id,sizeof(plan[i].tag_id),"%s",tag);
    snprintf(plan[i].robot,sizeof(plan[i].robot),"%s",robot);
    plan[i].revision=rev;plan[i].priority=prio;
    for(j=0;j<i;j++)
      if(!strcmp(plan[j].task_id,plan[i].task_id)||!strcmp(plan[j].tag_id,plan[i].tag_id))REJECT;
  }
  fd=lock_ledger(root);
  if(fd<0)goto done;
  ledger=load(root);
  if(!ledger)goto done;
  rows=get(ledger,"tasks");
  if(number_of(ledger,"plan_version",0,INT_MAX,&stored))goto done;
  if(version<stored){status="STALE_PLAN_REJECTED";status_bad=1;goto response;}
  if(version==stored){
    const char *prior=text_of(ledger,"plan_id");
    const char *prior_body=text_of(ledger,"plan_body");
    if(!prior||strcmp(prior,plan_id)||!prior_body||strcmp(prior_body,plan_body)){
      status="PLAN_VERSION_CONFLICT";status_bad=1;goto response;}
    status="DUPLICATE_PLAN";goto response;
  }
  if(auto_assign(plan,count,rows))REJECT;
  for(i=0;i<count;i++){
    int j;
    for(j=0;j<i;j++)if(!strcmp(plan[j].robot,plan[i].robot))REJECT;
  }
  for(i=0;i<count;i++){
    cJSON *row=find_task(rows,plan[i].task_id);
    if(!row)continue;
    if(!is_terminal(text_of(row,"state"))){status="DOUBLE_AUTHORIZATION_REJECTED";status_bad=1;goto response;}
    if(get(row,"revision")->valueint+1!=(int)plan[i].revision){status="REVISION_CONFLICT_REJECTED";status_bad=1;goto response;}
  }
  for(i=0;i<count;i++){
    cJSON *row=find_task(rows,plan[i].task_id);
    if(!row){
      if(plan[i].revision!=1){status="REVISION_CONFLICT_REJECTED";status_bad=1;goto response;}
      row=cJSON_CreateObject();
      if(!row)goto done;
      if(!cJSON_AddStringToObject(row,"task_id",plan[i].task_id)||
         !cJSON_AddItemToArray(rows,row)){cJSON_Delete(row);goto done;}
    }
    cJSON_DeleteItemFromObjectCaseSensitive(row,"plan_id");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"tag_id");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"robot_id");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"plan_version");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"revision");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"state");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"vehicle_state");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"sequence");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"dispatch_id");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"stop_id");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"note");
    {
      char dispatch_id[104];
      snprintf(dispatch_id,sizeof(dispatch_id),"assign-%s-%ld",plan[i].task_id,plan[i].revision);
      if(!cJSON_AddStringToObject(row,"plan_id",plan_id)||
         !cJSON_AddStringToObject(row,"tag_id",plan[i].tag_id)||
         !cJSON_AddStringToObject(row,"robot_id",plan[i].robot)||
         !cJSON_AddNumberToObject(row,"plan_version",(double)version)||
         !cJSON_AddNumberToObject(row,"revision",(double)plan[i].revision)||
         !cJSON_AddStringToObject(row,"state","PENDING")||
         !cJSON_AddStringToObject(row,"vehicle_state","")||
         !cJSON_AddNumberToObject(row,"sequence",0)||
         !cJSON_AddStringToObject(row,"dispatch_id",dispatch_id)||
         !cJSON_AddStringToObject(row,"stop_id","")||
         !cJSON_AddStringToObject(row,"note",""))goto done;
    }
  }
  cJSON_DeleteItemFromObjectCaseSensitive(ledger,"plan_id");
  cJSON_DeleteItemFromObjectCaseSensitive(ledger,"plan_version");
  cJSON_DeleteItemFromObjectCaseSensitive(ledger,"plan_body");
  if(!cJSON_AddStringToObject(ledger,"plan_id",plan_id)||
     !cJSON_AddStringToObject(ledger,"plan_body",plan_body)||
     !cJSON_AddNumberToObject(ledger,"plan_version",(double)version))goto done;
  if(save(root,ledger))goto done;
  status="PLAN_PERSISTED";
response:
  o=cJSON_CreateObject();
  if(!o)goto done;
  if(!cJSON_AddStringToObject(o,"status",status)||
     !cJSON_AddStringToObject(o,"plan_id",plan_id)||
     !cJSON_AddNumberToObject(o,"plan_version",(double)version)||
     !cJSON_AddNumberToObject(o,"previous_plan_version",(double)stored)||
     !cJSON_AddNumberToObject(o,"stored_plan_version",(double)(!strcmp(status,"PLAN_PERSISTED")?version:stored))||
     !cJSON_AddBoolToObject(o,"motion",0)||
     !cJSON_AddStringToObject(o,"ack_scope","LOCAL_STORAGE_ONLY")||
     !cJSON_AddItemToObject(o,"tasks",brief_all(rows))){
    cJSON_Delete(o);o=NULL;goto done;
  }
  ret=status_bad?2:0;
done:
  if(fd>=0)close(fd);
  if(!o&&invalid){
    o=cJSON_CreateObject();
    if(o&&cJSON_AddStringToObject(o,"status","REJECTED")&&
       cJSON_AddStringToObject(o,"stage","PLAN_VALIDATION")&&
       cJSON_AddBoolToObject(o,"motion",0))ret=finish(o,reply,2);
    else{cJSON_Delete(o);o=NULL;ret=3;}
  }else if(o)ret=finish(o,reply,ret);
  free(plan);cJSON_free(plan_body);cJSON_Delete(ledger);cJSON_Delete(doc);
  return ret;
}

/* ---------- shared command helpers ---------- */
static int request_body(char *out,size_t size,const struct dispatch_item *it,const char *action)
{
  int n;
  if(!strcmp(action,"STOP"))
    n=snprintf(out,size,"{\"schema\":\"spine-robot-sim-v1\",\"mode\":\"simulation\",\"command_id\":\"%s\","
      "\"robot_id\":\"%s\",\"task_id\":\"%s\",\"revision\":%ld,\"action\":\"STOP\"}",
      it->command_id,it->robot,it->task_id,it->revision);
  else
    n=snprintf(out,size,"{\"schema\":\"spine-robot-sim-v1\",\"mode\":\"simulation\",\"command_id\":\"%s\","
      "\"robot_id\":\"%s\",\"task_id\":\"%s\",\"revision\":%ld,\"action\":\"ASSIGN\",\"tag_id\":\"%s\"}",
      it->command_id,it->robot,it->task_id,it->revision,it->tag_id);
  return (n<0||(size_t)n>=(size_t)size)?-1:0;
}
/* Executor ACK is accepted only when it is scoped to executor storage and
   reports the exact (task, robot, revision) it was asked about. */
static int ack_state_is(const char *response,const struct dispatch_item *it,const char *want,long *sequence)
{
  cJSON *o,*t;int ok=-1;const char *st;long revision;
  o=cJSON_ParseWithOpts(response,NULL,1);
  if(!o)return -1;
  if(duplicate_key(o))goto done;
  t=get(o,"task");
  st=text_of(t,"state");
  if(!text_of(o,"schema")||strcmp(text_of(o,"schema"),"spine-robot-sim-v1")||
     !text_of(o,"command_id")||strcmp(text_of(o,"command_id"),it->command_id))goto done;
  if(!cJSON_IsTrue(get(o,"persisted"))||!cJSON_IsFalse(get(o,"motion")))goto done;
  if(!text_of(o,"ack_scope")||strcmp(text_of(o,"ack_scope"),"SIMULATOR_STORAGE_ONLY"))goto done;
  if(!cJSON_IsObject(t)||duplicate_key(t))goto done;
  if(!text_of(t,"task_id")||strcmp(text_of(t,"task_id"),it->task_id))goto done;
  if(!text_of(t,"robot_id")||strcmp(text_of(t,"robot_id"),it->robot))goto done;
  if(number_of(t,"revision",1,INT_MAX,&revision)||revision!=it->revision)goto done;
  if(!st||strcmp(st,want))goto done;
  if(sequence&&number_of(t,"sequence",1,INT_MAX,sequence))goto done;
  ok=0;
done:
  cJSON_Delete(o);
  return ok;
}
static int mark_dispatched(const char *root,const struct dispatch_item *it,const char *body)
{
  int fd=lock_ledger(root),ret=3;cJSON *ledger,*row;
  if(fd<0)return 3;
  ledger=load(root);
  if(!ledger){close(fd);return 3;}
  row=find_task(get(ledger,"tasks"),it->task_id);
  if(row&&text_of(row,"state")&&!strcmp(text_of(row,"state"),"PENDING")&&
     (long)get(row,"revision")->valueint==it->revision){
    cJSON_DeleteItemFromObjectCaseSensitive(row,"state");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"vehicle_state");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"note");
    if(!cJSON_AddStringToObject(row,"state","DISPATCHED")||
       !cJSON_AddStringToObject(row,"vehicle_state","ACCEPTED")||
       !cJSON_AddStringToObject(row,"note","")||
       command_note(ledger,it->command_id,"ASSIGN",body,"ACKNOWLEDGED"))goto done;
    if(save(root,ledger))goto done;
    ret=0;
  }
done:
  close(fd);cJSON_Delete(ledger);
  return ret;
}
static const char *outcome_name(int outcome)
{
  switch(outcome){
  case 1:return "DISPATCHED";
  case 2:return "HELD_BY_RISK";
  case 3:return "HELD_HUMAN_REVIEW";
  case 4:return "HELD_ROBOT_BUSY";
  case 5:return "UNREACHABLE";
  case 6:return "ACK_REJECTED";
  case 7:return "STORAGE_REJECTED";
  default:return "NOT_PROCESSED";
  }
}
/* A risk hold is persisted in the ledger note so that a later human CLOSE does
   not silently restore the old authorization: only a newer plan version
   rewrites the row (and therefore re-authorizes it). */
static int set_note(const char *root,const struct dispatch_item *it,const char *note,const char *state)
{
  int fd=lock_ledger(root),ret=3;cJSON *ledger,*row;
  if(fd<0)return 3;
  ledger=load(root);
  if(!ledger){close(fd);return 3;}
  row=find_task(get(ledger,"tasks"),it->task_id);
  if(row&&(long)get(row,"revision")->valueint==it->revision){
    cJSON_DeleteItemFromObjectCaseSensitive(row,"note");
    if(!cJSON_AddStringToObject(row,"note",note))goto done;
    if(state){
      cJSON_DeleteItemFromObjectCaseSensitive(row,"state");
      if(!cJSON_AddStringToObject(row,"state",state))goto done;
    }
    if(save(root,ledger))goto done;
    ret=0;
  }
done:
  close(fd);cJSON_Delete(ledger);
  return ret;
}

/* ---------- dispatch ---------- */
/* ---------- risk linkage: IMMEDIATE tags stop what is already running ------------- */
static int risk_linkage(const char *root,const char *endpoint,cJSON *stopped)
{
  char ids[SP_TASK_CAPACITY][64];int n=0,i,ret=0,fd,code;
  cJSON *ledger,*row;
  fd=lock_ledger(root);if(fd<0)return 3;
  ledger=load(root);if(!ledger){close(fd);return 3;}
  cJSON_ArrayForEach(row,get(ledger,"tasks")){
    const char *st=text_of(row,"state"),*tag=text_of(row,"tag_id");int level=0;
    if(!st||!tag)continue;
    if(strcmp(st,"DISPATCHED")&&strcmp(st,"RUNNING")&&strcmp(st,"BLOCKED"))continue;
    if(n>=SP_TASK_CAPACITY)break;
    if(sp_store_tag_risk(root,tag,&level)||level<2)continue;
    snprintf(ids[n],sizeof(ids[n]),"%s",text_of(row,"task_id"));n++;
  }
  close(fd);cJSON_Delete(ledger);
  for(i=0;i<n;i++){
    char *reply=NULL;
    if(sp_task_stop(root,ids[i],"RISK_LINKAGE",&reply)==3)ret=3;
    if(reply)cJSON_free(reply);
  }
  if(!n)return ret;
  {
    char *reply=NULL;cJSON *doc=NULL,*item;cJSON *tasks;
    code=sp_task_stop_sync(root,endpoint,&reply);
    if(code==3){if(reply)cJSON_free(reply);return 3;}
    if(code==4)ret=4;
    if(reply){
      doc=cJSON_Parse(reply);
      tasks=doc?get(doc,"tasks"):NULL;
      cJSON_ArrayForEach(item,tasks){
        cJSON *copy=cJSON_Duplicate(item,1);
        if(!copy||!cJSON_AddItemToArray(stopped,copy)){
          cJSON_Delete(copy);cJSON_Delete(doc);cJSON_free(reply);return 3;
        }
      }
      cJSON_Delete(doc);cJSON_free(reply);
    }
  }
  return ret;
}

int sp_task_dispatch(const char *root,const char *endpoint,char **reply)
{
  struct dispatch_item *items=NULL;unsigned char busy[SP_MAX_ROBOTS];int count=0,i,ret=0,net=0,local_error=0,fd=-1,code=0;
  cJSON *ledger=NULL,*rows=NULL,*o=NULL,*arr=NULL,*row,*stops=NULL;const char *status;
  if(reply)*reply=NULL;
  if(!sp_http_endpoint_valid(endpoint))return 2;
  items=calloc(SP_TASK_CAPACITY,sizeof(*items));
  if(!items)return 3;
  memset(busy,0,sizeof(busy));
  fd=lock_ledger(root);
  if(fd<0){free(items);return 3;}
  ledger=load(root);
  if(!ledger){close(fd);free(items);return 3;}
  rows=get(ledger,"tasks");
  cJSON_ArrayForEach(row,rows){
    const char *st=text_of(row,"state");int r=robot_index(text_of(row,"robot_id"));
    if(!st)continue;
    if(!strcmp(st,"PENDING")){
      if(count>=SP_TASK_CAPACITY)break;
      snprintf(items[count].task_id,sizeof(items[count].task_id),"%s",text_of(row,"task_id"));
      snprintf(items[count].tag_id,sizeof(items[count].tag_id),"%s",text_of(row,"tag_id"));
      snprintf(items[count].robot,sizeof(items[count].robot),"%s",text_of(row,"robot_id"));
      items[count].revision=(long)get(row,"revision")->valueint;
      snprintf(items[count].command_id,sizeof(items[count].command_id),"assign-%s-%ld",
               text_of(row,"task_id"),items[count].revision);
      {
        const char *nt=text_of(row,"note");
        snprintf(items[count].note,sizeof(items[count].note),"%s",nt?nt:"");
        items[count].frozen=!strncmp(items[count].note,"HELD_BY_RISK",12)||
                            !strncmp(items[count].note,"HELD_HUMAN_REVIEW",17);
      }
      items[count].outcome=0;
      count++;
    }else if(!is_terminal(st)&&r>=0)busy[r]=1;
  }
  close(fd);fd=-1;
  cJSON_Delete(ledger);ledger=NULL;
  for(i=0;i<count;i++){
    char body[512],resp[4096];int level=0,r=robot_index(items[i].robot);
    if(items[i].frozen){items[i].outcome=!strncmp(items[i].note,"HELD_BY_RISK",12)?2:3;continue;}
    if(sp_store_tag_risk(root,items[i].tag_id,&level)){items[i].outcome=7;local_error=1;continue;}
    if(level>0){
      if(set_note(root,&items[i],level==2?"HELD_BY_RISK":"HELD_HUMAN_REVIEW",NULL)){items[i].outcome=7;local_error=1;continue;}
      items[i].outcome=(level==2)?2:3;items[i].frozen=1;continue;
    }
    if(r>=0&&busy[r]){items[i].outcome=4;continue;}
    if(request_body(body,sizeof(body),&items[i],"ASSIGN")){items[i].outcome=7;local_error=1;continue;}
    if(sp_http_exchange(endpoint,"POST","/v1/commands",body,resp,sizeof(resp))){items[i].outcome=5;net=1;continue;}
    if(ack_state_is(resp,&items[i],"ACCEPTED",NULL)){items[i].outcome=6;net=1;continue;}
    if(mark_dispatched(root,&items[i],body)){items[i].outcome=7;local_error=1;continue;}
    items[i].outcome=1;
    if(r>=0)busy[r]=1;
  }
  o=cJSON_CreateObject();arr=cJSON_CreateArray();stops=cJSON_CreateArray();
  if(!o||!arr||!stops){cJSON_Delete(o);cJSON_Delete(arr);cJSON_Delete(stops);free(items);return 3;}
  code=risk_linkage(root,endpoint,stops);
  if(code==3){cJSON_Delete(o);cJSON_Delete(arr);cJSON_Delete(stops);free(items);return 3;}
  if(code==4)net=1;
  for(i=0;i<count;i++){
    cJSON *e=cJSON_CreateObject();
    if(!e||!cJSON_AddStringToObject(e,"task_id",items[i].task_id)||
       !cJSON_AddStringToObject(e,"robot_id",items[i].robot)||
       !cJSON_AddStringToObject(e,"status",outcome_name(items[i].outcome))||
       !cJSON_AddBoolToObject(e,"dispatched",items[i].outcome==1)||
       !cJSON_AddItemToArray(arr,e)){cJSON_Delete(e);cJSON_Delete(o);cJSON_Delete(arr);free(items);return 3;}
  }
  status=count?(local_error?"PARTIAL_STORAGE_ERROR":net?"PARTIAL_NETWORK_ERROR":"DISPATCH_STEP"):
         (cJSON_GetArraySize(stops)?"RISK_STOPPED":"NOTHING_TO_DISPATCH");
  if(!cJSON_AddStringToObject(o,"status",status)||
     !cJSON_AddStringToObject(o,"ack_scope","REMOTE_STORAGE_ONLY")||
     !cJSON_AddBoolToObject(o,"motion",0)||
     !cJSON_AddNumberToObject(o,"task_count",count)){
    cJSON_Delete(o);cJSON_Delete(arr);cJSON_Delete(stops);free(items);return 3;
  }
  if(!cJSON_AddItemToObject(o,"tasks",arr)){
    cJSON_Delete(o);cJSON_Delete(arr);cJSON_Delete(stops);free(items);return 3;
  }
  arr=NULL;
  if(!cJSON_AddItemToObject(o,"stops",stops)){
    cJSON_Delete(o);cJSON_Delete(stops);free(items);return 3;
  }
  stops=NULL;
  ret=local_error?3:net?4:0;
  free(items);
  return finish(o,reply,ret);
}

/* ---------- poll ---------- */
static const char *next_state(const char *local,const char *vehicle)
{
  if(!strcmp(local,"STOP_REQUESTED")){
    if(!strcmp(vehicle,"STOP_CONFIRMED"))return "STOP_CONFIRMED";
    if(!strcmp(vehicle,"COMPLETED")||!strcmp(vehicle,"FAILED"))return vehicle;
    return NULL;
  }
  return vehicle;
}
int sp_task_poll(const char *root,const char *endpoint,char **reply)
{
  static const char *const forward[]={"RUNNING","BLOCKED","COMPLETED","FAILED","STOP_CONFIRMED"};
  char resp[4096];cJSON *state_doc=NULL,*vehicles=NULL,*ledger=NULL,*rows=NULL,*o=NULL,*arr=NULL,*row;
  int fd=-1,ret=3,changed=0;
  if(reply)*reply=NULL;
  if(!sp_http_endpoint_valid(endpoint))return 2;
  if(sp_http_exchange(endpoint,"GET","/v1/state","",resp,sizeof(resp)))return 4;
  state_doc=cJSON_ParseWithOpts(resp,NULL,1);
  if(!cJSON_IsObject(state_doc)||duplicate_key(state_doc)||
     !text_of(state_doc,"schema")||strcmp(text_of(state_doc,"schema"),"spine-robot-sim-v1")||
     !text_of(state_doc,"source")||strcmp(text_of(state_doc,"source"),"PC_NETWORK_SIMULATOR")||
     !cJSON_IsFalse(get(state_doc,"motion"))){cJSON_Delete(state_doc);return 4;}
  vehicles=get(state_doc,"tasks");
  if(!cJSON_IsArray(vehicles)||cJSON_GetArraySize(vehicles)>SP_MAX_ROBOTS){cJSON_Delete(state_doc);return 4;}
  cJSON_ArrayForEach(row,vehicles){
    long rev,sequence;const char *robot=text_of(row,"robot_id");cJSON *prior;
    if(!cJSON_IsObject(row)||duplicate_key(row)||!id_ok(text_of(row,"task_id"))||
       !robot||robot_index(robot)<0||number_of(row,"revision",1,INT_MAX,&rev)||
       number_of(row,"sequence",0,INT_MAX,&sequence)||!text_of(row,"state")){
      cJSON_Delete(state_doc);return 4;
    }
    cJSON_ArrayForEach(prior,vehicles){
      if(prior==row)break;
      if(!strcmp(text_of(prior,"task_id"),text_of(row,"task_id"))||
         !strcmp(text_of(prior,"robot_id"),robot)){cJSON_Delete(state_doc);return 4;}
    }
  }
  fd=lock_ledger(root);
  if(fd<0){cJSON_Delete(state_doc);return 3;}
  ledger=load(root);
  if(!ledger){close(fd);cJSON_Delete(state_doc);return 3;}
  rows=get(ledger,"tasks");
  o=cJSON_CreateObject();arr=cJSON_CreateArray();
  if(!o||!arr)goto done;
  cJSON_ArrayForEach(row,rows){
    const char *st=text_of(row,"state"),*robot=text_of(row,"robot_id"),*vst=NULL,*note=NULL,*moved=NULL;
    cJSON *vehicle=NULL,*v;cJSON *e;long lseq,seq_num=0;
    if(!st||!strcmp(st,"PENDING")||is_terminal(st))continue;
    lseq=(long)get(row,"sequence")->valueint;
    cJSON_ArrayForEach(v,vehicles)
      if(text_of(v,"task_id")&&!strcmp(text_of(v,"task_id"),text_of(row,"task_id"))){vehicle=v;break;}
    if(!vehicle){note="VEHICLE_UNKNOWN";}
    else if(!text_of(vehicle,"robot_id")||strcmp(text_of(vehicle,"robot_id"),robot)||
            !cJSON_IsNumber(get(vehicle,"revision"))||
            (long)get(vehicle,"revision")->valueint!=(long)get(row,"revision")->valueint){note="VEHICLE_STATE_CONFLICT";}
    else{
      vst=text_of(vehicle,"state");
      if(!cJSON_IsNumber(get(vehicle,"sequence")))note="REPORT_MISSING_SEQUENCE";
      else{
        seq_num=(long)get(vehicle,"sequence")->valueint;
        if(seq_num<lseq)note="STALE_PROGRESS_IGNORED";
        else if(seq_num==lseq)note="DUPLICATE_REPORT";
        else if(!vst||!one_of(vst,forward,5))note="UNSUPPORTED_STATE";
        else{
          moved=next_state(st,vst);
          note=moved?"REPORT_APPLIED":"STOP_PENDING_EXECUTOR";
          if(moved){
            cJSON_DeleteItemFromObjectCaseSensitive(row,"state");
            cJSON_DeleteItemFromObjectCaseSensitive(row,"vehicle_state");
            cJSON_DeleteItemFromObjectCaseSensitive(row,"sequence");
            cJSON_DeleteItemFromObjectCaseSensitive(row,"note");
            if(!cJSON_AddStringToObject(row,"state",moved)||
               !cJSON_AddStringToObject(row,"vehicle_state",vst)||
               !cJSON_AddNumberToObject(row,"sequence",(double)seq_num)||
               !cJSON_AddStringToObject(row,"note",note))goto done;
          }else{
            cJSON_DeleteItemFromObjectCaseSensitive(row,"vehicle_state");
            if(!cJSON_AddStringToObject(row,"vehicle_state",vst))goto done;
          }
          changed=1;
        }
      }
    }
    if(!vst)vst="";
    if(!note)note="";
    e=cJSON_CreateObject();
    if(!e||!cJSON_AddStringToObject(e,"task_id",text_of(row,"task_id"))||
       !cJSON_AddStringToObject(e,"local_state",text_of(row,"state"))||
       !cJSON_AddStringToObject(e,"vehicle_state",vst)||
       !cJSON_AddNumberToObject(e,"sequence",(double)get(row,"sequence")->valueint)||
       !cJSON_AddStringToObject(e,"note",note)||
       !cJSON_AddItemToArray(arr,e)){cJSON_Delete(e);goto done;}
  }
  if(changed&&save(root,ledger))goto done;
  if(!cJSON_AddStringToObject(o,"status","POLLED")||
     !cJSON_AddStringToObject(o,"ack_scope","REMOTE_STORAGE_ONLY")||
     !cJSON_AddBoolToObject(o,"motion",0)||
     !cJSON_AddItemToObject(o,"tasks",arr))goto done;
  arr=NULL;
  ret=finish(o,reply,0);o=NULL;
done:
  if(fd>=0)close(fd);
  cJSON_Delete(o);cJSON_Delete(arr);cJSON_Delete(ledger);cJSON_Delete(state_doc);
  return ret;
}

/* ---------- stop ---------- */
int sp_task_stop(const char *root,const char *task_id,const char *reason,char **reply)
{
  int fd=-1,ret=3;cJSON *ledger=NULL,*row=NULL,*o=NULL;const char *status="TASK_NOT_FOUND";
  int released=0,confirmed=0;
  if(reply)*reply=NULL;
  if(!id_ok(task_id))return 2;
  if(reason&&strlen(reason)>160)return 2;
  fd=lock_ledger(root);
  if(fd<0)return 3;
  ledger=load(root);
  if(!ledger){close(fd);return 3;}
  row=find_task(get(ledger,"tasks"),task_id);
  if(row){
    const char *st=text_of(row,"state");
    if(!st)goto done;
    if(is_terminal(st)){
      status="STOP_NOT_REQUIRED";released=!strcmp(st,"CANCELLED")||!strcmp(st,"STOP_CONFIRMED");ret=0;
    }else if(!strcmp(st,"STOP_REQUESTED")){
      status="ALREADY_REQUESTED";ret=0;
    }else if(!strcmp(st,"PENDING")){
      status="CANCELLED";
      cJSON_DeleteItemFromObjectCaseSensitive(row,"state");
      cJSON_DeleteItemFromObjectCaseSensitive(row,"note");
      if(!cJSON_AddStringToObject(row,"state","CANCELLED")||
         !cJSON_AddStringToObject(row,"note","NOT_DISPATCHED"))goto done;
      if(save(root,ledger))goto done;
      released=1;ret=0;
    }else{
      char stop_id[104];
      snprintf(stop_id,sizeof(stop_id),"stop-%s-%ld",task_id,(long)get(row,"revision")->valueint);
      status="STOP_REQUESTED";
      cJSON_DeleteItemFromObjectCaseSensitive(row,"state");
      cJSON_DeleteItemFromObjectCaseSensitive(row,"stop_id");
      cJSON_DeleteItemFromObjectCaseSensitive(row,"note");
      if(!cJSON_AddStringToObject(row,"state","STOP_REQUESTED")||
         !cJSON_AddStringToObject(row,"stop_id",stop_id)||
         !cJSON_AddStringToObject(row,"note",(reason&&*reason)?reason:"RISK_LINKAGE"))goto done;
      if(save(root,ledger))goto done;
      ret=0;
    }
  }
done:
  if(fd>=0)close(fd);
  if(ledger&&!row){
    o=cJSON_CreateObject();
    if(o&&cJSON_AddStringToObject(o,"status","TASK_NOT_FOUND")&&
       cJSON_AddStringToObject(o,"task_id",task_id)&&
       cJSON_AddBoolToObject(o,"motion",0))ret=finish(o,reply,2);
    else {cJSON_Delete(o);ret=3;}
  }
  if(ledger&&row){
    o=cJSON_CreateObject();
    if(!o){cJSON_Delete(ledger);return 3;}
    if(!cJSON_AddStringToObject(o,"status",status)||
       !cJSON_AddStringToObject(o,"task_id",task_id)||
       !cJSON_AddStringToObject(o,"robot_id",text_of(row,"robot_id"))||
       !cJSON_AddStringToObject(o,"task_state",text_of(row,"state"))||
       !cJSON_AddBoolToObject(o,"executor_confirmed",confirmed)||
       !cJSON_AddBoolToObject(o,"robot_released",released)||
       !cJSON_AddBoolToObject(o,"motion",0)){cJSON_Delete(o);o=NULL;ret=3;}
    else ret=finish(o,reply,ret);
  }
  cJSON_Delete(ledger);
  return ret;
}
static int mark_stop_confirmed(const char *root,const struct dispatch_item *it,const char *body,long seq)
{
  int fd=lock_ledger(root),ret=3;cJSON *ledger,*row;
  if(fd<0)return 3;
  ledger=load(root);
  if(!ledger){close(fd);return 3;}
  row=find_task(get(ledger,"tasks"),it->task_id);
  if(row&&text_of(row,"state")&&!strcmp(text_of(row,"state"),"STOP_REQUESTED")&&
     seq>(long)get(row,"sequence")->valueint){
    cJSON_DeleteItemFromObjectCaseSensitive(row,"state");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"vehicle_state");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"sequence");
    cJSON_DeleteItemFromObjectCaseSensitive(row,"note");
    if(!cJSON_AddStringToObject(row,"state","STOP_CONFIRMED")||
       !cJSON_AddStringToObject(row,"vehicle_state","STOP_CONFIRMED")||
       !cJSON_AddNumberToObject(row,"sequence",(double)seq)||
       !cJSON_AddStringToObject(row,"note","EXECUTOR_CONFIRMED_STOP")||
       command_note(ledger,it->command_id,"STOP",body,"ACKNOWLEDGED"))goto done;
    if(save(root,ledger))goto done;
    ret=0;
  }
done:
  close(fd);cJSON_Delete(ledger);
  return ret;
}
int sp_task_stop_sync(const char *root,const char *endpoint,char **reply)
{
  struct dispatch_item *items=NULL;int count=0,i,ret=0,net=0,invalid_ack=0,local_error=0,fd=-1;
  cJSON *ledger=NULL,*rows=NULL,*o=NULL,*arr=NULL,*row;
  if(reply)*reply=NULL;
  if(!sp_http_endpoint_valid(endpoint))return 2;
  items=calloc(SP_TASK_CAPACITY,sizeof(*items));
  if(!items)return 3;
  fd=lock_ledger(root);
  if(fd<0){free(items);return 3;}
  ledger=load(root);
  if(!ledger){close(fd);free(items);return 3;}
  rows=get(ledger,"tasks");
  cJSON_ArrayForEach(row,rows){
    const char *st=text_of(row,"state");
    if(!st||strcmp(st,"STOP_REQUESTED"))continue;
    if(count>=SP_TASK_CAPACITY)break;
    snprintf(items[count].task_id,sizeof(items[count].task_id),"%s",text_of(row,"task_id"));
    snprintf(items[count].robot,sizeof(items[count].robot),"%s",text_of(row,"robot_id"));
    snprintf(items[count].command_id,sizeof(items[count].command_id),"%s",text_of(row,"stop_id"));
    items[count].revision=(long)get(row,"revision")->valueint;
    items[count].sequence=(long)get(row,"sequence")->valueint;
    count++;
  }
  close(fd);fd=-1;cJSON_Delete(ledger);ledger=NULL;
  for(i=0;i<count;i++){
    char body[512],resp[4096];long seq=0;
    if(!id_ok(items[i].command_id)){items[i].outcome=7;local_error=1;continue;}
    if(request_body(body,sizeof(body),&items[i],"STOP")){items[i].outcome=7;local_error=1;continue;}
    if(sp_http_exchange(endpoint,"POST","/v1/commands",body,resp,sizeof(resp))){items[i].outcome=5;net=1;continue;}
    if(ack_state_is(resp,&items[i],"STOP_CONFIRMED",&seq)){items[i].outcome=6;invalid_ack=1;continue;}
    if(seq<=items[i].sequence){items[i].outcome=6;invalid_ack=1;continue;}
    if(mark_stop_confirmed(root,&items[i],body,seq)){items[i].outcome=7;local_error=1;continue;}
    items[i].outcome=1;
  }
  o=cJSON_CreateObject();arr=cJSON_CreateArray();
  if(!o||!arr){cJSON_Delete(o);cJSON_Delete(arr);free(items);return 3;}
  for(i=0;i<count;i++){
    const char *name=!items[i].outcome?"PENDING":items[i].outcome==1?"STOP_CONFIRMED":outcome_name(items[i].outcome);
    cJSON *e=cJSON_CreateObject();
    if(!e||!cJSON_AddStringToObject(e,"task_id",items[i].task_id)||
       !cJSON_AddStringToObject(e,"status",name)||
       !cJSON_AddBoolToObject(e,"executor_confirmed",items[i].outcome==1)||
       !cJSON_AddItemToArray(arr,e)){cJSON_Delete(e);cJSON_Delete(o);cJSON_Delete(arr);free(items);return 3;}
  }
  if(!cJSON_AddStringToObject(o,"status",count?(local_error?"PARTIAL_STORAGE_ERROR":
       (net||invalid_ack)?"PARTIAL_NETWORK_ERROR":"STOP_SYNC_STEP"):"NOTHING_TO_SYNC")||
     !cJSON_AddBoolToObject(o,"motion",0)||
     !cJSON_AddItemToObject(o,"tasks",arr)){
    cJSON_Delete(o);cJSON_Delete(arr);free(items);return 3;
  }
  ret=local_error?3:(net||invalid_ack)?4:0;
  free(items);
  return finish(o,reply,ret);
}

/* ---------- view ---------- */
int sp_task_view(const char *root,const char *task_id,char **reply)
{
  int fd=-1,ret=0;cJSON *ledger=NULL,*rows=NULL,*o=NULL,*arr=NULL,*row;int found=0;
  if(reply)*reply=NULL;
  if(task_id&&!id_ok(task_id))return 2;
  fd=lock_ledger(root);
  if(fd<0)return 3;
  ledger=load(root);
  if(!ledger){close(fd);return 3;}
  rows=get(ledger,"tasks");
  arr=cJSON_CreateArray();
  o=cJSON_CreateObject();
  if(!arr||!o)goto done;
  cJSON_ArrayForEach(row,rows){
    cJSON *b;
    if(task_id&&strcmp(text_of(row,"task_id"),task_id))continue;
    found=1;
    b=brief(row);
    if(!b||!cJSON_AddItemToArray(arr,b)){cJSON_Delete(b);goto done;}
  }
  if(task_id&&!found){ret=2;
    if(!cJSON_AddStringToObject(o,"status","TASK_NOT_FOUND"))goto done;
  }else if(!cJSON_AddStringToObject(o,"status",task_id?"TASK_VIEW":"TASK_LIST"))goto done;
  if(!cJSON_AddStringToObject(o,"plan_id",text_of(ledger,"plan_id"))||
     !cJSON_AddNumberToObject(o,"plan_version",(double)get(ledger,"plan_version")->valueint)||
     !cJSON_AddBoolToObject(o,"motion",0)||
     !cJSON_AddStringToObject(o,"ack_scope","LOCAL_STORAGE_ONLY")||
     !cJSON_AddItemToObject(o,"tasks",arr))goto done;
  arr=NULL;
  ret=finish(o,reply,ret);o=NULL;
done:
  if(fd>=0)close(fd);
  cJSON_Delete(o);cJSON_Delete(arr);cJSON_Delete(ledger);
  return o?3:ret;
}
