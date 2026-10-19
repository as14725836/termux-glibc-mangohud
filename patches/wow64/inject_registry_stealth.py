#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反检测：把 Wine 自有注册表根键 `Software\\Wine` 改名（幂等、全树一致）

背景
----
WinLicense / Themida / VMProtect 一类加壳程序的环境判定里，最便宜的一条就是
读 `HKCU\\Software\\Wine` / `HKLM\\Software\\Wine` —— 键存在即判「跑在 Wine 上」，
后续直接走反调试 / 拒跑分支。Wine 自己只用这几个常量访问自家配置，只要把
**全部引用点**（C 源码里的转义字符串 + loader/wine.inf.in 的 INF 行）一起改名，
功能完全不受影响，而外部按原名探测会落到「键不存在」。

改名只替换「名称段」，不碰路径层级：
  Software\\Wine                     -> Software\\WinAppCompat
  Software\\Wine\\DllOverrides       -> Software\\WinAppCompat\\DllOverrides
  Software\\Wine\\AppDefaults\\x.exe -> Software\\WinAppCompat\\AppDefaults\\x.exe

代价
----
winetricks / protontricks 等外部工具默认按 `Software\\Wine` 找配置，改名后它们
读不到。本仓库产物面向跑加壳游戏，不在这些工具链路上；需要时把 input 关掉。
这是编译期改名，没有运行时开关。

用法
----
inject_registry_stealth.py <wine源码目录> [--dry-run]
环境变量：WINE_REG_OLDNAME / WINE_REG_NEWNAME 可覆盖新旧键名
"""

import io
import os
import sys

EXTS = ('.c', '.h', '.in', '.idl', '.rc', '.spec', '.drv', '.pl', '.sh')

OLD = os.environ.get('WINE_REG_OLDNAME', 'Wine')
NEW = os.environ.get('WINE_REG_NEWNAME', 'WinAppCompat')

# C 源码里是转义字符串，字面为 Software\\Wine（两个反斜杠字符）
C_OLD = 'Software' + '\\\\' + OLD
C_NEW = 'Software' + '\\\\' + NEW
# INF / 脚本 / 注释里是 Software\Wine（一个反斜杠字符）
P_OLD = 'Software' + '\\' + OLD
P_NEW = 'Software' + '\\' + NEW

SKIP_DIRS = {'.git', 'build', 'build-arm64', 'build-wow64', 'build-tools'}


def is_test(rel):
    return '/tests/' in ('/' + rel.replace(os.sep, '/'))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry-run' in sys.argv
    src = args[0] if args else os.getcwd()

    if NEW == OLD:
        print('SKIP: NEW == OLD (%s)' % NEW)
        return 0

    touched = []
    total_c = total_p = 0

    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not (fn.endswith(EXTS) or fn.endswith('.inf.in')):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, src)
            if is_test(rel):
                continue
            try:
                t = io.open(p, encoding='utf-8', errors='surrogateescape').read()
            except OSError:
                continue
            if C_OLD not in t and P_OLD not in t:
                continue
            n_c = t.count(C_OLD)
            t2 = t.replace(C_OLD, C_NEW)
            n_p = t2.count(P_OLD)
            t2 = t2.replace(P_OLD, P_NEW)
            if t2 == t:
                continue
            touched.append((rel, n_c, n_p))
            total_c += n_c
            total_p += n_p
            if not dry:
                io.open(p, 'w', encoding='utf-8', errors='surrogateescape').write(t2)

    if not touched:
        print('OK(already): 树内已无 Software\\%s（可能已改名，或不是 wine 源码树）' % OLD)
        return 0

    print('--- %s ---' % ('DRY-RUN（未写入）' if dry else '已改名 Software\\%s -> Software\\%s' % (OLD, NEW)))
    for rel, a, b in sorted(touched):
        print('  %-56s escaped=%d plain=%d' % (rel, a, b))
    print('合计: %d 个文件, %d 处转义形式, %d 处单反斜杠形式' % (len(touched), total_c, total_p))
    if not dry:
        print('提示: wine.inf 已随之改动，重新 configure/make 后新建 prefix 才生效；')
        print('      已有 prefix 里的旧键不会自动迁移（删 prefix 重建即可）')
    return 0


if __name__ == '__main__':
    sys.exit(main())