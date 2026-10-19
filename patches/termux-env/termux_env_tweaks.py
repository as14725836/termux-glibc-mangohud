#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Termux 环境优化（幂等，找不到锚点就跳过，不产生冲突/不破坏源码）
参考: airidosas252/glibc-wine 的 termux-wine-fix.patch（仅取我们还没有且安全的部分）
  1) setup_config_dir(): 增加 D: -> /sdcard，Z: -> /data/data/com.termux/files
  2) preloader.c: 低 64k 地址告警判定不再限定 __aarch64__
用法: termux_env_tweaks.py <wine源码目录>
注意: 任一子项异常只 WARN 并继续，不得整体中断（历史 bug: 缺 import re 导致整段静默失效）
"""
import io, os, re, sys

src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
done, skip, fail = [], [], []


def load(rel):
    p = os.path.join(src, rel)
    if not os.path.isfile(p):
        return None, None
    return p, io.open(p, encoding='utf-8', errors='surrogateescape').read()


def save(p, t):
    io.open(p, 'w', encoding='utf-8', errors='surrogateescape').write(t)


def guard(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        fail.append('%s: %s: %s' % (name, type(e).__name__, e))
        print('  WARN %s 失败: %s: %s' % (name, type(e).__name__, e), flush=True)


# ---- 1) 盘符映射 ----------------------------------------------------------
def tweak_drives():
    p, t = load('dlls/ntdll/unix/server.c')
    if t is None:
        skip.append('server.c(缺文件)')
        return
    changed = False
    if 'dosdevices/d:' not in t:
        anchor = 'mkdir( "drive_c", 0777 );'
        add = ('mkdir( "drive_c", 0777 );\n'
               '        mkdir( "drive_d", 0777 );\n'
               '        symlink( "/sdcard", "dosdevices/d:" );')
        if anchor in t:
            t = t.replace(anchor, add, 1)
            changed = True
        else:
            skip.append('server.c(drive_d 锚点未找到)')
    if 'symlink( "/", "dosdevices/z:" );' in t:
        t = t.replace('symlink( "/", "dosdevices/z:" );',
                      'symlink( "/data/data/com.termux/files", "dosdevices/z:" );', 1)
        changed = True
    elif 'dosdevices/z:' not in t:
        skip.append('server.c(z: 锚点未找到)')
    if changed:
        save(p, t)
        done.append('盘符映射 D:->/sdcard, Z:->Termux前缀')
    else:
        done.append('盘符映射(已是目标状态)')


# ---- 2) preloader 低 64k 判定 ---------------------------------------------
def tweak_preloader():
    p, t = load('loader/preloader.c')
    if t is None:
        skip.append('preloader.c(缺文件)')
        return
    pat = re.compile(r'#ifdef __aarch64__([ \t]*(\\?)[ \t]*\n[ \t]*&&[ \t]*'
                     r'preload_info\[i\]\.addr < \(void \*\)0x7fffffffff)')
    m = pat.search(t)
    if m:
        # 只有原文带续行反斜杠时才能安全改成 #if 1（否则 #if 1 与下一行 && 不构成同一表达式）
        if m.group(2) != '\\':
            skip.append('preloader.c(条件跨行无续行符，拒绝改写以免产出非法 C)')
            return
        save(p, t[:m.start()] + '#if 1' + m.group(1) + t[m.end():])
        done.append('preloader 低64k判定改为 #if 1')
    elif '0x7fffffffff' not in t:
        done.append('preloader(本版本无高区常量，无需改动)')
    else:
        done.append('preloader(已是目标状态)')


guard('盘符映射', tweak_drives)
guard('preloader 低64k', tweak_preloader)

print('termux 环境优化: %d 项完成%s' % (len(done), ('，跳过: ' + '; '.join(skip)) if skip else ''), flush=True)
for d in done:
    print('  ✔ ' + d, flush=True)
for s in skip:
    print('  - 跳过 ' + s, flush=True)
if fail:
    print('  ✗ 失败 %d 项（不阻断构建）: %s' % (len(fail), '; '.join(fail)), flush=True)
sys.exit(0)