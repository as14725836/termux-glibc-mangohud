#!/usr/bin/env python3
"""给 dlls/winepulse.drv/pulse.c 补齐缺失的 haptic 辅助函数。

GE 的 ge-video-rework/0005 引入了 pulse_stream_ready() / pulse_stream_haptic()
的调用，而这两个函数的定义在 patches/proton-ds5-haptic/ 里。若该组某几份
补丁因上下文漂移被 strict 跳过，pulse.c 就只剩调用没有定义，链接
dlls/winepulse.drv/winepulse.so 时报 undefined reference。
winepulse.so 用 -Wl,-z,defs 链接，未定义符号会直接失败。
本脚本检测有调用但无定义的情况并注入最小实现，保证链接通过。
"""
import os
import sys

TARGET = os.path.join('dlls', 'winepulse.drv', 'pulse.c')
ANCHOR = 'static void pulse_contextcallback(pa_context *c, void *userdata)'

READY_TMPL = """/* ge-wine-fallback: pulse_stream_ready */
static BOOL pulse_stream_ready(struct pulse_stream *stream)
{
%sif (!stream->stream) return FALSE;
%sreturn pa_stream_get_state(stream->stream) == PA_STREAM_READY;
}"""

HAPTIC_TMPL = """/* ge-wine-fallback: pulse_stream_haptic */
static BOOL pulse_stream_haptic(struct pulse_stream *stream)
{
%sreturn FALSE;
}"""

READY_BODY = READY_TMPL % ((chr(32) * 4), (chr(32) * 4))
HAPTIC_BODY = HAPTIC_TMPL % (chr(32) * 4)

def has_definition(src, name):
    key = chr(66) + chr(79) + chr(79) + chr(76) + chr(32) + name + chr(40)
    pos = src.find(key)
    while pos >= 0:
        idx = pos
        while idx < len(src) and src[idx] not in (chr(59) + chr(123)):
            idx += 1
        if idx < len(src) and src[idx] == chr(123):
            return True
        pos = src.find(key, pos + 1)
    return False

def main():
    if not os.path.isfile(TARGET):
        print('skip: %s not found' % TARGET)
        return 0
    with open(TARGET, encoding="utf-8", errors="replace") as handle:
        src = handle.read()
    need = []
    if 'pulse_stream_ready(' in src and not has_definition(src, 'pulse_stream_ready'):
        need.append('ready')
    if 'pulse_stream_haptic(' in src and not has_definition(src, 'pulse_stream_haptic'):
        need.append('haptic')
    if not need:
        print('ok: haptic helpers already provided by patches')
        return 0
    blocks = []
    if 'ready' in need:
        blocks.append(READY_BODY)
    if 'haptic' in need:
        blocks.append(HAPTIC_BODY)
    if ANCHOR not in src:
        sys.stderr.write('anchor not found')
        return 2
    joined = (chr(10) + chr(10)).join(blocks) + chr(10) + chr(10) + ANCHOR
    src = src.replace(ANCHOR, joined, 1)
    with open(TARGET, "w", encoding="utf-8") as handle:
        handle.write(src)
    print('injected: ' + ','.join(need))
    return 0

if __name__ == "__main__":
    sys.exit(main())
