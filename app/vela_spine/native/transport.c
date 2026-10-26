#include "transport.h"
#include "ingress.h"
#include "cJSON.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <time.h>
#include <sys/socket.h>
#include <arpa/inet.h>

static int64_t now_ms(void)
{
  struct timespec t;
  if(clock_gettime(CLOCK_MONOTONIC,&t)) return -1;
  return (int64_t)t.tv_sec*1000+t.tv_nsec/1000000;
}
static int wait_socket(int fd,short events,int64_t deadline)
{
  struct pollfd p;int ret;int64_t left,now;
  for(;;) {
    now=now_ms();if(now<0) return -1;
    left=deadline-now;if(left<=0) return -1;
    memset(&p,0,sizeof(p));p.fd=fd;p.events=events;
    ret=poll(&p,1,(int)left);
    if(ret<0&&errno==EINTR) continue;
    return ret>0&&(p.revents&(events|POLLHUP))?0:-1;
  }
}
static int send_all(int fd,const char *p,size_t n,int64_t deadline)
{
  while(n) {
    ssize_t sent;
    if(wait_socket(fd,POLLOUT,deadline)) return -1;
#ifdef MSG_NOSIGNAL
    sent=send(fd,p,n,MSG_NOSIGNAL);
#else
    sent=send(fd,p,n,0);
#endif
    if(sent<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK)) continue;
    if(sent<=0) return -1;
    p+=sent;n-=(size_t)sent;
  }
  return 0;
}
/* Strict bounded framing: one Content-Length, no chunking or close framing. */
static int framing(const char *buf,size_t used,size_t *total,size_t *offset)
{
  const char *end=strstr(buf,"\r\n\r\n"),*p,*line;int found=0;size_t len=0;
  if(!end) return used>2048?-1:0;
  if((size_t)(end-buf)>2048) return -1;
  if((strncmp(buf,"HTTP/1.0 ",9)&&strncmp(buf,"HTTP/1.1 ",9))||
     strncmp(buf+9,"200",3)||(buf[12]!=' '&&buf[12]!='\r')) return -1;
  p=strstr(buf,"\r\n");if(!p) return -1;p+=2;
  while(p<end) {
    const char *colon;size_t keysize;
    line=strstr(p,"\r\n");if(!line) return -1;
    colon=memchr(p,':',(size_t)(line-p));if(!colon) return -1;
    keysize=(size_t)(colon-p);
    if(keysize==17&&!strncasecmp(p,"Transfer-Encoding",17)) return -1;
    if(keysize==14&&!strncasecmp(p,"Content-Length",14)) {
      const char *v=colon+1;unsigned long value=0;int digits=0;
      if(found++) return -1;
      while(v<line&&(*v==' '||*v=='\t'))v++;
      while(v<line&&*v>='0'&&*v<='9') {
        digits=1;value=value*10+(unsigned)(*v++-'0');if(value>2048) return -1;
      }
      while(v<line&&(*v==' '||*v=='\t'))v++;
      if(!digits||v!=line||!value) return -1;
      len=(size_t)value;
    }
    p=line+2;
  }
  if(found!=1) return -1;
  *offset=(size_t)(end-buf)+4;*total=*offset+len;
  return *total<=4096?1:-1;
}
static int ack_valid(const char *body,const char *id)
{
  cJSON *o=NULL,*item,*v;int count=0,ids=0,persisted=0,ok=0;
  if(strstr(body,"\\u0000")||!sp_json_bounded(body)) return 0;
  o=cJSON_ParseWithOpts(body,NULL,1);if(!cJSON_IsObject(o)) goto done;
  cJSON_ArrayForEach(item,o) {
    count++;
    if(!item->string) goto done;
    if(!strcmp(item->string,"notification_id")) ids++;
    else if(!strcmp(item->string,"persisted")) persisted++;
    else goto done;
  }
  v=cJSON_GetObjectItemCaseSensitive(o,"notification_id");
  if(count!=2||ids!=1||persisted!=1||!cJSON_IsString(v)||strcmp(v->valuestring,id)) goto done;
  ok=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(o,"persisted"));
