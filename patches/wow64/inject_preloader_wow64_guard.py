#!/usr/bin/env python3
"""
方案 B：彻底修复 dwproton (x86_64 Wine) 跑在 ARM64 宿主 (box64) 上时，
32 位进程无法启动、prefix 初始化后 syswow64/ 为空的问题。

保留 CI 的 --enable-archs=i386,x86_64。

======================= 症状 =======================
  prefix 初始化后 syswow64/ 始终为空（离线包 0 个文件）。
  日志：
    NtCreateFile L"\\??\\C:\\windows\\syswow64\\rundll32.exe" not found (c0000034)
    err:wineboot:update_wineprefix Wow64Install rundll32 failed to start (machine 014c, err=2)
  同一个 box64 上，用 --enable-archs=x86_64（无 i386-unix/）编出来的包正常。

======================= 根因链（已逐行确认）=======================
1) dwproton 的 Wine 本体是 x86_64（跑在 box64 上）。
   server/registry.c:init_supported_machines() 在 __x86_64__ 下无条件把
   IMAGE_FILE_MACHINE_I386 加进 supported_machines[]，native_machine=AMD64。
   => Wine 认为 I386 是"alternate machine"，应交给**外部 32 位 loader**。

2) wineboot 在 bootstrap 模式下 CreateProcessW(syswow64\rundll32.exe)：
   文件不存在 -> is_builtin_path() 返回 TRUE -> 视为 builtin
   -> exec_wineloader(machine=I386)
        -> get_alternate_wineloader(I386) 返回 "<dll_dir>/i386-unix/wine"
           （因为 is_win64 && I386==get_alt_machine(AMD64)）
        -> preloader_exec() 先 execv "<...>/i386-unix/wine-preloader"，
           再 execv "<...>/i386-unix/wine"

3) 两种包的表现：
   - 单架构 (--enable-archs=x86_64，无 i386-unix/)：
       i386-unix/wine 不存在 -> 两次 execv 失败 -> preloader_exec 落回
       execv(argv[1]) 失败 -> loader_exec 落回 wineloader(x86_64-unix/wine)
       -> box64 跑 64 位 Wine 的**内部 WoW64**(wow64.dll+wow64cpu.dll)
       -> 32 位 rundll32 成功 -> syswow64 正常填满 ✅
   - 双架构 (--enable-archs=i386,x86_64，有 i386-unix/)：
       i386-unix/wine 存在 -> box64 去 exec 这个**真 32 位 ELF**
         * box64 未编 BOX32 且系统无 box86 -> 直接失败 -> _exit(1)
           -> 父进程拿到 exit_code=1 -> CreateProcessW 返回 err=2 ❌
         * 若编了 BOX32 -> 跑起**旧式 32 位宿主 WoW64**，需要
           i386-unix/ntdll.so 等一整套，与 64 位 Wine 的 WoW64 体系冲突 ❌

4) 另外 dwproton 还给 preloader_exec() 加了（上游没有）：
       if (machine == IMAGE_FILE_MACHINE_AMD64
           && ((p=remove_tail(argv[1],"x86_64-unix/wine")) ||
               (p=remove_tail(argv[1],"i386-unix/wine64"))))
           切到 i386-unix/wine64
   第一个匹配项恰是 64 位宿主的 wineloader -> 在 box64 上会把 64 位 wineboot
   误切到 i386-unix/wine64（一个靠 dlopen 64 位 .so 的 32 位 loader），
   box64 下 dlopen 64 位 .so 必失 -> _exit(1)。是第二个叠加病灶。

======================= 修法 =======================
引入运行期判定 host_is_foreign_arch()：
  编译目标是 x86_64 (__x86_64__)，但 uname().machine 不是 x86_64
  （实际是 aarch64/arm64 等）——即"x86_64 Wine 跑在非 x86 宿主上"（box64）。

在**两处**使用它：

  A) loader_exec()：当 host_is_foreign_arch() 为真且 machine 是 I386 时，
     跳过外部 loader 尝试（get_alternate_wineloader 返回的
     <dll_dir>/i386-unix/wine），直接落到 64 位 wineloader，由 Wine 内部
     WoW64 机制处理 32 位 PE —— 与单架构包行为一致（已验证可用）。
     注意：**不改** get_alternate_wineloader 本体，因为 env.c:1972 依赖它
     返回非 NULL 来走 "start.exe /exec" 路由（那也是单架构包正常工作的路径）。

  B) preloader_exec()：dwproton 那段 AMD64->i386-unix/wine64 切换，
     增加 !is_win64 前置条件（只有 32 位宿主 loader 才需要切），
     不再让 64 位宿主误切。

  并且把 A 里"谁是 alternate machine"的语义对齐原生 aarch64 Wine：
  ARM64 宿主下 I386 是**内部 WoW64**，不是外部 loader。

幂等：SENTINEL 标记，重复运行跳过。
"""

import os
import re
import sys

SENTINEL = "/* TERMUX_WOW64_HOSTGUARD */"

