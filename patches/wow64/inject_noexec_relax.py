#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Termux/noexec: 允许 noexec 文件系统上的映射回退 read()（Pipetto b0fdd49f 适配）。

来源
----
Pipetto-crypto/wine commit b0fdd49fdea779ce5678256ac45f57f881214b02
("ntdll: allow running from pages without PROT_EXEC")。
原补丁删除 map_file_into_view() 的 EACCES/EPERM 分支中“拒绝映射”的代码，
使 noexec 挂载（如 /sdcard）上的映像继续走 anon mmap + pread 回退。

这按内容锚点做等价移植，覆盖两种代数变体：
  A. 旧树(10.x)：if (vprot & VPROT_WRITE) { if (prot & PROT_EXEC) ERR(...); return STATUS_ACCESS_DENIED; }
  B. 新树(11.x)：if (vprot & VPROT_WRITE) return STATUS_ACCESS_DENIED;
检测：已含标记 -> 跳过（幂等）；map_file_into_view 内已无该拦截（如 Pipetto
树自带）-> 跳过（已存在）。找不到锚点 -> 跳过（不阻断构建）。

用法: inject_noexec_relax.py <wine-source-dir> [--dry-run]
"""
import io
import os
import sys

REL = "dlls/ntdll/unix/virtual.c"
MARK = "noexec relax"
FUNC = "static NTSTATUS map_file_into_view"
CASE = "case EPERM:"
DENY = "return STATUS_ACCESS_DENIED;"
NOTE_LINE = "            /* [noexec relax] noexec-fs mappings fall back to read() (Pipetto b0fdd49f) */\n"


def note(item, msg):
    print("[noexec-relax] %s: %s" % (item, msg), flush=True)


def apply(src):
    i = src.find(FUNC)
    if i < 0:
        return src, "SKIP: map_file_into_view not found"
    j = src.find(CASE, i)
    if j < 0:
        return src, "SKIP: case EPERM not found"
    # 限制在 EACCES/EPERM case 区域（到下一个 default: 为止），避免误伤后续函数
    dflt = src.find("default:", j)
    lim = dflt if dflt > 0 else j + 800
    k = src.find(DENY, j, lim)
    if k < 0:
        return src, "SKIP: already relaxed (no ACCESS_DENIED in EACCES/EPERM branch)"
    g = src.rfind("if (vprot & VPROT_WRITE", j, k)
    if g < 0:
        return src, "SKIP: deny present but guard not found (structure changed)"
    ls = src.rfind("\n", 0, g) + 1
    line_end = src.find("\n", g)
    if line_end < 0:
        return src, "SKIP: line end not found"
    after = src[g:line_end]
    if after.strip().endswith(";"):
        out = src[:ls] + NOTE_LINE + src[line_end + 1:]
        return out, "OK: single-line deny removed"
    close = src.find("}", k)
    if close < 0:
        return src, "SKIP: block close not found"
    ce = src.find("\n", close)
    if ce < 0:
        return src, "SKIP: block close newline not found"
    out = src[:ls] + NOTE_LINE + src[ce + 1:]
    return out, "OK: block deny removed"


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
    if MARK in src:
        note("idempotent", "already contains marker -> skip")
        return 0
    orig = src
    src, msg = apply(src)
    note("apply", msg)
    if "OK:" not in msg:
        note("result", "no change")
        return 0
    if dry:
        note("dry-run", "would write %d -> %d bytes" % (len(orig), len(src)))
        return 0
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    note("write", "done: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())