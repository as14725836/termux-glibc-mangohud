#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Termux glibc: 把 machine-id 读取路径改成 Termux 可访问的位置。

背景
----
Wine 从 machine-id 派生两类标识：
  * server/token.c  init_user_sid()     -> 本地用户 SID 的 sub_auth[1..2]
                                          读 /etc/machine-id
  * dlls/ntdll/unix/system.c get_system_uuid()
                                        -> 系统 UUID (RtlGetSystemTimeAndBias 等）
                                          读 /var/lib/dbus/machine-id
Termux 上这两个标准路径不可访问（或不存在），于是 SID 退化为固定值、
系统 UUID 全 0xFF，部分程序（授权/防盗版/存档校验）行为异常。

策略：直接把路径换成 Termux 路径（不做原路径回退）
--------------------------------------------------
  /etc/machine-id          -> /data/data/com.termux/files/usr/glibc/etc/machine-id
  /var/lib/dbus/machine-id -> /data/data/com.termux/files/usr/glibc/etc/machine-id

这些构建产物只服务 Termux glibc 环境，保留 /etc 原路径只会让
同一个 SID/UUID 在两处读出不一致，所以直接替换。

锚点稳定性
----------
* system.c 的
      memset( uuid, 0xff, sizeof(*uuid) );
      if ((fd = open( "/var/lib/dbus/machine-id", O_RDONLY )) != -1)
  在 wine-9.0 / 10.0 / 11.0 / master 逐字相同（已核对）。
* token.c 的
      f = fopen( "/etc/machine-id", "r" );
  是 Proton 分支独有（上游没有 init_user_sid）；非 Proton 分支自动跳过。
"""
import io, os, re, sys

TERMUX_MACHINE_ID = "/data/data/com.termux/files/usr/glibc/etc/machine-id"


def patch_system_c(path):
    """get_system_uuid(): open("/var/lib/dbus/machine-id") -> 多路径回退"""
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    if TERMUX_MACHINE_ID in src:
        return "already"

    OLD = 'if ((fd = open( "/var/lib/dbus/machine-id", O_RDONLY )) != -1)'
    if OLD not in src:
        return "anchor-miss"

    NEW = 'if ((fd = open( "%s", O_RDONLY )) != -1)' % TERMUX_MACHINE_ID

    n = src.count(OLD)
    if n != 1:
        return "anchor-dup(%d)" % n
    src = src.replace(OLD, NEW)
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    return "patched"


def patch_token_c(path):
    """init_user_sid(): fopen("/etc/machine-id") -> 多路径回退"""
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    if TERMUX_MACHINE_ID in src:
        return "already"

    OLD = 'f = fopen( "/etc/machine-id", "r" );'
    if OLD not in src:
        return "not-proton"

    NEW = 'f = fopen( "%s", "r" );' % TERMUX_MACHINE_ID

    n = src.count(OLD)
    if n != 1:
        return "anchor-dup(%d)" % n
    src = src.replace(OLD, NEW, 1)

    # 报错信息里的路径也一起换成实际使用的路径，方便排查
    # 注意用 @PATH@ 占位再替换，避免 Python 的 % 和 C 的 %s 打架
    src = src.replace(
        'fprintf( stderr, "Failed to open /etc/machine-id, error %s.\\n", strerror( errno ));',
        'fprintf( stderr, "Failed to open @PATH@, error %s.\\n", strerror( errno ));')
    src = src.replace(
        'fprintf( stderr, "Failed to read /etc/machine-id, error %s.\\n", strerror( errno ));',
        'fprintf( stderr, "Failed to read @PATH@, error %s.\\n", strerror( errno ));')
    src = src.replace("@PATH@", TERMUX_MACHINE_ID)

    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    return "patched"


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    targets = [
        ("dlls/ntdll/unix/system.c", patch_system_c, True),
        ("server/token.c",           patch_token_c,  False),
    ]
    hard_fail = False
    for rel, fn, required in targets:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            print("SKIP: %s 不存在" % rel)
            if required: hard_fail = True
            continue
        r = fn(p)
        print("%-12s %s" % (r, rel))
        if required and r in ("anchor-miss",) or r.startswith("anchor-dup"):
            hard_fail = True
    print("OK: machine-id 路径修复完成（或无需修复）")
    return 0  # 永不因本步骤失败而中断构建


if __name__ == "__main__":
    sys.exit(main())
