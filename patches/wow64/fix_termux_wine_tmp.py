#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Termux glibc: 把 wineserver 的 /tmp/.wine-<uid> 目录改到 Termux 可写路径。

背景
----
Termux/Android 上 /tmp 不可写，wineserver 启动时：
    wineserver: mkdir /tmp/.wine-10521: Permission denied
Wine 自带 `#ifdef __ANDROID__` 分支，但 x86_64 glibc 构建**不会**定义
__ANDROID__（那是给 bionic/交叉编译用的），所以走 #else 的 /tmp 分支。

上游 patch11.16/termux-wine-full-11.16.patch 里有这个修复，但它是按
Wine 11.16 的行号/写法写的，套到 Wine 9.0 上 hunk 打不上 → 整份跳过。

本脚本用「内容锚点 + 字符串替换」定位，不依赖行号，覆盖：
  * dlls/ntdll/unix/server.c   init_server_dir()
  * server/request.c           create_server_dir()
两个 Wine 9.0/10.x/11.x 都存在的点。

幂等：已经是 termux 路径就直接跳过。
"""
import io, os, re, sys

TERMUX_TMP = "/data/data/com.termux/files/usr/tmp"

TARGETS = [
    # (相对路径, 说明)
    ("dlls/ntdll/unix/server.c", "init_server_dir"),
    ("server/request.c",         "create_server_dir"),
]


def patch_server_c(path):
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    if TERMUX_TMP in src:
        return "already"
    # asprintf( &dir, "/tmp/.wine-%u/server-%s", getuid(), tmp );
    # 注意: group(2) 只吃 "/.wine-%u/server-%s"，/tmp 前缀由 TERMUX_TMP 提供
    pat = re.compile(
        r'(asprintf\(\s*&dir\s*,\s*)"/tmp(/\.wine-%u/server-%s)"(\s*,\s*getuid\(\))',
        re.S)
    new, n = pat.subn(lambda m: '%s"%s%s"%s' % (m.group(1), TERMUX_TMP, m.group(2), m.group(3)), src)
    if n == 0:
        return "anchor-miss"
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(new)
    return "patched(%d)" % n


def patch_request_c(path):
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    if TERMUX_TMP in src:
        return "already"
    orig = src

    # 1) len 计算：  len += sizeof("/tmp/.wine-") + 12;
    #    ->          len += sizeof(TERMUX_WINE_TMP) + 12;
    #    直接在文件顶部注入宏，避免超长行内字符串。
    pat_len = re.compile(
        r'len\s*\+=\s*sizeof\(\s*"/tmp/\.wine-"\s*\)\s*\+\s*12\s*;')
    src, n1 = pat_len.subn('len += sizeof(WINE_TMP_PREFIX) + 12;', src)

    # 2) sprintf( server_dir, "/tmp/.wine-%u", getuid() );
    #    -> sprintf( server_dir, WINE_TMP_PREFIX "-%u", getuid() );
    pat_sp = re.compile(
        r'sprintf\(\s*server_dir\s*,\s*"/tmp/\.wine-%u"\s*,\s*getuid\(\)\s*\)\s*;')
    src, n2 = pat_sp.subn('sprintf( server_dir, WINE_TMP_PREFIX "-%u", getuid() );', src)

    if n1 == 0 and n2 == 0:
        return "anchor-miss"

    # 3) 注入宏定义（放在第一个 include 之后，保证只注一次）
    if "WINE_TMP_PREFIX" in src and "#define WINE_TMP_PREFIX" not in src:
        lines = src.split("\n")
        # 找最后一个连续 include 块的末尾
        last_inc = -1
        for i, ln in enumerate(lines[:200]):
            if re.match(r'\s*#\s*include\s', ln):
                last_inc = i
        ins = last_inc + 1 if last_inc >= 0 else 0
        lines.insert(ins,
            "\n/* Termux glibc: /tmp 不可写，wineserver 目录改到 Termux 可写路径 */\n"
            '#define WINE_TMP_PREFIX "%s/.wine"' % TERMUX_TMP)
        src = "\n".join(lines)

    if src == orig:
        return "no-change"
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    return "patched(len=%d,sprintf=%d)" % (n1, n2)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    ok = True
    for rel, what in TARGETS:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            print("SKIP: %s 不存在 (%s)" % (rel, what))
            continue
        if rel.endswith("server.c"):
            r = patch_server_c(p)
        else:
            r = patch_request_c(p)
        print("%-12s %s -> %s" % (r.split("(")[0], rel, r))
        if r == "anchor-miss":
            ok = False
    if ok:
        print("OK: termux /tmp 修复完成（或无需修复）")
    else:
        print("WARN: 有锚点未命中，源码结构可能不同")
    return 0 if ok else 0   # 不因为 miss 就 fail 构建


if __name__ == "__main__":
    sys.exit(main())
