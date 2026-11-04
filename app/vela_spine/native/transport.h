#ifndef SP_TRANSPORT_H
#define SP_TRANSPORT_H
#include <stddef.h>
/* Private IPv4:port only. Plain HTTP for isolated replay LAN/SSH gateway. */
int sp_http_post(const char *endpoint,const char *body,const char *notice_id);
int sp_http_endpoint_valid(const char *endpoint);
int sp_http_exchange(const char *endpoint,const char *method,const char *path,const char *body,char *out,size_t size);
#endif