# ---------------------------------------------------------------- loader.c
HELPER = """
/* TERMUX_WOW64_HOSTGUARD */
/* x86_64 Wine 跑在非 x86_64 宿主（ARM64/box64、FEX 等）上时返回 TRUE。
 * 此时 box64/FEX 不能像原生内核那样 exec 一个真 32 位 x86 ELF 并混合
 * dlopen 64 位 .so，因此必须走 Wine 内部的 WoW64，而不能去 exec
 * lib/wine/i386-unix/wine。 */
static BOOL host_is_foreign_arch(void)
{
#ifdef __x86_64__
    static int cached = -1;
    if (cached == -1)
    {
        struct utsname buf;
        cached = (uname( &buf ) == 0 &&
                  strcmp( buf.machine, "x86_64" ) && strcmp( buf.machine, "amd64" ));
    }
    return cached;
#else
    return FALSE;
#endif
}
"""

# get_alternate_wineloader 本体不动：env.c:1972 依赖它返回非 NULL 来走
# "start.exe /exec" 路由（那是单架构包已验证可行的路径）。foreign-arch 的
# 跳过逻辑放在 loader_exec() 里，只影响"实际 spawn 子进程"这一步。

OLD_EXEC = """    if (((argv[1] = get_alternate_wineloader( machine )))) preloader_exec( argv, machine );

    argv[1] = strdup( wineloader );"""

NEW_EXEC = """    /* TERMUX_WOW64_HOSTGUARD: x86_64 Wine 在 box64/FEX 上时，不能 exec 外部
     * 32 位 loader（lib/wine/i386-unix/wine）—— box64 未编 BOX32/无 box86 时
     * 无法执行该 32 位 ELF，会导致 wineboot 起 syswow64\\rundll32.exe 时
     * CreateProcessW 立即失败 (err=2)，Wow64Install 不执行，syswow64/ 为空。
     * 此时跳过 external loader，直接用 64 位 wineloader，由 Wine 内部 WoW64
     * （wow64.dll + wow64cpu.dll）处理 32 位 PE —— 与单架构包行为一致。 */
    if (!(machine == IMAGE_FILE_MACHINE_I386 && host_is_foreign_arch()))
    {
        if (((argv[1] = get_alternate_wineloader( machine )))) preloader_exec( argv, machine );
    }

    argv[1] = strdup( wineloader );"""

OLD_PRE = """    if (machine == IMAGE_FILE_MACHINE_AMD64
        && ((p = remove_tail( argv[1], "x86_64-unix/wine" )) || (p = remove_tail( argv[1], "i386-unix/wine64" ))))
    {
        asprintf( &argv[0], "%si386-unix/wine64-preloader", p );
        asprintf( &argv[1], "%si386-unix/wine64", p );
    }
    else
#endif
"""

NEW_PRE = """    if (machine == IMAGE_FILE_MACHINE_AMD64
        && !is_win64
        && ((p = remove_tail( argv[1], "i386-unix/wine" )) || (p = remove_tail( argv[1], "i386-unix/wine64" ))))
    {
        /* TERMUX_WOW64_HOSTGUARD: 只有当前是 32 位宿主 loader（!is_win64）且目标
         * PE 是 AMD64 时，才切到 32 位宿主里的 64 位 loader (i386-unix/wine64)。
         * dwproton 原版用 remove_tail(argv[1],"x86_64-unix/wine") 判定 —— 那恰是
         * 64 位宿主的 wineloader，会让 64 位 wineboot 在 box64 上误切到
         * i386-unix/wine64（靠 dlopen 64 位 .so，box64 下必失）。 */
        asprintf( &argv[0], "%si386-unix/wine64-preloader", p );
        asprintf( &argv[1], "%si386-unix/wine64", p );
    }
    else
#endif
"""


def patch_loader(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()

    if SENTINEL in src:
        print("  [skip] loader.c already patched")
        return True

    changed = False

    # 0) 确保 <sys/utsname.h> 可用（uname / struct utsname）
    if "#include <sys/utsname.h>" not in src:
        inc_anchor = "#include <unistd.h>"
        if inc_anchor in src:
            src = src.replace(inc_anchor, inc_anchor + "\n#include <sys/utsname.h>", 1)
        else:
            src = src.replace("#include <sys/mman.h>",
                              "#include <sys/mman.h>\n#include <sys/utsname.h>", 1)

    # 1) 插入 helper（放在 get_alternate_wineloader 的定义之前）
    anchor = "char *get_alternate_wineloader( WORD machine )"
    if anchor not in src:
        print("  [WARN] get_alternate_wineloader anchor not found")
        return False
    src = src.replace(anchor, HELPER + "\n" + anchor, 1)
    changed = True

    # 2) loader_exec: foreign-arch 宿主上跳过外部 32 位 loader
    if OLD_EXEC not in src:
        print("  [WARN] loader_exec block not found")
        return False
    src = src.replace(OLD_EXEC, NEW_EXEC, 1)

    # 3) preloader_exec: 修 AMD64 切换条件
    if OLD_PRE not in src:
        print("  [WARN] preloader_exec block not found")
        return False
    src = src.replace(OLD_PRE, NEW_PRE, 1)

    if changed:
        with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(src)
        print("  [ok] patched loader.c (host_is_foreign_arch + loader_exec + preloader_exec)")
    return True


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ".."
    target = os.path.join(root, "dlls", "ntdll", "unix", "loader.c")
    if not os.path.isfile(target):
        print("  [skip] %s not found" % target)
        return 0
    patch_loader(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
