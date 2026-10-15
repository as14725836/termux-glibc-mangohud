#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media_converter: PROTON_* 环境变量开关（Pipetto b44ef85b 适配）。

来源
----
Pipetto-crypto/wine commit b44ef85be4fbf48c186b7df823be6c59762009ec
("winegstreamer: port add-envvar-to-gate-media-converter from Proton-GE")，
给 dlls/winegstreamer/media-converter/lib.c 的 media_converter_init() 加
三个环境变量开关：

  PROTON_VIDEO_CONVERT=0 -> 跳过 protonvideoconverter 注册
  PROTON_AUDIO_CONVERT=0 -> 跳过 protonaudioconverter / protonaudioconverterbin
  PROTON_DEMUX=0         -> 跳过 protondemuxer 注册

适用性：仅对携带 media-converter/lib.c 的树生效（Proton 系：WinNative 等）。
上游 wine / wine-tkg 无该文件 -> 跳过。已自带的树（Pipetto 快照）-> 幂等跳过。

用法: inject_media_converter_gates.py <wine-source-dir> [--dry-run]
"""
import io
import os
import re
import sys

REL = "dlls/winegstreamer/media-converter/lib.c"
MARK = "PROTON_VIDEO_CONVERT"

GATED = '''bool media_converter_init(void)
{
    const char *proton_video_convert = NULL;
    const char *proton_audio_convert = NULL;
    const char *proton_demuxer = NULL;

    GST_DEBUG_CATEGORY_INIT(media_converter_debug,
            "protonmediaconverter", GST_DEBUG_FG_YELLOW, "Proton media converter");

    proton_video_convert = getenv("PROTON_VIDEO_CONVERT");
    if (proton_video_convert == NULL || strcmp(proton_video_convert, "0") != 0)
    {
        if (!GST_ELEMENT_REGISTER(protonvideoconverter, NULL))
        {
            GST_ERROR("Failed to register protonvideoconverter.");
            return false;
        }
    }

    proton_audio_convert = getenv("PROTON_AUDIO_CONVERT");
    if (proton_audio_convert == NULL || strcmp(proton_audio_convert, "0") != 0)
    {
        if (!GST_ELEMENT_REGISTER(protonaudioconverter, NULL))
        {
            GST_ERROR("Failed to register protonaudioconverter.");
            return false;
        }

        if (!GST_ELEMENT_REGISTER(protonaudioconverterbin, NULL))
        {
            GST_ERROR("Failed to register protonaudioconverterbin.");
            return false;
        }
    }

    proton_demuxer = getenv("PROTON_DEMUX");
    if (proton_demuxer == NULL || strcmp(proton_demuxer, "0") != 0)
    {
        if (!GST_ELEMENT_REGISTER(protondemuxer, NULL))
        {
            GST_ERROR("Failed to register protondemuxer.");
            return false;
        }
    }

    return true;
}
'''

# 原始（未加开关）注册序列：从函数头到第一个仅含 '}' 的收尾
FUNC_HEAD = "bool media_converter_init(void)"
FUNC_OLD_RE = re.compile(
    r"bool media_converter_init\(void\)\n\{.*?\n\}\n",
    re.S)


def note(item, msg):
    print("[mc-gates] %s: %s" % (item, msg), flush=True)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <wine-source-dir> [--dry-run]" % sys.argv[0])
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    path = os.path.join(root, REL)
    if not os.path.isfile(path):
        note("find", "SKIP: %s missing (non-Proton tree) -> nothing to do" % REL)
        return 0
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    if MARK in src:
        note("idempotent", "already contains PROTON_VIDEO_CONVERT -> skip")
        return 0
    m = FUNC_OLD_RE.search(src)
    if not m:
        note("find", "SKIP: media_converter_init not matched -> skip")
        return 0
    body = m.group(0)
    # 需要包含四个注册的“未分开关”版本才注入；否则结构不同跳过
    need = ["protonvideoconverter", "protonaudioconverter", "protonaudioconverterbin", "protondemuxer"]
    if not all(k in body for k in need):
        note("find", "SKIP: register sequence differs -> skip")
        return 0
    if "getenv" in body:
        note("idempotent", "getenv already present -> skip")
        return 0
    src = src[:m.start()] + GATED + src[m.end():]
    if dry:
        note("dry-run", "would write %d bytes (replace %d)" % (len(src), len(body)))
        return 0
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    note("write", "done: gated registration inserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())