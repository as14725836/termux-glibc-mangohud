#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gst-priority: 让 MediaFoundation byte stream handler 优先使用 GStreamer 解码器。

背景
----
dlls/mfsrcsnk/media_source.c 的

    static BOOL use_gst_byte_stream_handler(void) { ... return FALSE/TRUE; }

在不同源码树里语义不同：
  * 上游 wine-mirror/wine      : 默认 return TRUE  (GStreamer 优先)
  * Proton 系 (WinNative-Emu)  : 默认 return FALSE (winedmo/FFmpeg 优先)
  * dwproton (dawn.wine)       : 默认 return FALSE，但已经支持
                                 PROTON_MEDIA_FORCE_GST=1 强制 GStreamer

目标
----
统一切换为「默认 GStreamer」，并提供运行时开关：
    WINE_USE_DMO 未设置 -> 默认 GStreamer
    WINE_USE_DMO=0      -> 强制 GStreamer
    WINE_USE_DMO=1      -> 强制 winedmo (FFmpeg)
同时保留原树里已有的 PROTON_MEDIA_FORCE_GST 语义（若存在）。

幂等
----
以 'WINE_USE_DMO' 作为注入标记：已含则跳过。

用法:
    inject_gst_priority.py <wine-source-dir> [--dry-run]
"""
import os
import re
import sys

REL = "dlls/mfsrcsnk/media_source.c"
MARK = "WINE_USE_DMO"

FUNC_RE = re.compile(
    r"static\s+BOOL\s+use_gst_byte_stream_handler\s*\(\s*void\s*\)\s*\n"
    r"\{.*?\n\}\n",
    re.S)

NEW_FUNC = '''static BOOL use_gst_byte_stream_handler(void)
{
    const char *wine_use_dmo = getenv("WINE_USE_DMO");
    BOOL result;
    DWORD size = sizeof(result);

    /* Termux/gst-priority: 运行时选择 demuxer 后端。
     *   WINE_USE_DMO=1 -> winedmo (FFmpeg)
     *   WINE_USE_DMO=0 -> GStreamer
     * 未设置时默认 GStreamer（与上游 wine 行为一致）。 */
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

    # 判定这棵树原始默认值：return FALSE(Proton) / return TRUE(上游)
    # 只要结尾不是 TRUE，就需要改。
    tail = body.rstrip()
    if re.search(r"return\s+TRUE\s*;\s*\}$", tail):
        note("idempotent", "已经是默认 GStreamer (return TRUE) → 跳过")
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
