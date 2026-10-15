#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""禁掉 Proton 在 accept_new_client() 里的 SO_PEERCRED 客户端进程树追踪。

为什么
------
dwproton / Proton 系在 server/request.c 的 accept_new_client() 里加了一段
上游 Wine 没有的代码：

    #ifdef SO_PEERCRED
    {
        struct ucred ucred;
        len = sizeof(ucred);
        if (!getsockopt( client, SOL_SOCKET, SO_PEERCRED, &ucred, &len ))
        {
            sprintf( s, "/proc/%d/status", ucred.pid );
            ... get_thread_from_pid( ppid ) ...
        }
    }
    #endif
    ...
    if ((process = create_process( client, thread ? thread->process : NULL, ... )))

它靠 SO_PEERCRED 反查发起连接客户端的父进程，用来把 Steam 的进程树映射
到 Wine 的进程结构上。

在 box64 + Termux 环境下这个假设不成立：
  * box64 对 getsockopt(SO_PEERCRED) 的 struct ucred 翻译不可靠，
    ucred.pid 可能是 0 或错误值；
  * /proc/<pid>/status 的 PPid 在 box64 的父子进程映射下也不对应
    Wine 自己的 thread 列表；
  * 于是 thread 乱指，create_process() 传入错误的 thread->process，
    最终 wineserver 在第一次 accept 客户端时就 SIGSEGV：
        wineserver crashed, please enable coredumps ...
        wine client error:0: recvmsg: Connection reset by peer

修复
----
把 SO_PEERCRED 那一段整体编译期剔除（#if 0 ... #endif），让代码退回
上游 Wine 的行为：thread = NULL，create_process(client, NULL, ...)。
这是最保守、也是上游一直在用的路径。

幂等
----
以 'PROTON_NO_PEERCRED_DISABLED' 注释作为标记；已注入则跳过。

用法:
    inject_disable_peercred.py <wine-source-dir> [--dry-run]
"""
import os
import re
import sys

REL = "server/request.c"
MARK = "PROTON_NO_PEERCRED_DISABLED"

# 匹配整段：
#   #ifdef SO_PEERCRED
#   {
#       ...
#   }
#   #endif
BLOCK_RE = re.compile(
    r"[ \t]*#ifdef[ \t]+SO_PEERCRED[ \t]*\n"
    r".*?"
    r"[ \t]*#endif[ \t]*\n",
    re.S)

REPLACEMENT = """\
/* PROTON_NO_PEERCRED_DISABLED
 * Termux/box64: Proton 靠 SO_PEERCRED 反查客户端父进程来重建 Steam 进程树。
 * box64 下 getsockopt(SO_PEERCRED) 的 struct ucred 与 /proc/<pid>/status
 * 的 PPid 都不可靠，会让 thread 指向错误的 process，导致 wineserver 在
 * 第一次 accept 客户端时崩溃（recvmsg: Connection reset by peer）。
 * 这里整体剔除，退回上游 Wine 行为：thread = NULL。 */
#if 0
#ifdef SO_PEERCRED
        {
            struct ucred ucred;

            len = sizeof(ucred);
            if (!getsockopt( client, SOL_SOCKET, SO_PEERCRED, &ucred, &len ))
            {
                pid_t ppid;
                char s[256];
                FILE *f;

                sprintf( s, "/proc/%d/status", ucred.pid );
                if ((f = fopen( s, "r" )))
                {
                    while (fgets( s, sizeof(s), f ))
                    {
                        if (sscanf( s, "PPid:%d", &ppid ) != 1) continue;
                        thread = get_thread_from_pid( ppid );
                        break;
                    }
                    fclose( f );
                }
            }
        }
#endif
#endif /* PROTON_NO_PEERCRED_DISABLED */
"""


def note(item, msg):
    print("[no-peercred] %s: %s" % (item, msg), flush=True)


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

    m = BLOCK_RE.search(src)
    if not m:
        note("find", "SKIP: 未找到 #ifdef SO_PEERCRED 块（非 Proton 树或已被上游移除）")
        return 0

    if "SO_PEERCRED" not in m.group(0) or "get_thread_from_pid" not in m.group(0):
        note("find", "SKIP: 匹配到的块内容与预期不符 → 跳过")
        return 0

    new_src = src[:m.start()] + REPLACEMENT + src[m.end():]

    if dry:
        note("dry-run", "would disable %d bytes of SO_PEERCRED block" % len(m.group(0)))
        return 0

    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(new_src)
    note("write", "已禁用 SO_PEERCRED 客户端进程树追踪（退回上游行为）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
