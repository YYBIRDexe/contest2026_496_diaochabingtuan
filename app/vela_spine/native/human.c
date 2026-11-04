#include "human.h"
#include "ingress.h"
#include "store.h"
#include "transport.h"
#include <mbedtls/md.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

static cJSON *get(const cJSON *o,const char *name)
{ return cJSON_GetObjectItemCaseSensitive(o,name); }
static int identifier(const cJSON *v,size_t limit)
{
  const char *s;
  if(!cJSON_IsString(v)||!v->valuestring[0]||strlen(v->valuestring)>limit)return 0;
  for(s=v->valuestring;*s;s++)if(!strchr("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-",*s))return 0;
  return 1;
}
cJSON *sp_human_parse_command(const char *payload)
{
  static const char *const names[]={"schema","action_id","event_id","revision","step","actor","note","verified"};
  cJSON *o=NULL,*item,*v;unsigned mask=0;size_t i;
  if(!payload||strlen(payload)>1400||!sp_json_bounded(payload))return NULL;
  o=cJSON_ParseWithOpts(payload,NULL,1);if(!cJSON_IsObject(o))goto bad;
  cJSON_ArrayForEach(item,o) {
    for(i=0;i<8;i++)if(item->string&&!strcmp(item->string,names[i]))break;
    if(i==8||(mask&(1U<<i)))goto bad;
    mask|=1U<<i;
  }
  if(mask!=255||!identifier(get(o,"action_id"),64)||!identifier(get(o,"event_id"),64)||!identifier(get(o,"actor"),32))goto bad;
  v=get(o,"schema");if(!cJSON_IsNumber(v)||v->valuedouble!=1)goto bad;
  v=get(o,"revision");if(!cJSON_IsNumber(v)||v->valuedouble<1||v->valuedouble>INT_MAX||v->valuedouble!=(double)v->valueint)goto bad;
  v=get(o,"step");if(!cJSON_IsString(v)||(strcmp(v->valuestring,"CLAIM")&&strcmp(v->valuestring,"HANDLE")&&strcmp(v->valuestring,"CLOSE")))goto bad;
  if(!cJSON_IsBool(get(o,"verified"))||cJSON_IsTrue(get(o,"verified"))!=(strcmp(v->valuestring,"CLOSE")==0))goto bad;
  v=get(o,"note");if(!cJSON_IsString(v)||!v->valuestring[0]||strlen(v->valuestring)>240)goto bad;
  for(i=0;v->valuestring[i];i++)if((unsigned char)v->valuestring[i]<32)goto bad;
  return o;
bad:cJSON_Delete(o);return NULL;
}
const char *sp_human_state(const cJSON *row)
{
  cJSON *h=get(row,"human"),*s=get(h,"state");
  if(cJSON_IsString(s))return s->valuestring;
  return cJSON_IsTrue(get(row,"pending"))?"REQUIRED":"NOT_REQUIRED";
}
int sp_human_record_valid(const cJSON *row)
{
  static const char *const states[]={"REQUIRED","CLAIMED","HANDLED","CLOSED"};
  static const char *const steps[]={"CLAIM","HANDLE","CLOSE"};
  cJSON *h=get(row,"human"),*history,*item,*cmd;const char *s;int count,index=0;
  if(!h)return 1;
  if(!cJSON_IsObject(h)||!cJSON_IsString(get(h,"state")))return 0;
  s=sp_human_state(row);
  if(strcmp(s,"REQUIRED")&&strcmp(s,"CLAIMED")&&strcmp(s,"HANDLED")&&strcmp(s,"CLOSED")&&strcmp(s,"NOT_REQUIRED"))return 0;
  if(cJSON_IsTrue(get(row,"pending"))==(!strcmp(s,"CLOSED")||!strcmp(s,"NOT_REQUIRED")))return 0;
  history=get(h,"actions");if(!cJSON_IsArray(history)||cJSON_GetArraySize(history)>3)return 0;
  count=cJSON_GetArraySize(history);
  if((strcmp(s,"NOT_REQUIRED")&&strcmp(s,states[count]))||(!strcmp(s,"NOT_REQUIRED")&&count))return 0;
  if(count&&!identifier(get(h,"actor"),32))return 0;
  cJSON_ArrayForEach(item,history) {
    if(!identifier(get(item,"action_id"),64)||!cJSON_IsString(get(item,"payload")))return 0;
    cmd=sp_human_parse_command(get(item,"payload")->valuestring);if(!cmd)return 0;
    if(strcmp(get(cmd,"action_id")->valuestring,get(item,"action_id")->valuestring)||
       strcmp(get(cmd,"event_id")->valuestring,get(get(row,"event"),"event_id")->valuestring)||
       get(cmd,"revision")->valueint!=get(get(row,"event"),"revision")->valueint||
       strcmp(get(cmd,"step")->valuestring,steps[index])||
       strcmp(get(cmd,"actor")->valuestring,get(h,"actor")->valuestring)){cJSON_Delete(cmd);return 0;}
    index++;
    cJSON_Delete(cmd);
  }
  return 1;
}
static int unhex(const char *s,unsigned char *out,size_t n)
{
  size_t i;unsigned value=0;const char *p;
  if(strlen(s)!=2*n)return -1;
  for(i=0;i<2*n;i++) {
    p=strchr("0123456789abcdef",s[i]);if(!p)return -1;
    value=(value<<4)|(unsigned)(p-"0123456789abcdef");
    if(i&1){out[i/2]=(unsigned char)value;value=0;}
  }
  return 0;
}
static int read_key(const char *root,unsigned char key[32])
{
  char path[256],buf[67];FILE *f;size_t n;int ret=-1;
  if(snprintf(path,sizeof(path),"%s/control.key",!strcmp(root,"/data/ai_agent/sp")?"/data/spine-auth":root)>=(int)sizeof(path))return -1;
  f=fopen(path,"rb");if(!f)return -1;
  n=fread(buf,1,sizeof(buf)-1,f);
  if(!ferror(f)&&feof(f)&&n>=64) {
    while(n&&(buf[n-1]=='\n'||buf[n-1]=='\r'))n--;
    buf[n]=0;ret=unhex(buf,key,32);
  }
  fclose(f);memset(buf,0,sizeof(buf));return ret;
}
static int mac(const unsigned char key[32],const char *text,unsigned char out[32])
{return mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),key,32,(const unsigned char *)text,strlen(text),out);}
static char *sign(const unsigned char key[32],const char *payload)
{
  unsigned char digest[32];char hex[65],*result=NULL;cJSON *o;size_t i;
  if(mac(key,payload,digest))return NULL;
  for(i=0;i<32;i++)snprintf(hex+2*i,3,"%02x",digest[i]);
  o=cJSON_CreateObject();if(!o)return NULL;
  cJSON_AddStringToObject(o,"payload",payload);cJSON_AddStringToObject(o,"mac",hex);
  result=cJSON_PrintUnformatted(o);cJSON_Delete(o);return result;
}
int sp_human_apply_signed(const char *root,const char *envelope,char **reply)
{
  unsigned char key[32],expected[32],received[32];unsigned diff=0;size_t i;
  cJSON *o=NULL,*item,*payload,*sig,*command=NULL;char *result=NULL;int count=0,ret=2;
  *reply=NULL;
  if(!envelope||strlen(envelope)>2048||!sp_json_bounded(envelope)||read_key(root,key))return 2;
  o=cJSON_ParseWithOpts(envelope,NULL,1);if(!cJSON_IsObject(o))goto done;
  cJSON_ArrayForEach(item,o)count++;
  payload=get(o,"payload");sig=get(o,"mac");
  if(count!=2||!cJSON_IsString(payload)||!cJSON_IsString(sig)||unhex(sig->valuestring,received,32)||mac(key,payload->valuestring,expected))goto done;
  for(i=0;i<32;i++)diff|=expected[i]^received[i];
  if(diff)goto done;
  command=sp_human_parse_command(payload->valuestring);if(!command)goto done;
  ret=sp_store_human_apply(root,command,payload->valuestring,&result);
  if(ret==0){*reply=sign(key,result);if(!*reply)ret=3;}
done:
  memset(key,0,sizeof(key));cJSON_Delete(o);cJSON_Delete(command);cJSON_free(result);return ret;
}
int sp_human_sync_step(const char *root,const char *endpoint)
{
  char path[256],body[2049],ack[2049];FILE *f;cJSON *o=NULL;char *reply=NULL;int ret=1;
  if(snprintf(path,sizeof(path),"%s/control.key",!strcmp(root,"/data/ai_agent/sp")?"/data/spine-auth":root)>=(int)sizeof(path))return 1;
  f=fopen(path,"rb");if(!f)return 0;fclose(f); /* No key: feature disabled. */
  if(sp_http_exchange(endpoint,"GET","/human-actions",NULL,body,sizeof(body)))goto done;
  if(!strcmp(body,"{\"empty\":true}")){ret=0;goto done;}
  if(sp_human_apply_signed(root,body,&reply))goto done;
  if(sp_http_exchange(endpoint,"POST","/human-results",reply,ack,sizeof(ack)))goto done;
  o=cJSON_ParseWithOpts(ack,NULL,1);
  if(cJSON_IsObject(o)&&cJSON_IsTrue(get(o,"persisted")))ret=0;
done:
  cJSON_Delete(o);cJSON_free(reply);return ret;
}
