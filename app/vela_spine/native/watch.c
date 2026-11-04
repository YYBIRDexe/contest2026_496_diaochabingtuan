#include "watch.h"
#include "store.h"
#include "transport.h"
#include "human.h"
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>

/* Foreground worker; NSH may background it. cycles=0 runs until terminated.
 * Kernel releases the separate owner lock on exit, including forced exit.
 * No signal handlers or daemon globals: NuttX builtins share an address space.
 */
int sp_watch(const char *root,const char *endpoint,unsigned cycles)
{
  char path[256];struct flock lock;int fd,n,code=0,outcome;
  unsigned attempt=0,delay=2,wait,logged=0;
  unsigned control_delay=2;time_t control_due=0;
  if(!sp_http_endpoint_valid(endpoint))return 2;
  n=snprintf(path,sizeof(path),"%s/watch.lock",root);
  if(n<0||(size_t)n>=sizeof(path)) return 2;
  fd=open(path,O_RDWR|O_CREAT,0600);if(fd<0) return 3;
  memset(&lock,0,sizeof(lock));lock.l_type=F_WRLCK;lock.l_whence=SEEK_SET;
  if(fcntl(fd,F_SETLK,&lock)<0) {close(fd);fputs("watch already owned or unavailable\n",stderr);return 3;}
  puts("{\"watch\":\"STARTED\",\"motion\":false}");fflush(stdout);
  for(;;) {
    outcome=SP_EMPTY;code=sp_store_delivery_step(root,endpoint,&outcome);attempt++;
    if(!code) {
      struct timespec tick;
      if(!clock_gettime(CLOCK_MONOTONIC,&tick)&&tick.tv_sec>=control_due) {
        int control=sp_human_sync_step(root,endpoint);
        control_due=tick.tv_sec+(control?control_delay:2);
        control_delay=control?(control_delay>=30?60:control_delay*2):2;
      }
    }
    if((code || outcome!=SP_EMPTY) && logged<128) {
      const char *status=code?"RETRY_PENDING":outcome==SP_SENT?"DELIVERED":"ACK_FOR_OLDER_REVISION";
      printf("{\"status\":\"%s\",\"motion\":false}\n",status);logged++;
      if(logged==128)puts("{\"watch\":\"LOG_LIMIT_REACHED\",\"motion\":false}");
    }
    fflush(stdout);
    /* Corrupt/unavailable storage fails closed; never silently recreate it. */
    if(code==3) break;
    if(cycles && attempt>=cycles) break;
    if(code) {
      wait=delay;delay=delay>=30?60:delay*2;
      if(logged<128)fprintf(stderr,"watch retry in %u seconds\n",wait);
    } else {
      delay=2;wait=outcome==SP_EMPTY?2:0;
    }
    /* Network total deadline is enforced by transport; no store lock here. */
    while(wait) wait=sleep(wait);
  }
  close(fd);return code;
}
int sp_service(void)
{
  char endpoint[65];size_t n;FILE *fp=fopen("/data/ai_agent/sp/endpoint.txt","rb");
  if(!fp)return 2;
  n=fread(endpoint,1,sizeof(endpoint)-1,fp);
  if(ferror(fp)||!feof(fp)||!n||memchr(endpoint,0,n)){fclose(fp);return 2;}
  fclose(fp);
  while(n && (endpoint[n-1]=='\n'||endpoint[n-1]=='\r'))n--;
  endpoint[n]=0;
  return sp_watch("/data/ai_agent/sp",endpoint,0);
}
