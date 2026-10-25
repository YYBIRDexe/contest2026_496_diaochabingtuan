#ifndef SP_TRANSPORT_H
#define SP_TRANSPORT_H
/* Private IPv4:port only. Plain HTTP for isolated replay LAN/SSH gateway. */
int sp_http_post(const char *endpoint,const char *body,const char *notice_id);
int sp_http_endpoint_valid(const char *endpoint);
#endif
