#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

/*
 * fexshm v3 - 让 FEX 的 stats 文件"一出生就是 1 MiB"。
 *
 * 背景（设备实测，2026-10-06）：
 *   1) wine/FEX 在 $TMPDIR 建出 /data/data/.../usr/tmp/fex-<pid>-stats，大小 0；
 *   2) FEX 随即 mmap 这个 0 字节文件并写入 header -> 页在 EOF 之外 -> SIGBUS，
 *      FEX 判定 stats 不可用后就不再写 -> 文件永远 0 字节（header=0）；
 *   3) MangoHud 读到 header.Version==0 -> 显示 "version mismatch" / "FEX Not Found!"。
 *   => 事后用 inotify/轮询把文件撑大（fexsizer）已经太晚，必须赢在 open 返回之前。
 *
 * v3 在 v2（shm_open 重定向 + 预分配）基础上，额外拦截普通文件路径：
 *   open / open64 / openat / openat64 / creat
 *   只要目标是 *fex-<数字>-stats 且刚被创建（或 O_TRUNC 过）后仍是 0 字节，
 *   就地 ftruncate 到 $FEXSHM_SIZE（默认 1 MiB）。
 *
 * 实现约束：
 *   - 内部一律走 syscall(SYS_openat)，不经过被 hook 的 open/openat，避免自递归；
 *   - 不使用 dlsym()，保持依赖为 GLIBC_2.17（Termux glibc 可加载）。
 *
 * 日志：$FEXSHM_DIR/fexshm.log（FEXSHM_LOG=0 关闭）
 * 编译：gcc -shared -fPIC -O2 -o libfexshm.so fexshm.c
 */

#ifndef FEXSHM_DEFAULT_DIR
#define FEXSHM_DEFAULT_DIR "/data/data/com.termux/files/usr/tmp"
#endif
#ifndef FEXSHM_DEFAULT_SIZE
#define FEXSHM_DEFAULT_SIZE 1048576ULL /* 1 MiB >= FEX MAX_STATS_SIZE */
#endif

static const char* shm_dir(void) {
  const char* d = getenv("FEXSHM_DIR");
  return (d && *d) ? d : FEXSHM_DEFAULT_DIR;
}

static unsigned long long prealloc_size(void) {
  const char* s = getenv("FEXSHM_SIZE");
  if (s && *s) {
    unsigned long long v = strtoull(s, NULL, 0);
    if (v) return v;
  }
  return FEXSHM_DEFAULT_SIZE;
}

static int logging_on(void) {
  const char* s = getenv("FEXSHM_LOG");
  return !(s && *s == '0');
}

