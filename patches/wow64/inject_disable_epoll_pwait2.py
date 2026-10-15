#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""禁用 wineserver 对 epoll_pwait2 的使用，退回 epoll_wait。

背景
----
Wine 10.x 起，server/fd.c 的 main_loop_epoll() 会用 epoll_pwait2
（Linux 5.11+，支持纳秒级超时）：

    __attribute__((weak)) int epoll_pwait2( int, struct epoll_event *, int,
                                            const struct timespec *, const sigset_t * );
    ...
    int use_epoll_pwait2 = !!epoll_pwait2;
    if (use_epoll_pwait2 && epoll_pwait2( -1, events, 0, NULL, NULL ) == -1 && errno == ENOSYS)
        use_epoll_pwait2 = 0;
    ...
    if (use_epoll_pwait2) ret = epoll_pwait2( epoll_fd, events, ARRAY_SIZE( events ), ... );
    else                  ret = epoll_wait( epoll_fd, events, ARRAY_SIZE( events ), timeout );

探测那一步是**故意传 fd = -1**，期望内核返回 EBADF 或 ENOSYS。

box64 v0.4.5 的问题
-------------------
box64 对 epoll_pwait2 的 wrapper 没有处理 fd = -1 这种“故意非法”的入参，
在 wrapper 内部 +0x13 处直接解引用空指针，于是：

    [BOX64] 32510|SIGSEGV @... (epoll_pwait2) ... for accessing (nil)
            RDI:0x00000000ffffffff              <- fd = -1
            x64pc=... "box64/epoll_pwait2 + 0x13"
    wineserver crashed, please enable coredumps (ulimit -c unlimited) and restart.
    wine client error:0: recvmsg: Connection reset by peer

wineserver 自己的 SIGSEGV handler 收到信号后 abort()（SIGABRT），
进程死亡，客户端 recvmsg 就报 Connection reset by peer。

对照实验（同一台设备、同一 box64、同为 x86_64 wow64 产物）：
    wine-proton-9.0（无 epoll_pwait2 探测） -> 能跑
    wine-staging-11.18                      -> 能跑
    dwproton 11.0（有 -1 探测）             -> 崩

修复
----
把 use_epoll_pwait2 的探测整段改成直接 0，等价于“这台内核没有
epoll_pwait2”，于是 main_loop 一直走 epoll_wait 分支。
epoll_wait 在所有 Linux/Android 内核上都可用，wine 用了十几年。

幂等
----
以 'NO_EPOLL_PWAIT2_FOR_TERMUX' 作为标记；已注入则跳过。

用法:
    inject_disable_epoll_pwait2.py <wine-source-dir> [--dry-run]
"""
import os
import re
import sys

REL = "server/fd.c"
MARK = "NO_EPOLL_PWAIT2_FOR_TERMUX"

# 匹配探测整段（两种可能写法）
PROBE_RE = re.compile(
    r"([ \t]*)int[ \t]+use_epoll_pwait2[ \t]*=[ \t]*!!epoll_pwait2[ \t]*;[ \t]*\n"
    r"(?:[ \t]*if[ \t]*\([ \t]*use_epoll_pwait2[^\n]*\n"
    r"(?:[ \t]*use_epoll_pwait2[ \t]*=[ \t]*0[ \t]*;[ \t]*\n)?"
    r")?")

REPLACEMENT = (
    "{indent}int use_epoll_pwait2 = 0; /* {mark}\n"
    "{indent} * Termux/box64: box64 v0.4.5 的 epoll_pwait2 wrapper 在 fd=-1 时\n"
    "{indent} * 解引用空指针（探测调用 apoll_pwait2(-1,...) -> SIGSEGV -> abort），\n"
    "{indent} * 导致 wineserver 一启动就崩。这里直接认定不可用，退回 epoll_wait。 */\n"
).format(indent="{indent}", mark=MARK)


def note(item, msg):
    print("[no-epoll2] %s: %s" % (item, msg), flush=True)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <wine-source-dir> [--dry-run]" % sys.argv[0])
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    path = os.path.join(root, REL)
    if not os.path.isfile(path):
        note("find", "SKIP: %s 不存在" % REL)
        return 0

    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()

    if MARK in src:
        note("idempotent", "已注入 %s → 跳过" % MARK)
        return 0

    m = PROBE_RE.search(src)
    if not m:
        note("find", "SKIP: 未找到 use_epoll_pwait2 探测段（该树不用 epoll_pwait2）")
        return 0

    indent = m.group(1)
    new_block = REPLACEMENT.replace("{indent}", indent)
    new_src = src[:m.start()] + new_block + src[m.end():]

    if dry:
        note("dry-run", "would replace %d bytes of epoll_pwait2 probe with use_epoll_pwait2=0"
             % len(m.group(0)))
        return 0

    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(new_src)
    note("write", "已禁用 epoll_pwait2 探测 → 退回 epoll_wait")
    return 0


if __name__ == "__main__":
    sys.exit(main())
