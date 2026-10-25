#include "ingress.h"
#include "cJSON.h"
#include <stdio.h>
#include <string.h>
#include <math.h>

int sp_json_bounded(const char *s)
{
  int depth=0,quoted=0,escape=0;
  for(;*s;s++) {
    if(quoted) {
      if(escape) escape=0;
      else if(*s=='\\') escape=1;
      else if(*s=='"') quoted=0;
    } else if(*s=='"') quoted=1;
    else if(*s=='{'||*s=='[') { if(++depth>16) return 0; }
    else if(*s=='}'||*s==']') { if(--depth<0) return 0; }
  }
  return !quoted && depth==0;
}

static int keys(const cJSON *obj, const char *const *allowed, int count)
{
  const cJSON *item, *prior;
  if (!cJSON_IsObject(obj)) return 0;
  cJSON_ArrayForEach(item,obj) {
    int i;
    if (!item->string) return 0;
    for(i=0;i<count;i++) if(!strcmp(item->string,allowed[i])) break;
    if(i==count) return 0;
    for(prior=obj->child;prior!=item;prior=prior->next)
      if(!strcmp(prior->string,item->string)) return 0;
  }
  return 1;
}
static const cJSON *field(const cJSON *o,const char *k)
{ return cJSON_GetObjectItemCaseSensitive(o,k); }
static int number(const cJSON *o,int lo,int hi,int *n)
{
  if(!cJSON_IsNumber(o) || !isfinite(o->valuedouble) ||
     o->valuedouble<lo || o->valuedouble>hi ||
     o->valuedouble!=(double)(int)o->valuedouble) return 0;
  *n=(int)o->valuedouble; return 1;
}
static int id(const cJSON *v)
{
  const unsigned char *s;
  if(!cJSON_IsString(v) || !v->valuestring[0] || strlen(v->valuestring)>64) return 0;
  for(s=(const unsigned char *)v->valuestring;*s;s++)
    if(!((*s>='a'&&*s<='z')||(*s>='A'&&*s<='Z')||
         (*s>='0'&&*s<='9')||*s=='_'||*s=='-'||*s=='.')) return 0;
  return 1;
}
int sp_decode_event(const char *json,int threshold,char **event,char **assessment)
{
  static const char *const names[]={"event_id","robot_id","tag_id","revision","policy_version","mode","fresh","factors"};
  static const char *const factors[]={"consequence","urgency","exposure","spread"};
  static const char *const decisions[]={"AUTO","HUMAN_REVIEW","IMMEDIATE_HUMAN"};
  cJSON *o=NULL,*out=NULL; const cJSON *f,*v; char *text=NULL,*canonical=NULL;
  sp_event e; sp_assessment a; int rev,i,levels[4],ret=2;
  if(!event || !assessment) return 2;
  *event=NULL;*assessment=NULL;
  if(!json || strlen(json)>4096 || strstr(json,"\\u0000") ||
     !sp_json_bounded(json) || threshold<0 || threshold>100) goto done;
  o=cJSON_ParseWithOpts(json,NULL,1);
  if(!o || !keys(o,names,8)) goto done;
  for(i=0;i<3;i++) if(!id(field(o,names[i]))) goto done;
  v=field(o,"policy_version");
  if(!cJSON_IsString(v)||strcmp(v->valuestring,"spine-v2")) goto done;
  v=field(o,"mode");
  if(!cJSON_IsString(v)||strcmp(v->valuestring,"replay")) goto done;
  if(!number(field(o,"revision"),1,2147483647,&rev)) goto done;
  v=field(o,"fresh"); if(!cJSON_IsBool(v)) goto done;
  e.fresh=cJSON_IsTrue(v);
  f=field(o,"factors"); if(!keys(f,factors,4)) goto done;
  for(i=0;i<4;i++) {
    v=field(f,factors[i]); levels[i]=-1;
    if(v && !number(v,-1,5,&levels[i])) goto done;
  }
  e.consequence=levels[0];e.urgency=levels[1];e.exposure=levels[2];e.spread=levels[3];
  if(sp_assess(&e,threshold,&a)) goto done;
  out=cJSON_CreateObject(); if(!out) goto done;
  for(i=0;i<3;i++) if(!cJSON_AddStringToObject(out,names[i],field(o,names[i])->valuestring)) goto done;
  if(!cJSON_AddNumberToObject(out,"revision",rev)||
     !cJSON_AddStringToObject(out,"source","REPLAY_UNAUTHENTICATED")||
     !cJSON_AddStringToObject(out,"status","VALIDATED_ONLY")||
     !cJSON_AddNumberToObject(out,"score",a.score)||
     !cJSON_AddNumberToObject(out,"unknown_mask",a.unknown_mask)||
     !cJSON_AddStringToObject(out,"decision",decisions[a.decision])||
     !cJSON_AddBoolToObject(out,"motion",0)||
     !cJSON_AddBoolToObject(out,"durable_ack",0)) goto done;
  text=cJSON_PrintUnformatted(out); if(!text) goto done;
  canonical=cJSON_PrintUnformatted(o); if(!canonical) goto done;
  *event=canonical;*assessment=text;canonical=NULL;text=NULL;ret=0;
done:
  cJSON_free(canonical);cJSON_free(text);cJSON_Delete(out);cJSON_Delete(o);
  return ret;
}

int sp_ingest_json(const char *json,int threshold)
{
  char *event=NULL,*assessment=NULL;
  int ret=sp_decode_event(json,threshold,&event,&assessment);
  if(!ret) puts(assessment); else fputs("event rejected\n",stderr);
  cJSON_free(event);cJSON_free(assessment);return ret;
}
