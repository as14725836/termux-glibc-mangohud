#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Termux 环境优化（幂等，找不到锚点就跳过，不产生冲突/不破坏源码）
参考: airidosas252/glibc-wine 的 termux-wine-fix.patch（仅取我们还没有且安全的部分）
  1) setup_config_dir(): 增加 D: -> /sdcard，Z: -> /data/data/com.termux/files
  2) preloader.c: 低 64k 地址告警判定不再限定 __aarch64__
用法: termux_env_tweaks.py <wine源码目录>
"""
import io, os, sys

src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
done, skip = [], []


def load(rel):
    p = os.path.join(src, rel)
    if not os.path.isfile(p):
        return None, None
    return p, io.open(p, encoding='utf-8', errors='surrogateescape').read()


def save(p, t):
    io.open(p, 'w', encoding='utf-8', errors='surrogateescape').write(t)


# ---- 1) 盘符映射 ----------------------------------------------------------
p, t = load('dlls/ntdll/unix/server.c')
if t is None:
    skip.append('server.c(缺文件)')
else:
    changed = False
    if 'dosdevices/d:' not in t:
        anchor = 'mkdir( "drive_c", 0777 );'
        add = ('mkdir( "drive_c", 0777 );\n'
               '        mkdir( "drive_d", 0777 );\n'
               '        symlink( "/sdcard", "dosdevices/d:" );')
        if anchor in t:
            t = t.replace(anchor, add, 1); changed = True
        else:
            skip.append('server.c(drive_d 锚点未找到)')
    if 'symlink( "/", "dosdevices/z:" );' in t:
        t = t.replace('symlink( "/", "dosdevices/z:" );',
                      'symlink( "/data/data/com.termux/files", "dosdevices/z:" );', 1)
        changed = True
    elif 'dosdevices/z:' not in t:
        skip.append('server.c(z: 锚点未找到)')
    if changed:
        save(p, t); done.append('盘符映射 D:->/sdcard, Z:->Termux前缀')
    else:
        done.append('盘符映射(已是目标状态)')

# ---- 2) preloader 低 64k 判定 ---------------------------------------------
p, t = load('loader/preloader.c')
if t is None:
    skip.append('preloader.c(缺文件)')
else:
    pat = re.compile(r'#ifdef __aarch64__(\s*\n\s*&&\s*preload_info\[i\]\.addr < \(void \*\)0x7fffffffff)')
    if pat.search(t):
        t2 = pat.sub(lambda m: '#if 1' + m.group(1), t, 1)
        save(p, t2); done.append('preloader 低64k判定改为 #if 1')
    else:
        done.append('preloader(无需改动/已是目标状态)')

print('termux 环境优化: %d 项完成%s' % (len(done), ('，跳过: ' + '; '.join(skip)) if skip else ''), flush=True)
for d in done:
    print('  ✔ ' + d, flush=True)
for s in skip:
    print('  - 跳过 ' + s, flush=True)
sys.exit(0)
