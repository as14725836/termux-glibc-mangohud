#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编译期彻底禁用 Proton 的 ntsync / inproc_sync 框架。

背景
----
Proton 系（含 dawn.wine 的 dwproton）在 server/ 里加了一套上游 Wine 没有的
in-process 同步框架：

  server/inproc_sync.c   + server/ntsync_tmp.h

它有两个后端，由 ntsync_tmp.h 里是否定义 NTSYNC_IOC_EVENT_READ 决定：

  * 定义   -> 走 /dev/ntsync 内核驱动 + NTSYNC_IOC_* ioctl（真实现）
  * 未定义 -> 整块退化成安全 stub：get_inproc_device_fd() 返回 -1，
              create_inproc_*() 返回 NULL，signal/reset 都是空函数

也就是说：**只要编译期让 NTSYNC_IOC_EVENT_READ 不生效**，整套框架就
自动变成 no-op，行为等价于上游 Wine / wine-staging，不需要改任何调用点。

为什么在 box64 + Termux 下需要禁用它
------------------------------------
即使运行时设了 PROTON_NO_NTSYNC=1（只是让 get_inproc_device_fd() 返回 -1），
真实现那一份代码仍然被编译进去并被调用到（例如 thread.c 里
get_inproc_sync_fd()、alert_sync 相关路径、get_inproc_alert_fd 请求）。
在 box64 下这些路径会崩：

    wireserver: using server-side synchronization.
    wineserver crashed, please enable coredumps ... and restart.
    wine client error:0: recvmsg: Connection reset by peer

对照实验（同一位 box64、同为 x86_64 wow64 产物）：
    wine-proton-9.0   : 无 inproc_sync/ntsync   -> 能跑
    wine 11.18        : 无 inproc_sync/ntsync   -> 能跑
    dwproton 11.0     : 有 inproc_sync/ntsync   -> 崩
    dwproton + PROTON_NO_NTSYNC=1               -> 仍崩（真实现仍被编入）

做法
----
在 server/ntsync_tmp.h 里，把 NTSYNC_IOC_EVENT_READ 的定义整体注释掉，
让 inproc_sync.c 的 #ifdef NTSYNC_IOC_EVENT_READ 判定为假，从而选中
文件末尾那套安全 stub 实现。

幂等
----
以 'NTSYNC_DISABLED_FOR_TERMUX' 作为标记；已注入则跳过。

用法:
    inject_disable_ntsync.py <wine-source-dir> [--dry-run]
"""
import os
import re
import sys

REL = "server/ntsync_tmp.h"
MARK = "NTSYNC_DISABLED_FOR_TERMUX"

# 匹配  define NTSYNC_IOC_EVENT_READ ...（整行，含续行）
DEF_RE = re.compile(
    r"^([ \t]*)#[ \t]*define[ \t]+NTSYNC_IOC_EVENT_READ\b.*(?:\n[ \t]*\\\n.*)*",
    re.M)


def note(item, msg):
    print("[no-ntsync] %s: %s" % (item, msg), flush=True)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <wine-source-dir> [--dry-run]" % sys.argv[0])
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    path = os.path.join(root, REL)
    if not os.path.isfile(path):
        note("find", "SKIP: %s 不存在（非 Proton 树）" % REL)
        return 0

    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()

    if MARK in src:
        note("idempotent", "已注入 %s → 跳过" % MARK)
        return 0

    m = DEF_RE.search(src)
    if not m:
        note("find", "SKIP: 未找到 #define NTSYNC_IOC_EVENT_READ")
        return 0

    orig = m.group(0)
    banner = (
        "/* %s\n"
        " * Termux/box64: 整体禁用 Proton 的 ntsync / inproc_sync 框架。\n"
        " * 注释掉 NTSYNC_IOC_EVENT_READ 会让 server/inproc_sync.c 选中最末尾\n"
        " * 那套安全 stub 实现（get_inproc_device_fd() 返回 -1、create_inproc_*()\n"
        " * 返回 NULL、signal/reset 为空函数），行为与上游 Wine / wine-staging\n"
        " * 一致 —— 两者在同一位 box64 下都能正常启动 wineserver。\n"
        " */\n" % MARK)
    new_block = banner + "/* " + orig.replace("*/", "* /") + " */\n"

    new_src = src[:m.start()] + new_block + src[m.end():]

    if dry:
        note("dry-run", "would comment out %d bytes of NTSYNC_IOC_EVENT_READ define" % len(orig))
        return 0

    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(new_src)
    note("write", "已注释 NTSYNC_IOC_EVENT_READ → inproc_sync.c 改走安全 stub")
    return 0


if __name__ == "__main__":
    sys.exit(main())
