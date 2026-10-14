#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 Wine 的 dlls/ntdll/unix/virtual.c 注入 WINEVMEMMAXSIZE 支持（幂等）。

来源
----
Pipetto-crypto/wine f9224d6b643cf43430559b296064480e4b883bd8
("virtual: add WINEVMEMMAXSIZE") 的语义等价移植：
  1) 全局 static SIZE_T vmem_max_size = 0（0 = 不限制）；
  2) virtual_init() 末尾读环境变量 WINEVMEMMAXSIZE（单位 MiB -> <<20）；
  3) allocate_virtual_memory() 中单次分配 size 超出上限时返回
     STATUS_WORKING_SET_LIMIT_RANGE。

为什么用锚点注入而不是 patch -p1
--------------------------------
原 commit 针对 2025-03 的源码树；wine 9/10/11（含 Proton/TKG/vanilla）
各行号与上下文已漂移，实测无法整份干净应用。本仓库对 virtual.c 的其它
补丁（box64 icache 等）同样采用内容锚点注入。

幂等
----
已包含 WINEVMEMMAXSIZE 的树（如 Pipetto proton-9.0-x86_64 已自带）直接
跳过，不重复注入。

用法
----
    python3 inject_vmem_max_size.py <wine_source_root> [--dry-run]

退出码：0=完成/跳过；2=锚点缺失（不写文件）
"""
import os, re, sys

REL = "dlls/ntdll/unix/virtual.c"
DECL_ANCHOR = re.compile(
    r"(static void \*host_addr_space_limit;[^\n]*\n)(\n)(static struct file_view \*arm64ec_view;)")
DECL_NEW = ("static void *host_addr_space_limit;  /* top of the host virtual address space */\n"
    "static SIZE_T vmem_max_size = 0;  /* WINEVMEMMAXSIZE: cap largest single allocation, 0 = disabled */\n"
    "\n"
    "static struct file_view *arm64ec_view;")
INIT_ENV = ("\n    /* WINEVMEMMAXSIZE: cap largest single allocation (MiB), 0/unset = stock behaviour */\n"
    "    {\n"
    "        const char *vmem_max_size_env = getenv( \"WINEVMEMMAXSIZE\" );\n"
    "        if (vmem_max_size_env && *vmem_max_size_env)\n"
    "        {\n"
    "            vmem_max_size = (SIZE_T)strtol( vmem_max_size_env, NULL, 10 ) << 20;\n"
    "            TRACE( \"virtual memory max size: %lu\\n\", (unsigned long)vmem_max_size );\n"
    "        }\n"
    "    }\n")
LIMIT_OLD = "if (is_beyond_limit( 0, size, working_set_limit )) return STATUS_WORKING_SET_LIMIT_RANGE;"
LIMIT_NEW = ("if (is_beyond_limit( 0, size, working_set_limit ) || (vmem_max_size > 0 && size > vmem_max_size))\n"
    "        return STATUS_WORKING_SET_LIMIT_RANGE;")

def note(item, msg): print("[WINEVMEMMAXSIZE] %s: %s" % (item, msg))

def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: inject_vmem_max_size.py <wine-source-dir> [--dry-run]")
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    path = os.path.join(root, REL)
    if not os.path.isfile(path):
        note("find", "SKIP: %s missing" % REL); return 0
    text = open(path, encoding="utf-8", errors="surrogateescape").read()
    orig = text
    if "WINEVMEMMAXSIZE" in text:
        note("idempotent", "already contains WINEVMEMMAXSIZE -> skip"); return 0
    ok = True
    m = DECL_ANCHOR.search(text)
    if m:
        text = DECL_ANCHOR.sub(DECL_NEW, text, count=1); note("decl", "OK: vmem_max_size inserted")
    else:
        m2 = re.search(r"static void \*host_addr_space_limit;[^\n]*\n", text)
        if m2:
            text = text[:m2.end()] + "static SIZE_T vmem_max_size = 0;  /* WINEVMEMMAXSIZE */\n" + text[m2.end():]
            note("decl", "OK: inserted (fallback)")
        else:
            note("decl", "FAIL: anchor not found"); ok = False
    pat_a = "free_ranges_end = free_ranges + 1;\n}"
    pat_b = "free_ranges_end = free_ranges + 1;\n\n    /* make the DOS area accessible"
    if pat_a in text:
        text = text.replace(pat_a, "free_ranges_end = free_ranges + 1;\n" + INIT_ENV + "}", 1)
        note("init", "OK: env block inserted (direct tail)")
    elif pat_b in text:
        text = text.replace(pat_b, "free_ranges_end = free_ranges + 1;" + INIT_ENV + "\n    /* make the DOS area accessible", 1)
        note("init", "OK: env block inserted (before DOS block)")
    else:
        fi = text.find("void virtual_init(void)")
        if fi >= 0:
            depth = 0; started = False; end = -1; i = fi
            while i < len(text):
                c = text[i]
                if c == "{": depth += 1; started = True
                elif c == "}":
                    depth -= 1
                    if started and depth == 0: end = i; break
                i += 1
            if end > 0:
                text = text[:end] + INIT_ENV + text[end:]; note("init", "OK: inserted (brace-match)")
            else:
                note("init", "FAIL: brace match failed"); ok = False
        else:
            note("init", "FAIL: virtual_init not found"); ok = False
    if LIMIT_OLD in text:
        text = text.replace(LIMIT_OLD, LIMIT_NEW, 1); note("limit", "OK: size cap injected")
    elif "vmem_max_size > 0" in text:
        note("limit", "SKIP: already present")
    else:
        note("limit", "FAIL: is_beyond_limit anchor not found"); ok = False
    if dry:
        note("dry-run", "anchors OK; would write %d -> %d bytes" % (len(orig), len(text)))
        return 0 if ok else 2
    if not ok:
        note("abort", "some anchor failed -> file NOT written"); return 2
    open(path, "w", encoding="utf-8", errors="surrogateescape").write(text)
    note("write", "done: %s" % path)
    return 0

if __name__ == "__main__":
    sys.exit(main())
