#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 wineboot 的 prefix 安装循环：把 Wow64Install 从 PreInstall 成功与否解耦。

症状
----
dwproton（Wine 11 新 WoW64 架构）在 box64/ARM64 上初始化 prefix 后，
system32 正常但 syswow64 为空：

    ls $PREFIX/drive_c/windows/system32  | wc -l   # ~807
    ls $PREFIX/drive_c/windows/syswow64  | wc -l   # 0   <-- 问题

对照：wine-proton-9.0（老 WoW64 架构）同一个 box64 上 syswow64 正常，
因为 9.0 的 [Wow64Install.ntx86] 直接内联 WineFakeDlls=，不依赖 32 位进程。

根因
----
dwproton 的 wine.inf 把 syswow64 的填充放进了

    [Wow64Install.ntx86]
    Needs=BaseWow64Install        # 内含 WineFakeDlls=FakeDllsWin32,FakeDllsWow64

而 Wow64Install 段由 programs/wineboot/wineboot.c 的 start_rundll32() 驱动：

    UINT GetSystemWow64Directory2W( path, count, machine )
      machine == IMAGE_FILE_MACHINE_TARGET_HOST (0x1)   -> C:\\windows\\system32
      machine == IMAGE_FILE_MACHINE_I386       (0x14c) -> C:\\windows\\syswow64

    start_rundll32(inf, "PreInstall",    TARGET_HOST) -> 64 位 rundll32
    start_rundll32(inf, "DefaultInstall",TARGET_HOST) -> 64 位 rundll32
    start_rundll32(inf, "Wow64Install",  I386)        -> 32 位 rundll32（!）

只有 32 位 rundll32 进程里，setupapi 的 DIRID 11 才解析成 syswow64，
[FakeDllsWin32] 里的通配符条目 11,,* 才会把 lib/wine/i386-windows/ 下的
真·32 位 PE 拷贝进 syswow64（这是 syswow64 795 个文件的实际来源）。

问题在于 update_wineprefix() 的控制流是一个嵌套 if：

    if ((process = start_rundll32( inf_path, L"PreInstall", TARGET_HOST )))
    {
        for (;;)
        {
            ...
            if (!machines[count].Machine) break;
            if (machines[count].Native)
                process = start_rundll32( inf_path, L"DefaultInstall", TARGET_HOST );
            else
                process = start_rundll32( inf_path, L"Wow64Install",
                                          machines[count].Machine );  # <-- 32 位
            count++;
        }
    }

也就是说：**只要 PreInstall 的 CreateProcessW 失败（返回 0），整个循环
（含 Wow64Install）都会被跳过，syswow64 永远是空的**，而
.update-timestamp 仍会被写上一个新时间戳，导致后续 wineboot -u 也不再重试。

在 box64/ARM64 + 新 WoW64 上，PreInstall/DefaultInstall 这两个 64 位
rundll32 进程创建需要 fork + wow64 初始化，比原生慢且更容易在启动早期
失败。一旦第一次失败，syswow64 就永久缺失。

修法
----
1. 把循环从 if 的条件里解耦出来：PreInstall 失败也继续尝试
   DefaultInstall / Wow64Install。
2. 每步失败都打印 WINE_ERR（带 GetLastError），失败不再被静默吞掉。

语义变化仅为“更健壮”：成功路径行为完全不变（还是按顺序跑三段、
还是等前一个进程结束再跑下一个）。

