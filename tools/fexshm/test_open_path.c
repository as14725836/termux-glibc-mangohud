/* 模拟 wine/FEX 的真实序列：普通 open(O_CREAT) 建文件 -> 立刻 mmap -> 写 header
 * 用法: TPATH=/path/fex-12345-stats ./t3 open        (走 open)
 *       TPATH=/path/fex-12345-stats ./t3 openat      (走 openat)
 * 期望（有垫片 v3）: open 后大小立刻 = 1048576，写 header 后另一个 fd 能读回 2/3
 * 期望（无垫片）    : open 后大小 = 0，mmap+写 -> Bus error
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char** argv) {
  const char* p = getenv("TPATH");
  const char* mode = argc > 1 ? argv[1] : "open";
  struct stat st;
  void* b;
  int fd, fd2;
  unsigned int buf[2] = {0, 0};

  if (!p) {
    fprintf(stderr, "need TPATH\n");
    return 1;
  }
  unlink(p);

  if (strcmp(mode, "openat") == 0) {
    fd = openat(AT_FDCWD, p, O_CREAT | O_RDWR, 0600);
  } else {
    fd = open(p, O_CREAT | O_RDWR, 0600);
  }
  if (fd < 0) {
    perror("open");
    return 2;
  }

  if (fstat(fd, &st) != 0) {
    perror("fstat");
    return 3;
  }
  printf("open 后立即 fstat 大小 = %lld\n", (long long)st.st_size);

  b = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (b == MAP_FAILED) {
    perror("mmap");
    return 4;
  }
  ((unsigned int*)b)[0] = 2; /* Version */
  ((unsigned int*)b)[1] = 3; /* app_type = WIN_ARM64EC */
  if (msync(b, 4096, MS_SYNC) != 0) perror("msync");

  fstat(fd, &st);
  printf("写 header 后大小 = %lld, 映射内 header = %u/%u\n", (long long)st.st_size, ((unsigned int*)b)[0],
         ((unsigned int*)b)[1]);

  fd2 = open(p, O_RDONLY);
  if (fd2 >= 0) {
    if (read(fd2, buf, 8) < 0) perror("read");
    close(fd2);
  }
  printf("另一个 fd 读回 = Version=%u app_type=%u  %s\n", buf[0], buf[1], (buf[0] == 2 && buf[1] == 3) ? "✅" : "❌");
  close(fd);
  return (buf[0] == 2 && buf[1] == 3) ? 0 : 5;
}