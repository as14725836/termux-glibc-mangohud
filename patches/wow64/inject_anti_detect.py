#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反检测：SMBIOS / 硬件指纹伪装（幂等、内容锚点式，找不到锚点就跳过）

背景
----
Android / Termux 上 /sys/class/dmi/id/* 要么不可读、要么是手机厂商的原生值，
Wine 会把读到的内容原样塞进 SMBIOS 表。NtQuerySystemInformation(
SystemFirmwareTableInformation) / WMI Win32_BIOS / Win32_BaseBoard 一读
就会拿到「空串」或「手机型号」，对 WinLicense / Themida 这类带环境指纹
校验的加壳程序来说等于直接暴露「不是真实 PC」。

本脚本在 dlls/ntdll/unix/system.c 的 get_smbios_string() 两个出口处
追加一次覆盖，把 BIOS / 整机 / 机箱 / 主板字段换成一组合法的桌面 PC 值；
三个序列号由 seed（WINE_HWID_SEED，缺省回退 /etc/machine-id）做
FNV-1a 派生 —— 同一台机器稳定、跨机器不同，避免「所有机器序列号一样」
这个更明显的特征。

开关
----
WINE_HWID_SPOOF=0   运行时彻底关闭伪装（默认开启）

用法
----
inject_anti_detect.py <wine源码目录>
"""

import io
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

TARGET = 'dlls/ntdll/unix/system.c'
MARK = 'wine_hwid_spoof'

HELPER = r'''
/* ---- 反检测：SMBIOS / 硬件指纹伪装（inject_anti_detect.py 注入） ---- */
static void wine_hwid_serial( char *out, size_t size, const char *salt )
{
    static const char *fallback = "wine-termux-hwid";
    char buf[128];
    const char *seed = getenv( "WINE_HWID_SEED" );
    unsigned int h = 2166136261u;
    size_t i = 0, n;
    FILE *f;

    buf[0] = 0;
    if (!seed || !*seed)
    {
        if ((f = fopen( "/etc/machine-id", "r" )))
        {
            if (!fgets( buf, sizeof(buf), f )) buf[0] = 0;
            fclose( f );
            n = strlen( buf );
            while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) buf[--n] = 0;
        }
        seed = buf[0] ? buf : fallback;
    }
    while (seed[i]) { h ^= (unsigned char)seed[i++]; h *= 16777619u; }
    if (salt) { i = 0; while (salt[i]) { h ^= (unsigned char)salt[i++]; h *= 16777619u; } }
    snprintf( out, size, "SN%08X%08X", h, h * 2654435761u );
}

static void wine_hwid_spoof( const char *path, char *str, size_t size )
{
    static const struct { const char *suffix; const char *value; } table[] =
    {
        { "bios_vendor",     "American Megatrends Inc." },
        { "bios_version",    "P1.60" },
        { "bios_date",       "03/14/2022" },
        { "sys_vendor",      "ASUSTeK COMPUTER INC." },
        { "product_name",    "B650M-PLUS" },
        { "product_version", "Rev 1.xx" },
        { "product_sku",     "Default string" },
        { "product_family",  "B650M-PLUS" },
        { "chassis_vendor",  "ASUSTeK COMPUTER INC." },
        { "chassis_version", "Rev 1.xx" },
        { "chassis_tag",     "Default string" },
        { "chassis_type",    "3" },
        { "board_vendor",    "ASUSTeK COMPUTER INC." },
        { "board_name",      "B650M-PLUS" },
        { "board_version",   "Rev 1.xx" },
        { "board_asset_tag", "Default string" },
    };
    const char *env = getenv( "WINE_HWID_SPOOF" );
    unsigned int i;

    if (!path || !size) return;
    if (env && !strcmp( env, "0" )) return;

    for (i = 0; i < sizeof(table) / sizeof(table[0]); i++)
    {
        if (strstr( path, table[i].suffix ))
        {
            snprintf( str, size, "%s", table[i].value );
            return;
        }
    }
    if (strstr( path, "product_serial" ) || strstr( path, "chassis_serial" ) ||
        strstr( path, "board_serial" ))
        wine_hwid_serial( str, size, path );
}

'''

ANCHOR_FN = 'static const char *get_smbios_string( const char *path, char *str, size_t size )\n'

ANCHOR_FAIL = 'if (!(file = fopen(path, "r"))) return str;'
REPL_FAIL = 'if (!(file = fopen(path, "r"))) { wine_hwid_spoof( path, str, size ); return str; }'

ANCHOR_OK = ('    if (len >= 1 && str[len - 1] == \'\\n\') len--;\n'
             '    str[len] = 0;\n'
             '    return str;\n')
REPL_OK = ('    if (len >= 1 && str[len - 1] == \'\\n\') len--;\n'
           '    str[len] = 0;\n'
           '    wine_hwid_spoof( path, str, size );\n'
           '    return str;\n')


def load(rel):
    p = os.path.join(src, rel)
    if not os.path.isfile(p):
        return None, None
    return p, io.open(p, encoding='utf-8', errors='surrogateescape').read()


def main():
    p, t = load(TARGET)
    if t is None:
        print('SKIP: %s 不存在（非 Linux 源码树或路径不对）' % TARGET)
        return 0

    if MARK in t:
        print('OK(already): %s 已含 %s' % (TARGET, MARK))
        return 0

    for hdr in ('#include <stdlib.h>', '#include <string.h>', '#include <stdio.h>'):
        if hdr not in t:
            print('SKIP: %s 缺 %s，放弃注入（避免编译失败）' % (TARGET, hdr))
            return 0

    if ANCHOR_FN not in t:
        print('SKIP: get_smbios_string 原型锚点未命中（版本差异），跳过')
        return 0

    if ANCHOR_FAIL not in t:
        print('SKIP: fopen 失败分支锚点未命中，跳过')
        return 0

    if ANCHOR_OK not in t:
        print('SKIP: 正常返回分支锚点未命中，跳过')
        return 0

    t2 = t.replace(ANCHOR_FN, HELPER + ANCHOR_FN, 1)
    t2 = t2.replace(ANCHOR_FAIL, REPL_FAIL, 1)
    t2 = t2.replace(ANCHOR_OK, REPL_OK, 1)

    # 顺序自检：helper 必须定义在调用点之前
    if not (t2.index('static void wine_hwid_spoof') < t2.index('wine_hwid_spoof( path, str, size )')):
        print('FAIL: 注入顺序异常，放弃写入')
        return 1

    io.open(p, 'w', encoding='utf-8', errors='surrogateescape').write(t2)
    print('OK: %s 已注入 SMBIOS 伪装（16 个静态字段 + 3 个派生序列号）' % TARGET)
    print('    运行时可关: WINE_HWID_SPOOF=0')
    return 0


sys.exit(main())
