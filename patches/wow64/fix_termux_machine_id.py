#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Termux: 把 Wine 读 machine-id 的路径改成 Termux 路径。

背景
----
Wine 从 machine-id 派生两类标识：
  * server/token.c            init_user_sid()     -> 本地用户 SID 的 sub_auth[1..2]
                                                   读 /etc/machine-id
  * dlls/ntdll/unix/system.c  get_system_uuid()   -> 系统 UUID
                                                   读 /var/lib/dbus/machine-id
Termux 上这两个标准路径读不到，于是 SID 退化、系统 UUID 全 0xFF，
授权 / 防盗版 / 存档校验类程序行为可能异常。

策略
----
直接把路径字符串替换掉，不做原路径回退（产物只服务 Termux）。

  /etc/machine-id          -> <TARGET>
  /var/lib/dbus/machine-id -> <TARGET>

TARGET 默认 /data/data/com.termux/files/usr/glibc/etc/machine-id，
可用环境变量 TERMUX_MACHINE_ID 覆盖。

锚点稳定性
----------
* system.c 的
      memset( uuid, 0xff, sizeof(*uuid) );
      if ((fd = open( "/var/lib/dbus/machine-id", O_RDONLY )) != -1)
  在 wine-9.0 / 10.0 / 11.0 / master 逐字相同（已核对）。
* token.c 的
      f = fopen( "/etc/machine-id", "r" );
  是 Proton 分支独有（上游没有 init_user_sid）；非 Proton 分支自动跳过。

用法
----
    python3 fix_termux_machine_id.py <wine_source_root> [目标路径]
    TERMUX_MACHINE_ID=/some/other/etc/machine-id python3 fix_termux_machine_id.py .
"""
import io, os, sys

DEFAULT_TARGET = "/data/data/com.termux/files/usr/glibc/etc/machine-id"
TARGET = os.environ.get("TERMUX_MACHINE_ID") or DEFAULT_TARGET


def patch_system_c(path):
    """get_system_uuid(): open("/var/lib/dbus/machine-id") -> TARGET"""
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    if TARGET in src:
        return "already"

    OLD = 'if ((fd = open( "/var/lib/dbus/machine-id", O_RDONLY )) != -1)'
    if OLD not in src:
        return "anchor-miss"
    n = src.count(OLD)
    if n != 1:
        return "anchor-dup(%d)" % n

    NEW = 'if ((fd = open( "%s", O_RDONLY )) != -1)' % TARGET
    src = src.replace(OLD, NEW, 1)
    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    return "patched"


def patch_token_c(path):
    """init_user_sid(): fopen("/etc/machine-id") -> TARGET"""
    src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
    if TARGET in src:
        return "already"

    OLD = 'f = fopen( "/etc/machine-id", "r" );'
    if OLD not in src:
        return "not-proton"
    n = src.count(OLD)
    if n != 1:
        return "anchor-dup(%d)" % n

    NEW = 'f = fopen( "%s", "r" );' % TARGET
    src = src.replace(OLD, NEW, 1)

    # 报错信息里的路径也一起换掉，方便排查（用 @PATH@ 占位避免 %s 打架）
    src = src.replace(
        'fprintf( stderr, "Failed to open /etc/machine-id, error %s.\\n", strerror( errno ));',
        'fprintf( stderr, "Failed to open @PATH@, error %s.\\n", strerror( errno ));')
    src = src.replace(
        'fprintf( stderr, "Failed to read /etc/machine-id, error %s.\\n", strerror( errno ));',
        'fprintf( stderr, "Failed to read @PATH@, error %s.\\n", strerror( errno ));')
    src = src.replace("@PATH@", TARGET)

    io.open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    return "patched"


def main():
    global TARGET
    if len(sys.argv) > 2 and sys.argv[2].strip():
        TARGET = sys.argv[2].strip()
    root = sys.argv[1] if len(sys.argv) > 1 else "."

    print("machine-id 目标路径: %s" % TARGET)

    targets = [
        ("dlls/ntdll/unix/system.c", patch_system_c),
        ("server/token.c",           patch_token_c),
    ]
    for rel, fn in targets:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            print("SKIP: %s 不存在" % rel)
            continue
        try:
            r = fn(p)
        except Exception as e:
            print("WARN: %s 处理异常: %s" % (rel, e))
            continue
        print("%-12s %s" % (r, rel))
    print("OK: machine-id 路径修复完成（或无需修复）")
    return 0  # 永不因本步骤失败而中断构建


if __name__ == "__main__":
    sys.exit(main())
