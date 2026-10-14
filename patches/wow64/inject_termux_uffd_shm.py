#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Termux: 禁用 uffd writewatch + shm_open 重定向到 Termux tmp（Pipetto 270a7ce5 适配）。

来源
----
Pipetto-crypto/wine commit 270a7ce54bbcc241bca9f35a7f7e98311b0ba668
("virtual: disable kernel writewatches on Android")，为 termux-glibc 构建移植：

  1) kernel_writewatch_init() 里 uffd 调用前加守卫：无 WINE_ALLOW_UFFD_WRITEWATCH
     时 use_kernel_writewatch = 0 并提前返回（Android 上 userfaultfd 受
     SELinux/seccomp 限制、WP_ASYNC/PM_SCAN 在常见厂商内核不可靠；回退到
     异常实现的 write watch）。设 WINE_ALLOW_UFFD_WRITEWATCH=1 恢复原行为。
  2) shm_open() -> $TMPDIR/<name> 普通文件（Android 无 /dev/shm）：
     兜底目录改为 Termux 的 /data/data/com.termux/files/usr/tmp
     （原 commit 的 "/tmp" 兜底对 Termux 无意义）。
     原 commit 只在 #ifdef __ANDROID__ 下生效——glibc 构建不定义该宏；
     这里用 termux_shm_open + 宏重定向的方式常量生效，且避免与 glibc
     sys/mman.h 的 shm_open 原型冲突（static 重定义会报错）。

幂等：两部分各自带 marker（termux_shm_open / WINE_ALLOW_UFFD_WRITEWATCH），
存在即跳过；锚点全部为内容锚点，不依赖行号。

用法: inject_termux_uffd_shm.py <wine-source-dir> [--dry-run]
"""
import io
import os
import sys

REL = "dlls/ntdll/unix/virtual.c"
SHM_MARK = "termux_shm_open"
WATCH_MARK = "WINE_ALLOW_UFFD_WRITEWATCH"

SHM_BLOCK = '''
#ifndef __ANDROID__
/* ---- [Termux patch] shm_open() -> Termux tmp file (Pipetto 270a7ce5, adapted) ----
 * Android has no /dev/shm; serve POSIX shm names (e.g. FEX stats "fex-<pid>-stats")
 * as regular files under the Termux tmp dir.  $TMPDIR wins when set.
 * (Guarded so trees carrying their own __ANDROID__ shm_open keep compiling.)
 */
static int __attribute__((unused)) termux_shm_open( const char *name, int oflag, mode_t mode )
{
    const char *dir = getenv( "TMPDIR" );
    char *fname;
    if (!dir || !dir[0]) dir = "/data/data/com.termux/files/usr/tmp";
    asprintf( &fname, "%s/%s", dir, name );
    return open( fname, oflag, mode );
}
#define shm_open termux_shm_open
#endif /* !__ANDROID__ */
'''

WATCH_BLOCK = '''    /* ---- [Termux patch] disable kernel write watches (Pipetto 270a7ce5, adapted) ----
     * userfaultfd is restricted on Android (SELinux/seccomp) and WP_ASYNC/PM_SCAN is
     * unreliable on common vendor kernels; use the exception-based implementation.
     * WINE_ALLOW_UFFD_WRITEWATCH=1 opts back in.
     */
    if (!getenv( "WINE_ALLOW_UFFD_WRITEWATCH" ))
    {
        use_kernel_writewatch = 0;
        return;
    }
'''

SHM_ANCHOR = "WINE_DECLARE_DEBUG_CHANNEL(virtual_ranges);"
UFFD_LINE = "uffd_fd = syscall( __NR_userfaultfd"


def note(item, msg):
    print("[termux-uffd-shm] %s: %s" % (item, msg), flush=True)


def inject_shm(src):
    if SHM_MARK in src:
        return src, "SKIP: already present"
    i = src.find(SHM_ANCHOR)
    if i < 0:
        return src, "WARN: anchor not found (virtual_ranges)"
    k = src.find("\n", i)
    src = src[:k + 1] + SHM_BLOCK + src[k + 1:]
    return src, "OK: shm_open override inserted"


def inject_watch(src):
    if WATCH_MARK in src:
        return src, "SKIP: already present"
    if "use_kernel_writewatch" not in src:
        return src, "WARN: use_kernel_writewatch not in file"
    i = src.find(UFFD_LINE)
    if i < 0:
        return src, "WARN: uffd syscall line not found"
    ls = src.rfind("\n", 0, i) + 1  # 行首
    src = src[:ls] + WATCH_BLOCK + src[ls:]
    return src, "OK: writewatch disable guard inserted"


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <wine-source-dir> [--dry-run]" % sys.argv[0])
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    path = os.path.join(root, REL)
    if not os.path.isfile(path):
        note("find", "SKIP: %s missing" % REL)
        return 0
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    orig = src
    src, m1 = inject_shm(src)
    src, m2 = inject_watch(src)
    note("shm", m1)
    note("watch", m2)
    if src == orig:
        note("write", "no change")
        return 0
    if dry:
        note("dry-run", "would write %d -> %d bytes" % (len(orig), len(src)))
        return 0
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    note("write", "done: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())