#include "task_watch.h"
#include "task.h"
#include "transport.h"
#include "cJSON.h"
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int sp_task_watch(const char *root,const char *endpoint,unsigned cycles)
{
  char path[256],*reply=NULL;struct flock lock;int fd,n,code;unsigned count=0;
  if(!sp_http_endpoint_valid(endpoint))return 2;
  n=snprintf(path,sizeof(path),"%s/taskwatch.lock",root);
  if(n<0||(size_t)n>=sizeof(path))return 2;
  fd=open(path,O_RDWR|O_CREAT,0600);if(fd<0)return 3;
  memset(&lock,0,sizeof(lock));lock.l_type=F_WRLCK;lock.l_whence=SEEK_SET;
  if(fcntl(fd,F_SETLK,&lock)<0){close(fd);return 3;}
  puts("{\"task_watch\":\"STARTED\",\"motion\":false}");fflush(stdout);
  for(;;){
    code=sp_task_dispatch(root,endpoint,&reply);cJSON_free(reply);reply=NULL;
    if(!code||code==4){
      code=sp_task_stop_sync(root,endpoint,&reply);cJSON_free(reply);reply=NULL;
      if(!code||code==4){code=sp_task_poll(root,endpoint,&reply);cJSON_free(reply);reply=NULL;}
    }
    if(code && count<64){printf("{\"task_watch_error\":%d,\"motion\":false}\n",code);fflush(stdout);}
    count++;if(cycles&&count>=cycles)break;
    sleep(2);
  }
  close(fd);return code;
}

int sp_task_service(void)
{
  char endpoint[65];size_t n;FILE *fp=fopen("/data/ai_agent/sp/task-end.txt","rb");
  if(!fp)return 2;
  n=fread(endpoint,1,sizeof(endpoint)-1,fp);
  if(ferror(fp)||!feof(fp)||!n||memchr(endpoint,0,n)){fclose(fp);return 2;}
  fclose(fp);while(n&&(endpoint[n-1]=='\n'||endpoint[n-1]=='\r'))n--;
  endpoint[n]=0;
  return sp_task_watch("/data/ai_agent/sp",endpoint,0);
}
