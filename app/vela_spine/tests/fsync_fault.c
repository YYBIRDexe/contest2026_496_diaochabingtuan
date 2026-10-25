/* Host-only linker wrapper. Never included in the firmware Makefile. */
#include <stdlib.h>
#include <errno.h>
int __real_fsync(int fd);
int __wrap_fsync(int fd)
{
  if(getenv("SP_TEST_FSYNC_FAIL")) {errno=EIO;return -1;}
  return __real_fsync(fd);
}
