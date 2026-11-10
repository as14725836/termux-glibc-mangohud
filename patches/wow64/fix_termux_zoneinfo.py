#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Termux: 把 Wine 读时区数据库 zoneinfo 的路径改成 Termux 路径。

背景
----
Wine 的 dlls/ntdll/unix/system.c 用 TZ 环境变量（或 Windows 时区名）去
zoneinfo 目录找时区文件，据此构造 RTL_DYNAMIC_TIME_ZONE_INFORMATION：

    static const char default_tzinfo_dir[] = "/usr/share/zoneinfo";
    ...
    const char *tzinfo_dir = getenv( "TZDIR" );
    ...
    if (!tzinfo_dir) tzinfo_dir = default_tzinfo_dir;
    snprintf( buf, sizeof(buf), "%s/%s", tzinfo_dir, name );
    if (!(f = fopen( buf, "r" )))
    {
        WARN( "Could not open %s.\n", debugstr_a( buf ));
        return FALSE;
    }

Termux 上 /usr/share/zoneinfo 不存在（glibc 时区数据装在前缀里），于是每次
取时区都刷：

    0034:warn:ntdll:get_tz_info_from_zoneinfo_name Could not open
    "/usr/share/zoneinfo/Asia/Shanghai".

并退回注册表映射路径 / 直接失败，导致本地时间偏移与夏令时判断不准。

策略
----
改两个字符串字面量，不动 TZDIR 优先级逻辑——用户显式设置 TZDIR 时仍然生效
（这才是原有的覆盖入口）：

  1) get_tz_info_from_zoneinfo_name() 的兜底目录
       static const char default_tzinfo_dir[] = "/usr/share/zoneinfo";
     ->  TZ_DIR

  2) get_system_config_tz_info() 读系统时区软链
       if (!realpath( "/etc/localtime", path )) return FALSE;
     ->  realpath( LOCAL_TIME, path )
     否则即使 zoneinfo 目录修好，TZ 未设置时这条路径也会因为读不到
     /etc/localtime 而直接返回 FALSE。

  TZ_DIR     默认 /data/data/com.termux/files/usr/glibc/share/zoneinfo
  LOCAL_TIME 默认 /data/data/com.termux/files/usr/glibc/share/zoneinfo/localtime
  分别可用环境变量 TERMUX_ZONEINFO / TERMUX_LOCALTIME 覆盖。

注意：脚本只改路径，不创建文件。目标时区数据与 localtime 软链需由
终端环境自行提供（tzdata 装到 TZ_DIR；localtime 指向 TZ_DIR 下某个时区）。

锚点稳定性
----------
*   static const char default_tzinfo_dir[] = "/usr/share/zoneinfo";
*   if (!realpath( "/etc/localtime", path )) return FALSE;

  两条在 wine-9.x / 10.x / 11.x / master 逐字相同（已核对 wine-mirror/wine@master
  与 as14725836/wine-termux@11.18）。
* Proton 10.0 分支用注册表 + localtime 两套路径，不含上述字符串，
  会自动跳过（返回 anchor-miss），不报错。

幂等：任一目标串已存在即跳过该项。

用法
----
    python3 fix_termux_zoneinfo.py <wine_source_root> [目标路径]
    TERMUX_ZONEINFO=/some/other/share/zoneinfo python3 fix_termux_zoneinfo.py .
"""
import io
import os
import sys

DEFAULT_TZ_DIR = "/data/data/com.termux/files/usr/glibc/share/zoneinfo"
DEFAULT_LOCALTIME = "/data/data/com.termux/files/usr/glibc/share/zoneinfo/localtime"

TZ_DIR = os.environ.get("TERMUX_ZONEINFO") or DEFAULT_TZ_DIR
LOCALTIME = os.environ.get("TERMUX_LOCALTIME") or DEFAULT_LOCALTIME

OLD_DECL = 'static const char default_tzinfo_dir[] = "/usr/share/zoneinfo";'
OLD_LOCALTIME = 'if (!realpath( "/etc/localtime", path )) return FALSE;'


def _replace_once(src, old, new):
    """唯一命中才替换。返回 (新内容, 状态)。"""
    if new in src:
        return src, "already"
    if old not in src:
        return src, "anchor-miss"
    n = src.count(old)
    if n != 1:
        return src, "anchor-dup(%d)" % n
    return src.replace(old, new, 1), "patched"


def patch_system_c(path):
    """default_tzinfo_dir[] + realpath("/etc/localtime") -> Termux 路径。"""
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    orig = src
    results = []

    src, st = _replace_once(
        src, OLD_DECL,
        'static const char default_tzinfo_dir[] = "%s";' % TZ_DIR)
    results.append(("default_tzinfo_dir", st))

    src, st = _replace_once(
        src, OLD_LOCALTIME,
        'if (!realpath( "%s", path )) return FALSE;' % LOCALTIME)
    results.append(("/etc/localtime", st))

    if src != orig:
        io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)

    return results


LABELS = {
    "already": "已是目标路径，跳过",
    "anchor-miss": "未见锚点（该树不走这条路径），跳过",
}

TITLES = {
    "default_tzinfo_dir": "/usr/share/zoneinfo      -> %s" % TZ_DIR,
    "/etc/localtime": "/etc/localtime            -> %s" % LOCALTIME,
}


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."

    global TZ_DIR, LOCALTIME
    if len(sys.argv) > 2:
        TZ_DIR = sys.argv[2]
    if len(sys.argv) > 3:
        LOCALTIME = sys.argv[3]

    path = os.path.join(root, "dlls", "ntdll", "unix", "system.c")
    if not os.path.isfile(path):
        print("SKIP: 未找到 %s" % path)
        return 0

    try:
        results = patch_system_c(path)
    except Exception as e:  # 不阻断构建
        print("WARN: zoneinfo 修复异常: %s" % e)
        return 0

    for name, st in results:
        if st == "patched":
            print("[termux-zoneinfo] OK: %s" % (TITLES.get(name, name)))
        elif st == "already":
            print("[termux-zoneinfo] NOOP: %s 已是目标路径" % name)
        elif st == "anchor-miss":
            print("[termux-zoneinfo] SKIP: %s 未见锚点" % name)
        else:
            print("[termux-zoneinfo] WARN: %s %s（未修改）" % (name, st))

    return 0


if __name__ == "__main__":
    sys.exit(main())
