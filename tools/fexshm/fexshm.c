#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

/*
 * fexshm v2 - redirect POSIX shm_open() to a regular file in a writable dir,
 *             AND make sure that file is never left 0 bytes.
 *
 * FEX-Emu publishes its stats through shm_open("/fex-<pid>-stats"), which can
 * only land in the glibc SHMDIR (/dev/shm).  Native Termux has no /dev/shm, so
 * the object is never created and overlays report "FEX Not Found!".
 * And even when the file does get created, a 0-byte shm object makes overlays
 * read an empty/broken header (MangoHud: "skip ... size 0 < header").
 *
 * v2 changes:
 *   - after a successful O_CREAT open, if the file is still 0 bytes, ftruncate()
 *     it to $FEXSHM_SIZE (default 1 MiB) so any later mmap by FEX/wine is
 *     file-backed with a real size and the guest's writes are readable;
 *   - append a one-line log per interception to $FEXSHM_DIR/fexshm.log
 *     (disable with FEXSHM_LOG=0) so we can see exactly who creates what;
 *   - everything else behaves like v1 (/dev/shm fallback for odd names).
 *
 * No dlsym() on purpose: keeps the dependency at GLIBC_2.17.
 * Build:  gcc -shared -fPIC -O2 -o libfexshm.so fexshm.c
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

static void log_line(const char* fmt, ...) {
  char buf[512];
  int n;
  int fd;
  va_list ap;

  if (!logging_on()) return;

  va_start(ap, fmt);
  n = vsnprintf(buf, sizeof buf, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  if ((size_t)n > sizeof buf - 2) n = (int)(sizeof buf - 2);
  buf[n++] = '\n';
  buf[n] = 0;

  fd = openat(AT_FDCWD, shm_dir(), O_RDONLY | O_DIRECTORY);
  if (fd >= 0) {
    int lf = openat(fd, "fexshm.log", O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0666);
    if (lf >= 0) {
      ssize_t ignored = write(lf, buf, (size_t)n);
      (void)ignored;
      close(lf);
    }
    close(fd);
  }
}

/* Make sure a freshly created shm file has a real size. */
static int size_up(int fd, const char* path) {
  struct stat st;
  unsigned long long want;

  if (fd < 0) return fd;
  if (fstat(fd, &st) != 0) {
    log_line("fstat(%s) 失败: %s", path, strerror(errno));
    return fd;
  }
  if (st.st_size != 0) return fd;

  want = prealloc_size();
  if (ftruncate(fd, (off_t)want) == 0) {
    log_line("pre-size %s -> %llu 字节", path, want);
  } else {
    log_line("ftruncate(%s, %llu) 失败: %s", path, want, strerror(errno));
  }
  return fd;
}

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
    /* Unusual name: behave like glibc (plain /dev/shm). */
    if (!name || name[0] != '/') {
      errno = EINVAL;
      return -1;
    }
    if ((size_t)snprintf(path, sizeof path, "/dev/shm%s", name) >= sizeof path) {
      errno = ENAMETOOLONG;
      return -1;
    }
    fd = open(path, oflag | O_CLOEXEC, mode);
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
  fd = open(path, oflag | O_CLOEXEC, mode);
  log_line("shm_open %s name=%s oflag=0x%x -> fd=%d%s", path, name, oflag, fd, fd < 0 ? strerror(errno) : "");
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