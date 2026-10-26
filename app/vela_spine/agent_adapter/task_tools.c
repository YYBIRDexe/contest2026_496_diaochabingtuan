/* 三个业务工具的实现：参数只做形状检查，真正的字段/版本/归属校验在账本里。
 * 结果统一封装成 {"tool","ok","status","motion":false,"ack_scope","result"}，
 * 便于审计“模型调用了什么、执行返回了什么”，并与“模型只是在解释”区分开。
 */
#include "task_tools.h"
#include "../native/task.h"
#include "../native/ingress.h"
#include "cJSON.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

const char *sp_task_tool_prompt(void)
{
  return "本轮可用业务工具只有三个，禁止 shell、文件路径、速度或任意 URL：\n"
         "- task_status：查询任务账本，参数 {} 或 {\"task_id\":\"T1\"}。\n"
         "- task_submit：提交 spine-plan-v1 计划（最多 8 条任务），返回是否落盘。\n"
         "- task_stop：请求停止指定任务，参数 {\"task_id\":\"T1\"}；"
         "只有执行器回报 STOP_CONFIRMED 才算停止完成。\n";
}

static cJSON *parse_object(const char *args,int max_fields)
{
  cJSON *doc;
  if(!args)return NULL;
  doc=cJSON_ParseWithOpts(args,NULL,1);
  if(!cJSON_IsObject(doc)||cJSON_GetArraySize(doc)>max_fields){cJSON_Delete(doc);return NULL;}
  return doc;
}

static char *tool_status(const char *root,const char *args,int *code)
{
  char *inner=NULL;const char *task_id=NULL;cJSON *doc=parse_object(args,1),*id;
  if(!doc){*code=2;return NULL;}
  id=cJSON_GetObjectItemCaseSensitive(doc,"task_id");
  if(id&&!cJSON_IsString(id)){cJSON_Delete(doc);*code=2;return NULL;}
  if(id)task_id=id->valuestring;
  *code=sp_task_view(root,task_id,&inner);
  cJSON_Delete(doc);
  return inner;
}

static char *tool_submit(const char *root,const char *args,int *code)
{
  char *inner=NULL;cJSON *doc=parse_object(args,16);
  cJSON *tasks;
  if(!doc){*code=2;return NULL;}
  tasks=cJSON_GetObjectItemCaseSensitive(doc,"tasks");
  if(!cJSON_IsArray(tasks)||cJSON_GetArraySize(tasks)>8){cJSON_Delete(doc);*code=2;return NULL;}
  cJSON_Delete(doc);
  *code=sp_task_plan_apply(root,args,&inner);
  return inner;
}

static char *tool_stop(const char *root,const char *endpoint,const char *args,int *code)
{
  char *inner=NULL,*sync=NULL;cJSON *doc=parse_object(args,1),*id;
  if(!doc){*code=2;return NULL;}
  id=cJSON_GetObjectItemCaseSensitive(doc,"task_id");
  if(!cJSON_IsString(id)){cJSON_Delete(doc);*code=2;return NULL;}
  *code=sp_task_stop(root,id->valuestring,"AGENT_REQUEST",&inner);
  cJSON_Delete(doc);
  if(!endpoint)return inner;
  if(sp_task_stop_sync(root,endpoint,&sync)==3){free(inner);free(sync);*code=3;return NULL;}
  if(sync&&inner){
    cJSON *merged=cJSON_CreateObject(),*a=cJSON_Parse(inner),*b=cJSON_Parse(sync);
    if(merged&&a&&b&&cJSON_AddItemToObject(merged,"request",a)&&
       cJSON_AddItemToObject(merged,"executor",b)){
      char *text=cJSON_PrintUnformatted(merged);
      cJSON_Delete(merged);free(inner);free(sync);
      if(text)return text;
      *code=3;return NULL;
    }
    cJSON_Delete(merged);cJSON_Delete(a);cJSON_Delete(b);
  }
  free(inner);free(sync);
  *code=3;
  return NULL;
}

int sp_task_tool_call(const char *root,const char *endpoint,const char *name,
                      const char *args_json,char **reply)
{
  char *inner=NULL;int code=2;cJSON *wrap=NULL,*result=NULL,*flag;
  if(reply)*reply=NULL;
  if(!root||!name||!args_json)return 2;
  if(strlen(args_json)>4096||!sp_json_bounded(args_json))return 2;
  if(!strcmp(name,"task_status"))inner=tool_status(root,args_json,&code);
  else if(!strcmp(name,"task_submit"))inner=tool_submit(root,args_json,&code);
  else if(!strcmp(name,"task_stop"))inner=tool_stop(root,endpoint,args_json,&code);
  else return 2;
  if(!reply){free(inner);return code?code:3;}
  wrap=cJSON_CreateObject();
  if(!wrap){free(inner);return 3;}
  flag=inner?cJSON_Parse(inner):NULL;
  if(!cJSON_AddStringToObject(wrap,"tool",name)||
     !cJSON_AddBoolToObject(wrap,"ok",code==0)||
     !cJSON_AddNumberToObject(wrap,"code",code)||
     !cJSON_AddBoolToObject(wrap,"motion",0)||
     !cJSON_AddStringToObject(wrap,"ack_scope","LOCAL_STORAGE_ONLY")){
    cJSON_Delete(flag);cJSON_Delete(wrap);free(inner);return 3;
  }
  result=flag?flag:(inner?cJSON_CreateString(inner):cJSON_CreateNull());
  if(!result||!cJSON_AddItemToObject(wrap,"result",result)){
    cJSON_Delete(result);cJSON_Delete(wrap);free(inner);return 3;
  }
  *reply=cJSON_PrintUnformatted(wrap);
  cJSON_Delete(wrap);free(inner);
  return *reply?code:3;
}
