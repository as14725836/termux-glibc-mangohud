#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gst-priority: 让 MediaFoundation byte stream handler 优先使用 GStreamer 解码器。

问题
----
Proton 系（WinNative-Emu/proton-wine 等）把 dlls/mfsrcsnk/media_source.c 的

    static BOOL use_gst_byte_stream_handler(void)
    {
        ...
        return FALSE;          /* Proton: 默认不用 GStreamer */
    }

改成了默认 FALSE，于是 MF 媒体源默认走 winedmo（FFmpeg）解复用，
GStreamer 解码器只在 winedmo 明确不支持时才兜底。

上游 wine-mirror/wine 的默认值是 return TRUE（默认用 GStreamer）。

目标
----
提供两种可切换行为：
  1. 默认改为 GStreamer（与上游一致）—— 让 GStreamer 解码器成为首选；
  2. 同时尊重 WINE_USE_DMO 环境变量（Pipetto 7bde91b5 语义）：
        WINE_USE_DMO 未设置   -> 走开关 1（默认 GST）
        WINE_USE_DMO=0        -> 强制 GStreamer
        WINE_USE_DMO=1        -> 强制 winedmo (FFmpeg)

幂等
----
以 'WINE_USE_DMO' 作为注入标记：已含则跳过（无论来自本脚本还是上游）。

用法:
    inject_gst_priority.py <wine-source-dir> [--dry-run]
"""
import os
import re
import sys

REL = "dlls/mfsrcsnk/media_source.c"
MARK = "WINE_USE_DMO"

# 函数原始形态（Proton: return FALSE；上游: return TRUE），整体替换
FUNC_RE = re.compile(
    r"static\s+BOOL\s+use_gst_byte_stream_handler\s*\(\s*void\s*\)\s*\n"
    r"\{.*?\n\}\n",
    re.S)

NEW_FUNC = '''static BOOL use_gst_byte_stream_handler(void)
{
    const char *wine_use_dmo = getenv("WINE_USE_DMO");
    BOOL result;
    DWORD size = sizeof(result);

    /* Termux: 允许通过 WINE_USE_DMO 强制选择 demuxer 后端。
     *   WINE_USE_DMO=1 -> 使用 winedmo (FFmpeg)
     *   WINE_USE_DMO=0 -> 使用 GStreamer（默认）
     * 未设置时默认 GStreamer，即与上游 wine 行为一致。 */
    if (wine_use_dmo)
    {
        BOOL use_dmo = (wine_use_dmo[0] == '1');
        return !use_dmo;
    }

    /* @@ Wine registry key: HKCU\\Software\\Wine\\MediaFoundation */
    if (!RegGetValueW( HKEY_CURRENT_USER, L"Software\\\\Wine\\\\MediaFoundation", L"DisableGstByteStreamHandler",
                       RRF_RT_REG_DWORD, NULL, &result, &size ))
        return !result;

    return TRUE;
}
'''


def note(item, msg):
    print("[gst-prio] %s: %s" % (item, msg), flush=True)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <wine-source-dir> [--dry-run]" % sys.argv[0])
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    path = os.path.join(root, REL)
    if not os.path.isfile(path):
        note("find", "SKIP: %s 不存在（非 Proton/MF 树）" % REL)
        return 0

    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()

    if MARK in src:
        note("idempotent", "已含 WINE_USE_DMO → 跳过")
        return 0

    m = FUNC_RE.search(src)
    if not m:
        note("find", "SKIP: 未匹配 use_gst_byte_stream_handler → 跳过")
        return 0

    body = m.group(0)
    if "DisableGstByteStreamHandler" not in body:
        note("find", "SKIP: 函数结构与预期不同 → 跳过")
        return 0
    if "getenv" in body:
        note("idempotent", "已含 getenv → 跳过")
        return 0

    new_src = src[:m.start()] + NEW_FUNC + src[m.end():]

    if 'stdlib.h' not in src.split('use_gst_byte_stream_handler')[0][-3000:]:
        note("warn", "media_source.c 未见显式 stdlib.h（getenv 由其它头间接提供，通常无碍）")

    if dry:
        note("dry-run", "would replace %d bytes -> %d bytes" % (len(body), len(NEW_FUNC)))
        return 0

    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(new_src)
    note("write", "完成：默认 GStreamer + WINE_USE_DMO 开关")
    return 0


if __name__ == "__main__":
    sys.exit(main())