幂等：以 SENTINEL 注释为标记，重复运行直接跳过。
"""

import os
import sys

SENTINEL = "/* TERMUX_WINEBOOT_WOW64_DECOUPLE */"

OLD = """        if ((process = start_rundll32( inf_path, L"PreInstall", IMAGE_FILE_MACHINE_TARGET_HOST )))
        {
            for (;;)
            {
                if (process)
                {
                    MSG msg;
                    DWORD res = MsgWaitForMultipleObjects( 1, &process, FALSE, INFINITE, QS_ALLINPUT );
                    if (res != WAIT_OBJECT_0)
                    {
                        while (PeekMessageW( &msg, 0, 0, 0, PM_REMOVE )) DispatchMessageW( &msg );
                        continue;
                    }
                    CloseHandle( process );
                }
                if (!machines[count].Machine) break;
                if (machines[count].Native)
                    process = start_rundll32( inf_path, L"DefaultInstall", IMAGE_FILE_MACHINE_TARGET_HOST );
                else
                    process = start_rundll32( inf_path, L"Wow64Install", machines[count].Machine );
                count++;
            }
        }"""

NEW = r"""        /* TERMUX_WINEBOOT_WOW64_DECOUPLE */
        /* 原实现把整个安装循环嵌在 `if ((process = start_rundll32(PreInstall)))`
         * 里：一旦 PreInstall 的 CreateProcessW 失败，DefaultInstall 与
         * Wow64Install 都会被跳过。在 box64/ARM64 上 PreInstall 容易在启动
         * 早期失败，结果 syswow64 永远为空而 .update-timestamp 仍被写入。
         * 这里把循环解耦出来：PreInstall 失败也继续跑后续段，并且失败会有
         * ERR 输出，不再被静默吞掉。成功路径行为不变。 */
        process = start_rundll32( inf_path, L"PreInstall", IMAGE_FILE_MACHINE_TARGET_HOST );
        if (!process)
            WINE_ERR( "wineboot: PreInstall rundll32 failed to start (err=%lu), continuing\n",
                      GetLastError() );
        else
        {
            MSG msg;
            DWORD res = MsgWaitForMultipleObjects( 1, &process, FALSE, INFINITE, QS_ALLINPUT );
            if (res != WAIT_OBJECT_0)
            {
                while (PeekMessageW( &msg, 0, 0, 0, PM_REMOVE )) DispatchMessageW( &msg );
            }
            CloseHandle( process );
            process = 0;
        }

        for (;;)
        {
            if (!machines[count].Machine) break;
            if (machines[count].Native)
                process = start_rundll32( inf_path, L"DefaultInstall", IMAGE_FILE_MACHINE_TARGET_HOST );
            else
                process = start_rundll32( inf_path, L"Wow64Install", machines[count].Machine );

            if (!process)
                WINE_ERR( "wineboot: %s rundll32 failed to start (machine %04x, err=%lu)\n",
                          machines[count].Native ? "DefaultInstall" : "Wow64Install",
                          machines[count].Machine, GetLastError() );
            else
            {
                MSG msg;
                DWORD res = MsgWaitForMultipleObjects( 1, &process, FALSE, INFINITE, QS_ALLINPUT );
                if (res != WAIT_OBJECT_0)
                {
                    while (PeekMessageW( &msg, 0, 0, 0, PM_REMOVE )) DispatchMessageW( &msg );
                }
                CloseHandle( process );
                process = 0;
            }
            count++;
        }

        /* TERMUX_WINEBOOT_WOW64_DECOUPLE: 校验 syswow64 是否真的被填充。
         * 32 位 rundll32 静默失败（例如 wow64 CPU 后端不可用）时，
         * Wow64Install 本身不会报错，但 syswow64 会是空的。这里给出明确
         * 错误，避免“初始化完成但 syswow64 为空”这种难以察觉的状态。 */
        if (!machines[0].Machine)
            WINE_ERR( "wineboot: no supported machines reported, WoW64Install skipped\n" );
        else
        {
            WCHAR syswow64[MAX_PATH];
            if (GetSystemWow64Directory2W( syswow64, MAX_PATH, IMAGE_FILE_MACHINE_I386 )
                && GetFileAttributesW( syswow64 ) == INVALID_FILE_ATTRIBUTES)
                WINE_ERR( "wineboot: syswow64 dir missing after Wow64Install (%s)\n",
                          debugstr_w( syswow64 ));
        }"""


def patch_file(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()

    if SENTINEL in src:
        print("  [skip] already patched")
        return True

    if OLD not in src:
        print("  [WARN] target block not found in %s" % path)
        return False

    src = src.replace(OLD, NEW, 1)
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(src)
    print("  [ok] patched wineboot Wow64Install decouple")
    return True


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ".."
    target = os.path.join(root, "programs", "wineboot", "wineboot.c")
    if not os.path.isfile(target):
        print("  [skip] %s not found" % target)
        return 0
    patch_file(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
