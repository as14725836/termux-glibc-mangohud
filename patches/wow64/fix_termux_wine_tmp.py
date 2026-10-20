#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Termux glibc: 把 Wine 里写死的宿主路径改到 Termux 可写/可读位置。

背景
----
Android 上 `/tmp` 不可写，wineserver 启动即失败：
    wineserver: mkdir /tmp/.wine-10521: Permission denied
Wine 自带 `#ifdef __ANDROID__` 分支，但 x86_64 glibc 构建不会定义
__ANDROID__（那是给 bionic 的），于是走 #else 的 /tmp 分支。

上游 patch11.16/termux-wine-full-11.16.patch 里的 hunk 是按 Wine 11.16
行号写的，套到 GE（Proton wine 11.0）上整份 `patch` 被跳过；本脚本用
「内容锚点 + 字符串替换」实现同一组修复，且兼容 9.x / 10.x / 11.x / GE：

  * dlls/ntdll/unix/server.c   init_server_dir()   /tmp/.wine-<uid> -> Termux tmp
                               setup_config_dir()  Z: -> Termux files, 追加 D: -> /sdcard
  * server/request.c           create_server_dir() 同上（server 侧）
  * dlls/crypt32/unixlib.c     CRYPT_knownLocations 追加 Termux CA bundle
  * server/unicode.c           nls_dirs 追加 Termux NLS 目录

