#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""winegstreamer: GstGL/OpenGL 可条件关闭（Pipetto 76f6eab3 适配）。

来源
----
Pipetto-crypto/wine commit 76f6eab35b55fd765db184459f8de2bbe4dea0e7
("winegstreamer: make opengl conditional")，为 termux-glibc 构建移植：

  1) unix_private.h: 声明 extern int wine_gst_no_gl;
  2) unixlib.c: 定义 wine_gst_no_gl（默认 -1），wg_init_gstreamer() 里读
     WINE_GST_NO_GL 环境变量；置位时跳过 GstGL display/context 初始化。
  3) wg_parser.c: wine_gst_no_gl 置位时 params->use_opengl = false，
     且把 is_kirikiri_game 调用加 game_id 非空防护。

适用性：仅对仍保留 GstGL 机制的树生效（pip9 等老结构）。
上游 wine 11.x 已彻底移除 GstGL/OpenGL 分支（unixlib.c 无 gl_display、
wg_parser.c 无 use_opengl）→ 检测不到锚点则跳过，不阻断构建。
已自带的树（Pipetto：wine_gst_no_gl 已存在）→ 幂等跳过。

用法: inject_gst_no_gl.py <wine-source-dir> [--dry-run]
"""
import io
import os
import sys

DIR = "dlls/winegstreamer"
MARK = "wine_gst_no_gl"
GST_ENV_READ = '''\tif (wine_gst_no_gl == -1)
\t\twine_gst_no_gl = getenv("WINE_GST_NO_GL") && atoi(getenv("WINE_GST_NO_GL"));

\tif (wine_gst_no_gl)
\t\treturn STATUS_SUCCESS;

'''
USE_GL_HOOK = '''\n    if (wine_gst_no_gl)
    \tparams->use_opengl = false;
    \t
'''


def note(item, msg):
    print("[gst-no-gl] %s: %s" % (item, msg), flush=True)


def rd(path):
    return io.open(path, encoding="utf-8", errors="surrogateescape").read()


def wr(path, s):
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(s)


def inject_h(path):
    """unix_private.h: 加 extern 声明。"""
    src = rd(path)
    if MARK in src:
        return "SKIP: already present"
    anchor = "extern NTSTATUS wg_init_gstreamer(void *args);"
    if anchor not in src:
        return "WARN: anchor not found"
    src = src.replace(anchor, anchor + "\n\nextern int wine_gst_no_gl;", 1)
    wr(path, src)
    return "OK: extern declared"


def inject_unixlib(path):
    """unixlib.c: 定义变量 + wg_init_gstreamer 里插 env 开关。"""
    src = rd(path)
    if MARK in src:
        return "SKIP: already present"
    if "GstGLDisplay *gl_display;" not in src:
        return "WARN: gl_display not found (newer upstream) -> skip"
    src = src.replace("GstGLDisplay *gl_display;",
                      "GstGLDisplay *gl_display;\nint wine_gst_no_gl = -1;", 1)
    # 在 "GST_INFO(\"GStreamer library version .. 与 gl_display = gst_gl_display_new() 之间插
    anchor = "    if (!(gl_display = gst_gl_display_new()))"
    if anchor not in src:
        return "WARN: gst_gl_display_new anchor not found"
    # 依树自适应：有 media_converter_init 就调用它（原 commit），否则直接返回
    if "media_converter_init" in src:
        branch = ('\tif (wine_gst_no_gl) {\n'
                  '\t\tif (!media_converter_init())\n'
                  '\t\t\treturn STATUS_UNSUCCESSFUL;\n'
                  '\t\treturn STATUS_SUCCESS;\n'
                  '\t}\n'
                  '\t\n')
    else:
        branch = '\tif (wine_gst_no_gl)\n\t\treturn STATUS_SUCCESS;\n\t\n'
    env_read = ('\tif (wine_gst_no_gl == -1)\n'
                '\t\twine_gst_no_gl = getenv("WINE_GST_NO_GL") && atoi(getenv("WINE_GST_NO_GL"));\n\n')
    src = src.replace(anchor, env_read + branch + anchor, 1)
    wr(path, src)
    return "OK: env switch inserted" + (" (with media_converter_init)" if "media_converter_init" in src else "")


def inject_wg_parser(path):
    """wg_parser.c: use_opengl hook + kirikiri null guard。"""
    src = rd(path)
    if MARK in src:
        return "SKIP: already present"
    if "params->use_opengl" not in src:
        return "WARN: use_opengl not found (newer upstream) -> skip"
    # null guard
    if "if (is_kirikiri_game(game_id))\n            params->use_opengl = false;" in src:
        src = src.replace(
            "if (is_kirikiri_game(game_id))\n            params->use_opengl = false;",
            "if (game_id && is_kirikiri_game(game_id))\n            params->use_opengl = false;", 1)
    # use_opengl hook：在 calloc 之后
    anchor = "    if (!(parser = calloc(1, sizeof(*parser))))\n        return E_OUTOFMEMORY;\n"
    if anchor not in src:
        return "WARN: calloc anchor not found"
    src = src.replace(anchor, anchor + USE_GL_HOOK, 1)
    wr(path, src)
    return "OK: use_opengl hook inserted"


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <wine-source-dir> [--dry-run]" % sys.argv[0])
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    base = os.path.join(root, DIR)
    files = {
        "unix_private.h": os.path.join(base, "unix_private.h"),
        "unixlib.c": os.path.join(base, "unixlib.c"),
        "wg_parser.c": os.path.join(base, "wg_parser.c"),
    }
    if not os.path.isdir(base):
        note("find", "SKIP: %s missing" % DIR)
        return 0
    # 先探：是否有 GstGL 机制（老结构）
    unixlib = rd(files["unixlib.c"]) if os.path.isfile(files["unixlib.c"]) else ""
    if "GstGLDisplay *gl_display;" not in unixlib and MARK not in unixlib:
        note("find", "SKIP: no GstGL mechanism in unixlib.c (newer upstream) -> nothing to do")
        return 0
    if MARK in unixlib:
        note("idempotent", "already contains wine_gst_no_gl -> skip")
        return 0
    results = []
    for name in ["unix_private.h", "unixlib.c", "wg_parser.c"]:
        p = files[name]
        if not os.path.isfile(p):
            results.append((name, "SKIP: file missing"))
            continue
        fn = {"unix_private.h": inject_h, "unixlib.c": inject_unixlib,
              "wg_parser.c": inject_wg_parser}[name]
        if dry:
            src_before = rd(p)
            r = fn(p)  # 真改写，dry 下回滚
            wr(p, src_before)
            results.append((name, "(dry) " + r))
        else:
            results.append((name, fn(p)))
    for name, r in results:
        note(name, r)
    return 0


if __name__ == "__main__":
    sys.exit(main())