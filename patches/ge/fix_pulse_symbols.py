#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""winepulse.drv 兜底：
1) pulse.c 调用了 pulse_stream_ready / pulse_stream_haptic 却没有定义时，
   注入自洽的最小实现（不依赖 ds5-haptic 组引入的 struct 字段）。
2) 幂等：已有定义则跳过。
用法：在 wine 源码树根目录执行 python3 fix_pulse_symbols.py
"""
import os
import sys

NL = chr(10)
TAB = chr(9)
WS = ' ' + TAB + chr(13) + NL
TARGET = os.path.join('dlls', 'winepulse.drv', 'pulse.c')
ANCHOR = 'static void pulse_contextcallback(pa_context *c, void *userdata)'

HELPERS = [
    ('pulse_stream_ready', [
        'static BOOL pulse_stream_ready(struct pulse_stream *stream)',
        '{',
        '    if (!stream || !stream->stream) return FALSE;',
        '    return pa_stream_get_state(stream->stream) == PA_STREAM_READY;',
        '}',
    ]),
    ('pulse_stream_haptic', [
        'static BOOL pulse_stream_haptic(struct pulse_stream *stream)',
        '{',
        '    (void)stream;',
        '    return FALSE;',
        '}',
    ]),
]


def match_paren(src, open_pos):
    depth = 0
    i = open_pos
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def has_definition(src, name):
    key = name + '('
    pos = 0
    while True:
        i = src.find(key, pos)
        if i < 0:
            return False
        pos = i + 1
        head = src[max(0, i - 60):i]
        if 'BOOL' not in head and 'static' not in head:
            continue
        close = match_paren(src, i + len(name))
        if close < 0:
            return False
        j = close + 1
        while j < len(src) and src[j] in WS:
            j += 1
        if j < len(src) and src[j] == '{':
            return True


def has_call(src, name):
    key = name + '('
    pos = 0
    while True:
        i = src.find(key, pos)
        if i < 0:
            return False
        pos = i + 1
        head = src[max(0, i - 60):i]
        if 'BOOL' in head or 'static' in head:
            close = match_paren(src, i + len(name))
            if close >= 0:
                j = close + 1
                while j < len(src) and src[j] in WS:
                    j += 1
                if j < len(src) and src[j] == '{':
                    continue
        return True


def main():
    if not os.path.isfile(TARGET):
        print('skip: no ' + TARGET)
        return 0
    src = open(TARGET, 'r', encoding='utf-8', errors='replace').read()
    if 'struct pulse_stream' not in src:
        print('skip: struct pulse_stream not found')
        return 0
    block = []
    for name, lines in HELPERS:
        if not has_call(src, name):
            continue
        if has_definition(src, name):
            continue
        block.append('/* ge-wine fallback: ' + name + ' 来自被跳过的 ds5-haptic 补丁，这里给最小实现 */')
        block.extend(lines)
        block.append('')
    if not block:
        print('ok: nothing to patch')
        return 0
    text = NL.join(block) + NL + NL
    idx = src.find(ANCHOR)
    if idx < 0:
        inc = src.rfind(NL + '#include ')
        if inc < 0:
            print('warn: anchor/include not found, skip')
            return 0
        end = src.find(NL, inc + 1)
        idx = end + 1 if end > 0 else len(src)
    new = src[:idx] + text + src[idx:]
    open(TARGET, 'w', encoding='utf-8').write(new)
    done = [n for n, _ in HELPERS if has_definition(new, n)]
    print('injected: ' + ','.join(done))
    return 0


if __name__ == '__main__':
    sys.exit(main())
