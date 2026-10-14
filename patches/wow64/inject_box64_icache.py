#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为 Wine 的 dlls/ntdll/unix/virtual.c 注入 box64 指令缓存失效补丁。

为什么需要它
------------
Wine 编成 x86_64 时，dlls/ntdll/unix/virtual.c 里：

    #if defined(__x86_64__) || defined(__i386__)
        /* no-op */
    #elif defined(HAVE___CLEAR_CACHE)
        ...

把 NtFlushInstructionCache() 当成空操作。这在真 x86_64 CPU 上是对的
（x86 的 store 与指令缓存硬件一致），但在 box64 下不成立：guest 镜像被
翻译成 box64 自己缓存里的宿主代码，没有任何 CPU 机制会失效那份翻译。
加壳程序自解密后调用这个 API 来“发布”刚写好的代码，于是 box64 继续跑
过期的 dynablock。

box64 唯一当作“代码变了”的信号，是某段内存范围的 PROT_EXEC 被清掉
（src/custommem.c 的 updateProtection()）：

    if(((prot ^ oprot) & PROT_EXEC) && !(prot&PROT_EXEC)) ... 失效 ...

而 guest 调 mprotect 会走到 box64 的 my_mprotect()
（src/emu/x64syscall.c: case 10 -> my_mprotect），所以从 Wine 侧
清一次再恢复 PROT_EXEC，就能借这条既有通道让 box64 丢弃对应 dynablock。

实现
----
helper 按页降为 read/write 再逐页恢复“它原本的保护位”：
  * 逐页而非两趟全范围，缩短代码不可执行的窗口；
  * 恢复原始位而不是硬写 RX —— PAGE_EXECUTE_READ 的范围不能悄悄变成可写；
  * 只有带 VPROT_EXEC 的页才动手，纯数据 flush 零开销；
  * WINE_BOX64_ICACHE_BOUNCE=0 可关闭。

为什么不用 patch -p1
--------------------
Wine 9.0 / 9.20 / 10.x / 11.x 的 virtual.c 行号差异极大（6298 / 7004 /
6576 …），但 NtFlushInstructionCache 的 x86 分支骨架、mprotect_exec 定义、
get_page_vprot 定义、VPROT_* 常量在所有版本里逐字相同。所以用内容锚点定位。
脚本幂等：已注入过直接成功返回。

用法
----
    python3 inject_box64_icache.py <wine 源码根目录>

