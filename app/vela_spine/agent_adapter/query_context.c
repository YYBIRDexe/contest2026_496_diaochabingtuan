/* Current readonly application context, independent of model tool choice.
 * The caller invokes the official registry. No files are written here.
 */
#include "../native/ingress.h"
#include "cJSON.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

int sp_query_matches(const char *s)
{
  if(!s) return 0;
  if(!strcmp(s,"/spine")) return 1;
  return (strstr(s,"巡检")||strstr(s,"脊椎")) &&
    (strstr(s,"查询")||strstr(s,"状态")||strstr(s,"解释")||strstr(s,"为何"));
}

char *sp_query_context(const char *query,
    int (*execute)(const char *,const char *,char *,size_t))
{
  char *skill=NULL,*state=NULL,*records_text=NULL,*result=NULL,sum[9];
  cJSON *doc=NULL,*records,*v;uint32_t crc=~(uint32_t)0;const unsigned char *p;int i;
  size_t n;
  if(!query||strlen(query)>512||!execute) return NULL;
  skill=calloc(1,4097);state=calloc(1,32769);
  if(!skill||!state) goto done;
  if(execute("read_file","{\"path\":\"/data/ai_agent/skills/spine-status.md\"}",skill,4097)!=0 ||
     !skill[0]||strlen(skill)>=4096) goto done;
  if(execute("read_file","{\"path\":\"/data/ai_agent/sp/state.json\"}",state,32769)!=0 ||
     strlen(state)>=32768||!sp_json_bounded(state)) goto done;
  doc=cJSON_ParseWithOpts(state,NULL,1);if(!cJSON_IsObject(doc)) goto done;
  v=cJSON_GetObjectItemCaseSensitive(doc,"schema");
  if(!cJSON_IsNumber(v)||v->valuedouble!=1) goto done;
  records=cJSON_GetObjectItemCaseSensitive(doc,"records");
  if(!cJSON_IsArray(records)||cJSON_GetArraySize(records)>32) goto done;
  records_text=cJSON_PrintUnformatted(records);if(!records_text) goto done;
  for(p=(const unsigned char *)records_text;*p;p++) {
    crc^=*p;for(i=0;i<8;i++) crc=(crc>>1)^((crc&1)?0xedb88320U:0);
  }
  snprintf(sum,sizeof(sum),"%08lx",(unsigned long)(~crc));
  v=cJSON_GetObjectItemCaseSensitive(doc,"crc32");
  if(!cJSON_IsString(v)||strcmp(v->valuestring,sum)) goto done;
  n=strlen(skill)+strlen(state)+strlen(query)+1024;
  result=malloc(n);if(!result) goto done;
  snprintf(result,n,
    "本轮应用已通过官方read_file执行两次只读查询，以下为本轮返回。"
    "只依据本轮技能与快照回答，不沿用历史结果。先报告记录数及指定事件是否存在。"
    "来源标签不参与评分或锁存；current_decision不是动作。"
    "delivered仅持久回执。human.state是人工流程状态，pending表示尚未关闭，不代表未接单。"
    "CLOSED表示该版本已人工复核关闭，assessment仍保留历史分级。回放非真实事故。\n"
    "<current_skill>\n%s\n</current_skill>\n"
    "<current_snapshot>\n%s\n</current_snapshot>\n用户查询：%s",skill,state,query);
done:
  cJSON_Delete(doc);cJSON_free(records_text);free(skill);free(state);return result;
}
