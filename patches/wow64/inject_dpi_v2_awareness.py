#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""user32/sysparams: PER_MONITOR_AWARE_V2 正确处理（Pipetto a7392da8 适配）。

来源
----
Pipetto-crypto/wine commit a7392da8c7aec45b7d0b2c8419684bf764dc2310
("sysparams: Handle DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 properly")，
在 GetAwarenessFromDpiAwarenessContext() 的旧 switch 版里：
  1) 补 case 0x8000022（V2 的哈希形式）到 "& 3" 分支；
  2) 新增 case (ULONG_PTR)DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 ->
     返回 PER_MONITOR_AWARE 的取反值。

适用性：
  * 仅对**旧 switch 版**（含 "case 0x80000012" 且缺 "0x8000022"）生效。
  * 上游 wine 11.x / WinNative：user32 已重构为 NTUSER_DPI_CONTEXT_GET_AWARENESS
    宏实现（V2 天然正确处理）-> 跳过。
  * Pipetto 树已自带 -> 幂等跳过。
  * 找不到旧 switch -> 跳过，不阻断构建。

用法: inject_dpi_v2_awareness.py <wine-source-dir> [--dry-run]
"""
import io
import os
import sys

REL = "dlls/user32/sysparams.c"
MARK = "0x8000022"
OLD_ANCHOR = "    case 0x80000012:\n        return (ULONG_PTR)context & 3;\n"
NEW_1 = "    case 0x80000012:\n    case 0x8000022:\n        return (ULONG_PTR)context & 3;\n"
V2_ANCHOR = (
    "    case (ULONG_PTR)DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE:\n"
    "        return ~(ULONG_PTR)context;\n"
)
V2_NEW = (
    "    case (ULONG_PTR)DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE:\n"
    "        return ~(ULONG_PTR)context;\n"
    "    case (ULONG_PTR)DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2:\n"
    "        return ~(ULONG_PTR)DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE;\n"
)


def note(item, msg):
    print("[dpi-v2] %s: %s" % (item, msg), flush=True)


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
        note("idempotent", "already contains 0x8000022 -> skip")
        return 0
    if "case 0x80000012" not in src:
        note("find", "SKIP: no legacy switch (reworked upstream) -> nothing to do")
        return 0
    orig = src
    changed = []
    if OLD_ANCHOR in src:
        src = src.replace(OLD_ANCHOR, NEW_1, 1)
        changed.append("0x8000022 case added")
    # V2 注入守卫：若已存在 V2 case（不管尾部空格），跳过以免重复
    if "(ULONG_PTR)DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2:" not in src:
        if V2_ANCHOR in src:
            src = src.replace(V2_ANCHOR, V2_NEW, 1)
            changed.append("PER_MONITOR_AWARE_V2 case added")
    else:
        note("v2-guard", "V2 case already present, skip insert")
    if not changed:
        note("apply", "SKIP: anchors not matched")
        return 0
    note("apply", "OK: " + ", ".join(changed))
    if dry:
        note("dry-run", "would write %d -> %d bytes" % (len(orig), len(src)))
        return 0
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    note("write", "done: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())