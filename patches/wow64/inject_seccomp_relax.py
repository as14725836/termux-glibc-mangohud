#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seccomp/install_bpf: 放宽低地址拒绝 + 测试 mmap 不限地址（Pipetto 441c0fe6 适配）。

来源
----
Pipetto-crypto/wine commit 441c0fe673de0a640e176110d9442e8e41250fd7
("ntdll: syscall patch")，改 dlls/ntdll/unix/signal_x86_64.c 的 install_bpf()：

  1) 删除“native libs 被加载到低地址（< 0x700000000000）就拒绝安装 seccomp”
     的早退检查——该检查会在低 VA（39-bit/自定义布局）与模拟器环境下误触发，
     导致 seccomp 不装、WOW64 syscall 过滤缺失。
  2) 测试 syscall 的 mmap 从固定地址 0x600000000000 改为 NULL（任意地址），
     判断条件从 `!= 0x600000000000` 改为 `== MAP_FAILED`——否则固定地址占用/
     布局变化时误判“无法分配测试页”。

适用性：仅对仍保留旧 install_bpf 的树生效（如 Kron4ek wine-tkg fsync）。
上游 11.x 已移除该机制（改为 PR_SET_SYSCALL_USER_DISPATCH），本脚本检测
不到锚点即跳过，不阻断构建。Pipetto 树已自带 → 幂等跳过。

用法: inject_seccomp_relax.py <wine-source-dir> [--dry-run]
"""
import io
import os
import sys

REL = "dlls/ntdll/unix/signal_x86_64.c"
MARK = "seccomp relax"
LOW_HEAD = "    if ((ULONG_PTR)sc_seccomp < NATIVE_SYSCALL_ADDRESS_START"
MMAP_OLD = "test_syscall = mmap((void *)0x600000000000, 0x1000, PROT_EXEC | PROT_READ | PROT_WRITE,"
MMAP_NEW = "test_syscall = mmap(NULL, 0x1000, PROT_EXEC | PROT_READ | PROT_WRITE,"
CMP_OLD = "if (test_syscall != (void *)0x600000000000)"
CMP_NEW = "if (test_syscall == MAP_FAILED)"
NOTE_LINE = "    /* [seccomp relax] allow low-address native libs (Pipetto 441c0fe6) */\n"


def note(item, msg):
    print("[seccomp-relax] %s: %s" % (item, msg), flush=True)


def remove_if_block(src, head_idx):
    """删除从 head_idx（行首）开始的整个 if 语句块（花括号配对）。"""
    brace = src.find("{", head_idx)
    if brace < 0:
        return src, False
    depth = 0
    i = brace
    end = -1
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end < 0:
        return src, False
    e = src.find("\n", end)
    if e < 0:
        return src, False
    return src[:head_idx] + src[e + 1:], True


def apply(src):
    changed = []
    i = src.find(LOW_HEAD)
    if i >= 0:
        ls = src.rfind("\n", 0, i) + 1
        src, ok = remove_if_block(src, ls)
        if ok:
            src = src[:ls] + NOTE_LINE + src[ls:]
            changed.append("low-address guard removed")
    if MMAP_OLD in src:
        src = src.replace(MMAP_OLD, MMAP_NEW, 1)
        changed.append("test mmap -> NULL")
    if CMP_OLD in src:
        src = src.replace(CMP_OLD, CMP_NEW, 1)
        changed.append("cmp -> MAP_FAILED")
    return src, changed


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
    if "install_bpf" not in src:
        note("find", "SKIP: install_bpf not present (newer upstream) -> nothing to do")
        return 0
    orig = src
    src, changed = apply(src)
    if not changed:
        note("apply", "SKIP: no anchors matched (structure differs / already patched)")
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