/* 只用裸 syscall 写日志，绝不走被 hook 的 open/openat。 */
static void log_line(const char* fmt, ...) {
  char buf[512];
  char path[600];
  int n, fd;
  va_list ap;

  if (!logging_on()) return;

  va_start(ap, fmt);
  n = vsnprintf(buf, sizeof buf, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  if ((size_t)n > sizeof buf - 2) n = (int)(sizeof buf - 2);
  buf[n++] = '\n';
  buf[n] = 0;

  if ((size_t)snprintf(path, sizeof path, "%s/fexshm.log", shm_dir()) >= sizeof path) return;
  fd = (int)syscall(SYS_openat, AT_FDCWD, path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0666);
  if (fd < 0) return;
  {
    ssize_t ignored = (ssize_t)syscall(SYS_write, fd, buf, (size_t)n);
    (void)ignored;
  }
  syscall(SYS_close, fd);
}

/* 目标名是否形如 fex-<数字>-stats（取 basename，任何目录都算） */
static int is_fex_stats_name(const char* path) {
  const char* base;
  const char* q;

  if (!path || !*path) return 0;
  base = strrchr(path, '/');
  base = base ? base + 1 : path;
  if (strncmp(base, "fex-", 4) != 0) return 0;
  q = base + 4;
  if (*q < '0' || *q > '9') return 0;
  while (*q >= '0' && *q <= '9') ++q;
  return strcmp(q, "-stats") == 0;
}

/* 0 字节 -> ftruncate 到 1MiB（在返回 fd 之前完成，保证调用方 mmap 时文件已够大） */
static int size_up(int fd, const char* path) {
  struct stat st;
  unsigned long long want;

  if (fd < 0) return fd;
  if (fstat(fd, &st) != 0) return fd;
  if (st.st_size != 0) return fd;

  want = prealloc_size();
  if (ftruncate(fd, (off_t)want) == 0) {
    log_line("[open] pre-size %s -> %llu 字节", path, want);
  } else {
    log_line("[open] ftruncate(%s, %llu) 失败: %s", path, want, strerror(errno));
  }
  return fd;
}

static int size_up_if_stats(int fd, const char* path) {
  if (fd < 0) return fd;
  if (!is_fex_stats_name(path)) return fd;
  return size_up(fd, path);
}

static mode_t fetch_mode(int flags, va_list ap) {
  if (flags & (O_CREAT | O_TMPFILE)) return (mode_t)va_arg(ap, int);
  return 0;
}

/* ---------- 普通文件路径 ---------- */

int open(const char* path, int flags, ...) {
  mode_t mode = 0;
  va_list ap;
  int fd;

  if (flags & (O_CREAT | O_TMPFILE)) {
    va_start(ap, flags);
    mode = fetch_mode(flags, ap);
    va_end(ap);
  }
  fd = (int)syscall(SYS_openat, AT_FDCWD, path, flags, mode);
  return size_up_if_stats(fd, path);
}

int open64(const char* path, int flags, ...) {
  mode_t mode = 0;
  va_list ap;
  int fd;

  if (flags & (O_CREAT | O_TMPFILE)) {
    va_start(ap, flags);
    mode = fetch_mode(flags, ap);
    va_end(ap);
  }
  fd = (int)syscall(SYS_openat, AT_FDCWD, path, flags, mode);
  return size_up_if_stats(fd, path);
}

int openat(int dirfd, const char* path, int flags, ...) {
  mode_t mode = 0;
  va_list ap;
  int fd;

  if (flags & (O_CREAT | O_TMPFILE)) {
    va_start(ap, flags);
    mode = fetch_mode(flags, ap);
    va_end(ap);
  }
  fd = (int)syscall(SYS_openat, dirfd, path, flags, mode);
  return size_up_if_stats(fd, path);
}

int openat64(int dirfd, const char* path, int flags, ...) {
  mode_t mode = 0;
  va_list ap;
  int fd;

  if (flags & (O_CREAT | O_TMPFILE)) {
    va_start(ap, flags);
    mode = fetch_mode(flags, ap);
    va_end(ap);
  }
  fd = (int)syscall(SYS_openat, dirfd, path, flags, mode);
  return size_up_if_stats(fd, path);
}

int creat(const char* path, mode_t mode) {
  int fd = (int)syscall(SYS_openat, AT_FDCWD, path, O_CREAT | O_WRONLY | O_TRUNC, mode);
  return size_up_if_stats(fd, path);
}

int creat64(const char* path, mode_t mode) {
  return creat(path, mode);
}

/* ---------- shm_open 路径（保留 v2 行为） ---------- */

static int flat_name(const char* name) {
  if (!name || !*name) return 0;
  if (*name == '/') ++name;
  return *name && !strchr(name, '/');
}

int shm_open(const char* name, int oflag, ...) {
  char path[512];
  mode_t mode = 0;
  va_list ap;
  int fd;

  if (oflag & O_CREAT) {
    va_start(ap, oflag);
    mode = (mode_t)va_arg(ap, int);
    va_end(ap);
  }

  if (!flat_name(name)) {
    if (!name || name[0] != '/') {
      errno = EINVAL;
      return -1;
    }
    if ((size_t)snprintf(path, sizeof path, "/dev/shm%s", name) >= sizeof path) {
      errno = ENAMETOOLONG;
      return -1;
    }
    fd = (int)syscall(SYS_openat, AT_FDCWD, path, oflag | O_CLOEXEC, mode);
    if (fd >= 0 && (oflag & O_CREAT)) {
      log_line("shm_open%s (落回 /dev/shm)", path);
      size_up(fd, path);
    }
    return fd;
  }

  if (name[0] == '/') ++name;
  if ((size_t)snprintf(path, sizeof path, "%s/%s", shm_dir(), name) >= sizeof path) {
    errno = ENAMETOOLONG;
    return -1;
  }
  if (oflag & O_CREAT) mkdir(shm_dir(), 0777);
  fd = (int)syscall(SYS_openat, AT_FDCWD, path, oflag | O_CLOEXEC, mode);
  log_line("shm_open %s name=%s oflag=0x%x -> fd=%d %s", path, name, oflag, fd, fd < 0 ? strerror(errno) : "");
  if (fd >= 0 && (oflag & O_CREAT)) size_up(fd, path);
  return fd;
}

int shm_open64(const char* name, int oflag, ...) {
  mode_t mode = 0;
  va_list ap;
  if (oflag & O_CREAT) {
    va_start(ap, oflag);
    mode = (mode_t)va_arg(ap, int);
    va_end(ap);
  }
  return shm_open(name, oflag, mode);
}

int shm_unlink(const char* name) {
  char path[512];

  if (!flat_name(name)) {
    if (!name || name[0] != '/') {
      errno = EINVAL;
      return -1;
    }
    if ((size_t)snprintf(path, sizeof path, "/dev/shm%s", name) >= sizeof path) {
      errno = ENAMETOOLONG;
      return -1;
    }
    log_line("shm_unlink %s", path);
    return unlink(path);
  }
  if (name[0] == '/') ++name;
  if ((size_t)snprintf(path, sizeof path, "%s/%s", shm_dir(), name) >= sizeof path) {
    errno = ENAMETOOLONG;
    return -1;
  }
  log_line("shm_unlink %s", path);
  return unlink(path);
}