失败一律 exit 1 —— 绝不能静默放过，否则会产出一个“看起来打了补丁”的错误
二进制。
"""

import os
import sys

HELPER = r'''
/***********************************************************************
 *           box64_icache_bounce
 *
 * [box64] Publish a rewritten code range to an emulator that keeps its own
 * translation of the guest image.  See NtFlushInstructionCache below.
 *
 * box64 reacts to exactly one thing: PROT_EXEC being cleared on a range
 * (updateProtection() in its custommem.c).  So the range is dropped to
 * read/write and restored page by page to the protection it already had.
 *
 * Ranges that are not executable carry no translation and are rejected
 * before any syscall, which keeps the hook free for ordinary data flushes.
 */
static BOOL box64_icache_bounce( void *addr, size_t size )
{
    static int enabled = -1;
    long page;
    char *start, *end, *p;

    if (enabled < 0)
    {
        const char *e = getenv( "WINE_BOX64_ICACHE_BOUNCE" );
        enabled = !e || (e[0] != '0' && e[0] != 'n' && e[0] != 'N' &&
                         e[0] != 'f' && e[0] != 'F');
    }
    if (!enabled || !addr || !size) return FALSE;

    page = sysconf( _SC_PAGESIZE );
    if (page <= 0) return FALSE;
    start = (char *)((uintptr_t)addr & ~((uintptr_t)page - 1));
    end   = (char *)(((uintptr_t)addr + size + page - 1) & ~((uintptr_t)page - 1));
    if (end <= start) return FALSE;                 /* wrap-around */

    /* Anything without VPROT_EXEC has never been translated by box64. */
    for (p = start; p < end; p += page)
        if (get_page_vprot( p ) & VPROT_EXEC) break;
    if (p >= end) return FALSE;

    /* Bounce one page at a time, alternating clear/restore.  Doing it per
     * page rather than as two whole-range passes keeps the window in which
     * the code is non-executable as short as possible, and lets each page be
     * restored to the exact protection it had - a PAGE_EXECUTE_READ range
     * must not silently come back writable. */
    for (p = start; p < end; p += page)
    {
        BYTE vprot = get_page_vprot( p );
        int unix_prot = 0;
        if (!(vprot & VPROT_EXEC)) continue;      /* nothing was translated */

        if (vprot & VPROT_READ)  unix_prot |= PROT_READ;
        if (vprot & VPROT_WRITE) unix_prot |= PROT_WRITE;

        /* Clear PROT_EXEC: this is what makes box64 drop the blocks. */
        mprotect_exec( p, page, unix_prot | PROT_WRITE );

        /* Put PROT_EXEC back together with the original bits. */
        if (mprotect_exec( p, page, unix_prot | PROT_EXEC ) ||
            !(get_page_vprot( p ) & VPROT_EXEC))
            ERR( "box64 icache bounce: cannot restore exec on %p: %s\n",
                 p, strerror( errno ) );
    }

    if (TRACE_ON( virtual ))
        TRACE( "box64 icache bounce on %p-%p\n", start, end );
    return TRUE;
}

'''

NEW_CALL = r'''#if defined(__x86_64__) || defined(__i386__)
    /* [box64] On a real x86_64 CPU the instruction cache is coherent with
     * stores, so this is a no-op by definition.  Under box64 it is not: the
     * guest image is translated into host code held in box64's own cache,
     * and no CPU mechanism invalidates that.  A packer that decrypts its own
     * code relies on this call to publish the result, so route it through
     * the one operation box64 treats as "code changed".  Nothing happens for
     * a non-executable range, and WINE_BOX64_ICACHE_BOUNCE=0 disables it. */
    if (handle == GetCurrentProcess() || handle == 0)
        box64_icache_bounce( (void *)addr, size );
'''

OLD_CALL = r'''#if defined(__x86_64__) || defined(__i386__)
    /* no-op */
'''


def die(msg):
    sys.stderr.write("FATAL: %s\n" % msg)
    sys.exit(1)


def must_find(hay, needle, label):
    n = hay.count(needle)
    if n == 0:
        die("anchor not found: %s" % label)
    if n > 1:
        die("anchor ambiguous (%d hits): %s" % (n, label))
    return hay.index(needle)


def main():
    if len(sys.argv) != 2:
        die("usage: %s <wine-source-root>" % sys.argv[0])
    root = sys.argv[1]
    path = os.path.join(root, "dlls", "ntdll", "unix", "virtual.c")
    if not os.path.isfile(path):
        die("not found: %s" % path)

    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()

    # --- 幂等 -----------------------------------------------------------
    if "box64_icache_bounce" in src:
        print("OK: box64_icache_bounce already present, nothing to do")
        return 0

    # --- helper 依赖的符号必须都在 --------------------------------------
    for sym, label in (
        ("static inline int mprotect_exec(", "mprotect_exec definition"),
        ("get_page_vprot(", "get_page_vprot definition"),
        ("#define VPROT_EXEC", "VPROT_EXEC constant"),
        ("#define VPROT_READ", "VPROT_READ constant"),
        ("#define VPROT_WRITE", "VPROT_WRITE constant"),
    ):
        if sym not in src:
            die("required symbol missing from virtual.c: %s" % label)

    # --- 1) helper 插在 mprotect_exec 定义之后 ---------------------------
    # 它要调 mprotect_exec，所以必须排在定义后面。锚在函数头，再数大括号
    # 找函数体结尾。
    head = must_find(
        src,
        "static inline int mprotect_exec( void *base, size_t size, int unix_prot )",
        "mprotect_exec head",
    )
    brace = src.index("{", head)
    depth = 0
    i = brace
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        die("could not find end of mprotect_exec body")
    insert_at = i + 1
    src = src[:insert_at] + "\n" + HELPER + "\n" + src[insert_at:]

    # --- 2) 改写 NtFlushInstructionCache 的 x86 空操作分支 ---------------
    at = must_find(src, OLD_CALL, "NtFlushInstructionCache x86 no-op branch")
    src = src[:at] + NEW_CALL + src[at + len(OLD_CALL):]

    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(src)

    # --- 报告 + 顺序自检 -------------------------------------------------
    lines = src.split("\n")
    helper_line = next(i + 1 for i, l in enumerate(lines) if "box64_icache_bounce" in l)
    call_line = next(
        i + 1 for i, l in enumerate(lines) if "box64_icache_bounce( (void *)addr" in l
    )
    if helper_line >= call_line:
        die("helper at line %d must precede its call at line %d"
            % (helper_line, call_line))

    print("OK: injected box64 icache bounce")
    print("    helper : line %d" % helper_line)
    print("    call   : line %d" % call_line)
    print("    file   : %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
