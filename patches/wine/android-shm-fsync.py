#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Termux/Android 适配补丁（针对 Proton 派生的 wine 树，幂等）

1) server/fsync.c
   a. 保留该树"fsync 默认开启"的设计（Proton 的 inproc_sync 层假设 fsync/ntsync
      至少有一个可用；关掉 fsync 会落进它没设计的"两者都没有"状态 -> 崩）。
      只把没有 /dev/shm 的问题用 b. 的兜底解决。
   b. 即便启用，shm_open 失败时退到 socket 目录（Termux tmp）里的普通文件；
      再失败就干净地放弃 fsync —— 关键是不再"假装初始化成功"，
      避免后续 mmap(-1) 失败后把 -1 塞进 shm_addrs，写它 => wineserver SIGSEGV。

2) server/token.c
   /etc/machine-id 缺失时用 /var/lib/dbus/machine-id 或随机值派生，
   消除 "Failed to open /etc/machine-id" 并保证 local_user_sid 结构完整。

3) dlls/ntdll/unix/fsync.c（客户端，如存在同样默认关闭）
"""
import io
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "."
applied = 0
missed = []


def patch_file(path, pairs, optional=False):
    global applied
    p = os.path.join(SRC, path)
    if not os.path.exists(p):
        print("[skip] 文件不存在: %s" % path)
        return
    s = io.open(p, encoding="utf-8", errors="surrogateescape").read()
    orig = s
    for name, old, new in pairs:
        if old in s:
            s = s.replace(old, new, 1)
            print("[ok ] %s :: %s" % (path, name))
            applied += 1
        else:
            print("[--] %s :: %s (未匹配，可能已打过或该树结构不同)" % (path, name))
            if not optional:
                missed.append("%s:%s" % (path, name))
    if s != orig:
        io.open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)


# ---------------------------------------------------------------- 1) server/fsync.c
FSYNC_OPEN_OLD = ('    shm_fd = shm_open( shm_name, O_RDWR | O_CREAT | O_EXCL, 0644 );\n'
                  '    if (shm_fd == -1)\n'
                  '        perror( "shm_open" );\n')
FSYNC_OPEN_NEW = ('    shm_fd = shm_open( shm_name, O_RDWR | O_CREAT | O_EXCL, 0644 );\n'
                  '    if (shm_fd == -1)\n'
                  '    {\n'
                  '        /* [CI] shm_open 走 /dev/shm，Android 上没有；退到 socket 目录（Termux tmp）里的普通文件 */\n'
                  '        shm_fd = openat( config_dir_fd, "wine-fsync-shm", O_RDWR | O_CREAT | O_EXCL, 0644 );\n'
                  '        if (shm_fd == -1)\n'
                  '        {\n'
                  '            perror( "fsync: no usable shm, fsync disabled" );\n'
                  '            return;  /* [CI] 干净地放弃 fsync，不设置 is_fsync_initialized */\n'
                  '        }\n'
                  '        fprintf( stderr, "fsync: using fallback shm in server dir\\n" );\n'
                  '    }\n')

FSYNC_UNLINK_OLD = ('    close( shm_fd );\n'
                    '    if (shm_unlink( shm_name ) == -1)\n'
                    '        perror( "shm_unlink" );\n')
FSYNC_UNLINK_NEW = ('    if (shm_fd >= 0) close( shm_fd );\n'
                    '    if (shm_unlink( shm_name ) == -1 && debug_level)\n'
                    '        perror( "shm_unlink" );\n'
                    '    unlink( "wine-fsync-shm" );  /* [CI] 兜底路径的清理 */\n')

patch_file("server/fsync.c", [
    ("shm_open 兜底到 Termux tmp", FSYNC_OPEN_OLD, FSYNC_OPEN_NEW),
    ("清理兜底 shm 文件", FSYNC_UNLINK_OLD, FSYNC_UNLINK_NEW),
])

# --------------------------------------------------------------- 2) server/token.c
TOKEN_OLD = ('    f = fopen( "/etc/machine-id", "r" );\n'
             '    if (!f)\n'
             '    {\n'
             '        fprintf( stderr, "Failed to open /etc/machine-id, error %s.\\n", strerror( errno ));\n'
             '        return;\n'
             '    }\n')
TOKEN_NEW = ('    f = fopen( "/etc/machine-id", "r" );\n'
             '    if (!f) f = fopen( "/var/lib/dbus/machine-id", "r" );\n'
             '    if (!f)\n'
             '    {\n'
             '        /* [CI] Android/Termux 没有 machine-id 文件：用随机值派生，保证 SID 结构完整 */\n'
             '        unsigned int r = 0;\n'
             '        FILE *ur = fopen( "/proc/sys/kernel/random/uuid", "r" );\n'
             '        if (ur) { if (fscanf( ur, "%8x", &r ) != 1) r = 0; fclose( ur ); }\n'
             '        if (!r) r = (unsigned int)getpid() * 2654435761u;\n'
             '        snprintf( machine_id, sizeof(machine_id), "%08x%08x", r, (unsigned int)getuid() );\n'
             '        machine_id[16] = 0;\n'
             '        goto have_machine_id;\n'
             '    }\n')

TOKEN_LABEL_OLD = ('    machine_id[n] = 0;\n'
                   '    id = strtoull( machine_id, NULL, 0x10 );\n')
TOKEN_LABEL_NEW = ('    machine_id[n] = 0;\n'
                   'have_machine_id:\n'
                   '    id = strtoull( machine_id, NULL, 0x10 );\n')

patch_file("server/token.c", [
    ("machine-id 缺失时派生", TOKEN_OLD, TOKEN_NEW),
    ("加入跳转标签", TOKEN_LABEL_OLD, TOKEN_LABEL_NEW),
])

# ------------------------------------------- 3) dlls/ntdll/unix/fsync.c（客户端，可选）
CLIENT_PAIRS = [
    ("客户端 shm 兜底（与 server 一致）",
     '    if ((shm_fd = shm_open( shm_name, O_RDWR, 0644 )) == -1)\n'
     '    {\n'
     '        /* probably the server isn\'t running with WINEFSYNC, tell the user and bail */\n',
     '    if ((shm_fd = shm_open( shm_name, O_RDWR, 0644 )) == -1)\n'
     '    {\n'
     '        /* [CI] Android 没有 /dev/shm：退回 server 目录里的普通文件（与服务端同一路径） */\n'
     '        char fb[512];\n'
     '        snprintf( fb, sizeof(fb), "%s/wine-fsync-shm", config_dir );\n'
     '        shm_fd = open( fb, O_RDWR, 0644 );\n'
     '    }\n'
     '    if (shm_fd == -1)\n'
     '    {\n'),
]
patch_file("dlls/ntdll/unix/fsync.c", CLIENT_PAIRS, optional=True)


# ------------------------------------------------- 4) 中性化 inproc/ntsync 层
# 这棵树（Proton 的 inproc_sync）假设"fsync 或 ntsync 至少有一个可用"；
# Android 上 /dev/ntsync 不存在，某些组合会落进它没设计的路径。
# 这里把它变成"从不使用 in-process device"，与 Valve 树（根本没有这层）行为一致。
INPROC_PAIRS = [
    ("inproc_sync.c: 永不使用 /dev/ntsync",
     '            fd = open( "/dev/ntsync", O_CLOEXEC | O_RDONLY );\n',
     '            fd = -1;  /* [CI] Android: never use ntsync (no /dev/ntsync); fall back cleanly */\n'),
]
patch_file("server/inproc_sync.c", INPROC_PAIRS, optional=True)

THREAD_PAIRS = [
    ("thread.c: init_thread 显式声明没有 inproc device",
     '    if (do_fsync())\n'
     '    {\n'
     '        reply->inproc_device = FSYNC_USED_BY_SERVER;\n'
     '    }\n'
     '    else if ((fd = get_inproc_device_fd()) >= 0)\n',
     '    reply->inproc_device = 0;  /* [CI] 默认：没有 in-process device */\n'
     '    if (do_fsync())\n'
     '    {\n'
     '        reply->inproc_device = FSYNC_USED_BY_SERVER;\n'
     '    }\n'
     '    else if ((fd = get_inproc_device_fd()) >= 0)\n'),
    ("thread.c: 没有 inproc 对象时不要报错",
     '    if ((fd = get_inproc_sync_fd( current->alert_sync )) < 0) set_error( STATUS_INVALID_PARAMETER );\n',
     '    if ((fd = get_inproc_sync_fd( current->alert_sync )) < 0)\n'
     '    {\n'
     '        /* [CI] 没有 in-process sync 对象：明确返回"没有"，不要报错打断客户端初始化 */\n'
     '        reply->fsync_shm_idx = -1;\n'
     '        reply->handle = 0;\n'
     '    }\n'),
]
patch_file("server/thread.c", THREAD_PAIRS, optional=True)

print("----")
print("共应用 %d 处；未匹配 %d 处" % (applied, len(missed)))
if missed:
    print("未匹配清单: %s" % ", ".join(missed))
    sys.exit(1)
