/* Narrow compatibility bridge for observed model text, not a generic executor.
 * The official registry still executes read_file and applies its path policy.
 */
#include "../native/ingress.h"
#include "cJSON.h"
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define VIEW "/data/ai_agent/sp/state.json"
/* File-tool write guard. Normalize slash/dot aliases before prefix matching. */
int sp_agent_path_reserved(const char *path)
{
  char normalized[512];size_t used=0,n;const char *p,*end;
  const char *root="/data/ai_agent/sp";
  if(!path||path[0]!='/')return 0;
  p=path;
  while(*p) {
    while(*p=='/')p++;
    if(!*p)break;
    end=strchr(p,'/');if(!end)end=p+strlen(p);n=(size_t)(end-p);
    if(n==2&&p[0]=='.'&&p[1]=='.')return 1;
    if(!(n==1&&p[0]=='.')) {
      if(used+n+1>=sizeof(normalized))return 1;
      normalized[used++]='/';memcpy(normalized+used,p,n);used+=n;
    }
    p=end;
  }
  normalized[used]=0;n=strlen(root);
  return !strncmp(normalized,root,n)&&(normalized[n]==0||normalized[n]=='/');
}
static const char *space(const char *p)
{ while(*p && isspace((unsigned char)*p))p++;return p; }
static int take(const char **p,const char *s)
{
  *p=space(*p);size_t n=strlen(s);
  if(strncmp(*p,s,n))return 0;
  *p+=n;return 1;
}
static int fields(const cJSON *o,int count)
{
  int n=0;const cJSON *p;
  if(!cJSON_IsObject(o))return 0;
  cJSON_ArrayForEach(p,o)n++;
  return n==count;
}
char *sp_parse_readonly_call(const char *text)
{
  const char *p,*end;cJSON *o=NULL,*args,*name,*path;char *ret=NULL;
  char buf[513];size_t n;
  if(!text||strlen(text)>8192)return NULL;
  p=space(text);
  if(take(&p,"<｜｜DSML｜｜ calls>")) {
    if(!take(&p,"<｜｜DSML｜｜ invoke name=\"read_file\">"))return NULL;
    if(!take(&p,"<｜｜DSML｜｜ parameter name=\"path\" string=\"true\">"))return NULL;
    if(strncmp(p,VIEW,strlen(VIEW)))return NULL;
    p+=strlen(VIEW);
    if(!take(&p,"</｜｜DSML｜｜ parameter>")||
       !take(&p,"</｜｜DSML｜｜ invoke>")||
       !take(&p,"</｜｜DSML｜｜ calls>")||*space(p))return NULL;
    ret=malloc(sizeof("{\"path\":\"" VIEW "\"}"));
    if(ret)strcpy(ret,"{\"path\":\"" VIEW "\"}");
    return ret;
  }
  /* Optional leading prose is accepted, but only a single complete envelope. */
  p=strstr(text,"<tool_call>");if(!p)return NULL;
  p+=strlen("<tool_call>");end=strstr(p,"</tool_call>");
  if(!end||*space(end+strlen("</tool_call>")))return NULL;
  n=(size_t)(end-p);if(!n||n>512)return NULL;
  memcpy(buf,p,n);buf[n]=0;
  if(strstr(buf,"\\u0000")||!sp_json_bounded(buf))return NULL;
  o=cJSON_ParseWithOpts(buf,NULL,1);if(!fields(o,2))goto done;
  name=cJSON_GetObjectItemCaseSensitive(o,"name");
  args=cJSON_GetObjectItemCaseSensitive(o,"arguments");
  if(!cJSON_IsString(name)||strcmp(name->valuestring,"read_file")||!fields(args,1))goto done;
  path=cJSON_GetObjectItemCaseSensitive(args,"path");
  if(!cJSON_IsString(path)||strcmp(path->valuestring,VIEW))goto done;
  ret=cJSON_PrintUnformatted(args);
done:
  cJSON_Delete(o);return ret;
}