done:
  cJSON_Delete(o);return ok;
}
static int endpoint_address(const char *endpoint,struct sockaddr_in *addr)
{
  char host[16];const char *colon;size_t hostlen;
  uint32_t ip;unsigned long port;char *tail;
  if(!endpoint)return -1;
  colon=strchr(endpoint,':');if(!colon) return -1;hostlen=(size_t)(colon-endpoint);
  if(!hostlen||hostlen>=sizeof(host)||strchr(colon+1,':')) return -1;
  memcpy(host,endpoint,hostlen);host[hostlen]=0;
  if(!colon[1]||strspn(colon+1,"0123456789")!=strlen(colon+1)) return -1;
  errno=0;port=strtoul(colon+1,&tail,10);if(errno||*tail||!port||port>65535) return -1;
  memset(addr,0,sizeof(*addr));addr->sin_family=AF_INET;addr->sin_port=htons((uint16_t)port);
  if(inet_pton(AF_INET,host,&addr->sin_addr)!=1) return -1;
  ip=ntohl(addr->sin_addr.s_addr);
  if((ip>>24)!=127&&(ip>>24)!=10&&(ip>>16)!=0xc0a8&&
     (ip&0xfff00000U)!=0xac100000U) return -1;
  return 0;
}
int sp_http_endpoint_valid(const char *endpoint)
{ struct sockaddr_in addr;return endpoint_address(endpoint,&addr)==0; }
int sp_http_exchange(const char *endpoint,const char *method,const char *path,const char *body,char *out,size_t size)
{
  char header[256],*response=NULL;struct sockaddr_in addr;
  int fd=-1,ret=-1,flags,error,n,framed=0;socklen_t elen=sizeof(error);
  size_t used=0,total=0,offset=0;int64_t deadline=now_ms();
  if(!body)body="";
  if(!out||!size||!method||!path||deadline<0||strlen(body)>8192||endpoint_address(endpoint,&addr))return -1;
  if(strcmp(method,"GET")&&strcmp(method,"POST"))return -1;
  if(strcmp(path,"/incidents")&&strcmp(path,"/human-actions")&&strcmp(path,"/human-results")&&
     strcmp(path,"/v1/commands")&&strcmp(path,"/v1/state"))return -1;
  n=snprintf(header,sizeof(header),"%s %s HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\nContent-Length: %lu\r\nConnection: close\r\n\r\n",method,path,endpoint,(unsigned long)strlen(body));
  if(n<0||(size_t)n>=sizeof(header)) return -1;
  fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0) return -1;
  response=malloc(4097);if(!response) goto done;
  flags=fcntl(fd,F_GETFL,0);if(flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK)) goto done;
  deadline+=6000;
  if(connect(fd,(struct sockaddr *)&addr,sizeof(addr))<0&&errno!=EINPROGRESS) goto done;
  if(wait_socket(fd,POLLOUT,deadline)||getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&elen)||error) goto done;
  if(send_all(fd,header,(size_t)n,deadline)||send_all(fd,body,strlen(body),deadline)) goto done;
  while(used<4096) {
    ssize_t got;
    if(wait_socket(fd,POLLIN,deadline)) goto done;
    got=recv(fd,response+used,4096-used,0);
    if(got<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK)) continue;
    if(got<=0) goto done;
    if(memchr(response+used,0,(size_t)got)) goto done;
    used+=(size_t)got;response[used]=0;
    if(!framed) {framed=framing(response,used,&total,&offset);if(framed<0) goto done;}
    if(framed&&used>=total) {
      if(used!=total) goto done;
      if(total-offset>=size)goto done;
      memcpy(out,response+offset,total-offset);out[total-offset]=0;ret=0;break;
    }
  }
done:
  close(fd);free(response);return ret;
}
int sp_http_post(const char *endpoint,const char *body,const char *notice_id)
{
  char ack[2049];
  if(!notice_id||sp_http_exchange(endpoint,"POST","/incidents",body,ack,sizeof(ack)))return -1;
  return ack_valid(ack,notice_id)?0:-1;
}