幂等：已经是 Termux 路径/已经追加过就跳过。
"""
import io
import os
import re
import sys

TERMUX_TMP = "/data/data/com.termux/files/usr/tmp"
TERMUX_FILES = "/data/data/com.termux/files"
TERMUX_GLIBC = "/data/data/com.termux/files/usr/glibc"

TARGETS = [
    ("dlls/ntdll/unix/server.c", "init_server_dir/setup_config_dir"),
    ("server/request.c", "create_server_dir"),
    ("dlls/crypt32/unixlib.c", "CRYPT_knownLocations"),
    ("server/unicode.c", "nls_dirs"),
]


def _read(path):
    return io.open(path, encoding="utf-8", errors="surrogateescape").read()


def _write(path, src):
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)


def patch_server_c(path):
    src = _read(path)
    orig = src
    log = []

    # 1) asprintf( &dir, "/tmp/.wine-%u/server-%llx-%llx", ... )
    #    兼容旧的 "/tmp/.wine-%u/server-%s"
    if TERMUX_TMP not in src:
        pat = re.compile(r'(asprintf\(\s*&dir\s*,\s*)"\/tmp\/(\.wine-%u\/server-[^"]*)"')
        src, n = pat.subn(lambda m: '%s"%s/%s"' % (m.group(1), TERMUX_TMP, m.group(2)), src)
        if n:
            log.append("server_dir=%d" % n)

    # 2) 旧的 sprintf(server_dir, "/tmp/.wine-%u", getuid())
    if TERMUX_TMP not in src:
        pat = re.compile(r'(sprintf\(\s*server_dir\s*,\s*)"\/tmp\/(\.wine-%u)"')
        src, n = pat.subn(lambda m: '%s"%s/%s"' % (m.group(1), TERMUX_TMP, m.group(2)), src)
        if n:
            log.append("server_dir_sprintf=%d" % n)

    # 3) dosdevices：Z: 指到 / 在 Termux 上等于暴露 Android 根且不可用，
    #    改成 Termux files；再补一个 D: -> /sdcard（仅新建 prefix 时生效）。
    if "dosdevices/d:" not in src:
        m = re.search(r'(?m)^([ \t]*)symlink\(\s*"/"\s*,\s*"dosdevices/z:"\s*\);[ \t]*\n', src)
        if m:
            indent = m.group(1)
            repl = (
                '%ssymlink( "%s", "dosdevices/z:" );\n'
                '%ssymlink( "/sdcard", "dosdevices/d:" );\n' % (indent, TERMUX_FILES, indent)
            )
            src = src[:m.start()] + repl + src[m.end():]
            log.append("dosdevices=z,d")

    if src == orig:
        return "already" if TERMUX_TMP in orig else "anchor-miss"
    _write(path, src)
    return "patched(%s)" % ",".join(log)


def patch_request_c(path):
    src = _read(path)
    orig = src

    # 1) asprintf( &base_dir, "/tmp/.wine-%u", getuid() )   <- GE / 11.x
    if TERMUX_TMP not in src:
        pat = re.compile(r'(asprintf\(\s*&base_dir\s*,\s*)"\/tmp\/(\.wine-%u)"')
        src, n = pat.subn(lambda m: '%s"%s/%s"' % (m.group(1), TERMUX_TMP, m.group(2)), src)
        if n:
            _write(path, src)
            return "patched(asprintf=%d)" % n

    # 2) 旧写法：len += sizeof("/tmp/.wine-") + 12; + sprintf(server_dir, ...)
    if TERMUX_TMP in src:
        return "already"
    n1 = n2 = 0
    pat_len = re.compile(r'len\s*\+=\s*sizeof\(\s*"/tmp/\.wine-"\s*\)\s*\+\s*12\s*;')
    src, n1 = pat_len.subn('len += sizeof("/%s/.wine-") + 12;' % TERMUX_TMP.lstrip("/"), src)
    pat_sp = re.compile(r'(sprintf\(\s*server_dir\s*,\s*)"\/tmp\/(\.wine-%u)"')
    src, n2 = pat_sp.subn(lambda m: '%s"%s/%s"' % (m.group(1), TERMUX_TMP, m.group(2)), src)
    if src == orig:
        return "anchor-miss"
    _write(path, src)
    return "patched(len=%d,sprintf=%d)" % (n1, n2)


def patch_crypt32(path):
    src = _read(path)
    if TERMUX_GLIBC + "/etc/ca-certificates/cacert.pem" in src:
        return "already"
    m = re.search(r'static const char \* const CRYPT_knownLocations\[\] =\s*\{.*?\n\};',
                  src, re.S)
    if not m:
        return "anchor-miss"
    block = m.group(0)
    new = block[:-3] + ' "%s/etc/ca-certificates/cacert.pem",\n};' % TERMUX_GLIBC
    src = src[:m.start()] + new + src[m.end():]
    _write(path, src)
    return "patched(+cacert)"


def patch_unicode(path):
    src = _read(path)
    if TERMUX_GLIBC + "/share/wine/nls" in src:
        return "already"
    pat = re.compile(
        r'(static const char \*nls_dirs\[\] = \{[^\n]*?)("/usr/share/wine/nls")')
    if not pat.search(src):
        return "anchor-miss"

    def repl(m):
        return '%s"%s", "%s/share/wine/nls", "%s/local/share/wine/nls"' % (
            m.group(1), m.group(2), TERMUX_GLIBC, TERMUX_GLIBC)

    src = pat.sub(repl, src, count=1)
    _write(path, src)
    return "patched(+nls)"


HANDLERS = {
    "server": patch_server_c,
    "request": patch_request_c,
    "crypt32": patch_crypt32,
    "unicode": patch_unicode,
}


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    ok = True
    for rel, what in TARGETS:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            print("[termux-path] SKIP: %s 不存在 (%s)" % (rel, what))
            continue
        key = rel.split("/")[-1]
        if key == "server.c":
            handler = HANDLERS["server"]
        elif key == "request.c":
            handler = HANDLERS["request"]
        elif key == "unixlib.c":
            handler = HANDLERS["crypt32"]
        else:
            handler = HANDLERS["unicode"]
        try:
            r = handler(p)
        except Exception as exc:  # 不让路径修复阻断构建
            print("[termux-path] ERROR: %s: %s" % (rel, exc))
            ok = False
            continue
        print("[termux-path] %-14s %s -> %s" % (r.split("(")[0], rel, r))
        if r == "anchor-miss":
            ok = False
    print("[termux-path] %s" % ("OK: Termux 路径修复完成" if ok else
                                "WARN: 有锚点未命中（源码结构变了）"))
    return 0  # 永不因 miss 阻断构建


if __name__ == "__main__":
    sys.exit(main())
