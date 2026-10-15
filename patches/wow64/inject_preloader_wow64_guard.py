#!/usr/bin/env python3
"""
修复 dlls/ntdll/unix/loader.c 的 preloader_exec() 在 "x86_64 Wine 跑在 ARM64 宿主
(box64/FEX)" 场景下错误走 WoW64 分支的问题。

症状：
  wine: created the configuration directory ...
  wine: could not load kernel32.dll, status c0000135
  以及 WINEBOOTSTRAPMODE=1 时的
  Application could not be started, or no application associated with the specified file.
  ShellExecuteEx failed: Environment variable not found.
  日志里 wineserver 被 spawn，但 wineboot.exe 子进程秒退：
    get_new_process_info() = 0 { success=0, exit_code=1 }
    err:environ:run_wineboot failed to start wineboot 1

根因：
  Proton 的 WoW64-on-ARM64 补丁给 preloader_exec() 加了一段
    #if !defined(__arm__) && !defined(__aarch64__)
        if (machine == IMAGE_FILE_MACHINE_AMD64 &&
            ((p = remove_tail(argv[1], "x86_64-unix/wine")) ||
             (p = remove_tail(argv[1], "i386-unix/wine64"))))
        {
            asprintf(&argv[0], "%si386-unix/wine64-preloader", p);
            asprintf(&argv[1], "%si386-unix/wine64", p);
        }
        else
    #endif
  __aarch64__/__arm__ 指的是 *编译目标* 的宿主架构。dwproton 的 Wine 本体是
  x86_64 二进制（跑在 box64 上），编译时 __aarch64__ 未定义，于是这段被编入。
  运行时 machine 是 IMAGE_FILE_MACHINE_AMD64（wineboot.exe 是 64 位），条件成立，
  wineloader 被换成 <prefix>/lib/wine/i386-unix/wine64 —— 但 x86_64 wow64 包
  根本没有 i386-unix/ 目录，两次 execv 都失败 -> _exit(1) -> run_wineboot failed。

  上游 Wine 9.0/10.0 的 preloader_exec() 没有这段，所以老包正常。

修法：
  保留 ARM64 原生 WoW64 的语义，但把 "是否切换" 从编译期常量改成
  运行时探测：只有 i386-unix/wine64 真的存在时才切换。
  - ARM64 原生 WoW64 包（有 i386-unix/）行为不变；
  - x86_64 wine on box64/FEX（无 i386-unix/）自动跳过，退回 %s-preloader。

幂等：以 SENTINEL 注释为标记，重复运行直接跳过。
"""

import os
import sys

SENTINEL = "/* TERMUX_WOW64_PRELOADER_GUARD */"

OLD = """    if (machine == IMAGE_FILE_MACHINE_AMD64
        && ((p = remove_tail( argv[1], "x86_64-unix/wine" )) || (p = remove_tail( argv[1], "i386-unix/wine64" ))))
    {
        asprintf( &argv[0], "%si386-unix/wine64-preloader", p );
        asprintf( &argv[1], "%si386-unix/wine64", p );
    }
    else"""

NEW = """    if (machine == IMAGE_FILE_MACHINE_AMD64
        && ((p = remove_tail( argv[1], "x86_64-unix/wine" )) || (p = remove_tail( argv[1], "i386-unix/wine64" ))))
    {
        /* TERMUX_WOW64_PRELOADER_GUARD */
        /* 只有 i386-unix/wine64 真实存在时才切到 WoW64 loader。
         * Proton 用编译期 __aarch64__ 判断宿主架构，但在
         * "x86_64 Wine 跑在 box64/FEX" 时该宏未定义，这段被错误编入，
         * 会把 wineloader 指向不存在的 i386-unix/wine64 并导致
         * wineboot/子进程创建失败 (run_wineboot failed ... 1)。 */
        char *wow64_path;
        asprintf( &wow64_path, "%si386-unix/wine64", p );
        if (access( wow64_path, X_OK ) == 0)
        {
            asprintf( &argv[0], "%si386-unix/wine64-preloader", p );
            argv[1] = wow64_path;
        }
        else
        {
            free( wow64_path );
            asprintf( &argv[0], "%s-preloader", argv[1] );
        }
    }
    else"""


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
    print("  [ok] patched preloader_exec WoW64 guard")
    return True


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ".."
    target = os.path.join(root, "dlls", "ntdll", "unix", "loader.c")
    if not os.path.isfile(target):
        print("  [skip] %s not found" % target)
        return 0
    patch_file(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
