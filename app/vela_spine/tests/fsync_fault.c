/* Host-only linker wrapper. Never included in the firmware Makefile. */
#include <stdlib.h>
#include <errno.h>
int __real_fsync(int fd);
int __wrap_fsync(int fd)
{
  static unsigned long calls;
  const char *fail_at=getenv("SP_TEST_FSYNC_FAIL_AT");
  calls++;
  if(getenv("SP_TEST_FSYNC_FAIL")||(fail_at&&strtoul(fail_at,NULL,10)==calls)) {errno=EIO;return -1;}
  return __real_fsync(fd);
}
