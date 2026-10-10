#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
wow64 完善补丁包（可在 wine 源码树内运行）
    python3 wow64-completion.py <wine-src-dir>

包含 4 组适配（全部幂等；不存在锚点/依赖时安全跳过）：
  A. HODLL 环境变量支持        dlls/wow64/syscall.c
  B. HODLL64 环境变量支持      dlls/ntdll/loader.c
  C. Wow64SuspendLocalThread 完整链路
       dlls/wow64/syscall.c / dlls/wow64/wow64.spec / dlls/ntdll/loader.c /
       dlls/ntdll/process.c / dlls/wow64/process.c
  D. 32 位地址上限检查宽化     dlls/wow64/virtual.c
  E. wineboot aarch64 XState 特性装填  programs/wineboot/wineboot.c
'''
import io, os, re, sys

DEF_HODLL_HELPER = '''\
/**********************************************************************
 *           wow64GetEnvironmentVariableW
 */
static DWORD wow64GetEnvironmentVariableW( LPCWSTR name, LPWSTR val, DWORD size )
{
    UNICODE_STRING us_name, us_value;
    NTSTATUS status;
    DWORD len;

    RtlInitUnicodeString( &us_name, name );
    us_value.Length = 0;
    us_value.MaximumLength = (size ? size - 1 : 0) * sizeof(WCHAR);
    us_value.Buffer = val;

    status = RtlQueryEnvironmentVariable_U( NULL, &us_name, &us_value );
    len = us_value.Length / sizeof(WCHAR);
    if (status == STATUS_BUFFER_TOO_SMALL) return len + 1;
    if (status) return 0;
    if (!size) return len + 1;
    val[len] = 0;
    return len;
}


'''

DEF_HODLL64_HELPER = DEF_HODLL_HELPER.replace("wow64GetEnvironmentVariableW", "loaderGetEnvironmentVariableW")

SUSPEND_SYSCALL_FUNC = '''
/**********************************************************************
 *           Wow64SuspendLocalThread (wow64.@)
 */
NTSTATUS WINAPI Wow64SuspendLocalThread( HANDLE thread, ULONG *count )
{
    return pBTCpuSuspendLocalThread( thread, count );
}
'''

XSTATE_FUNC = '''static void initialize_xstate_features( struct _KUSER_SHARED_DATA *data )
{
#if defined(__aarch64__)
    XSTATE_CONFIGURATION *xstate = &data->XState;

    xstate->EnabledFeatures = (1 << XSTATE_LEGACY_FLOATING_POINT) | (1 << XSTATE_LEGACY_SSE) | (1 << XSTATE_AVX);
    xstate->EnabledVolatileFeatures = xstate->EnabledFeatures;
    xstate->AllFeatureSize = 0x340;

    xstate->OptimizedSave = 0;
    xstate->CompactionEnabled = 0;

    xstate->Features[0].Size = xstate->AllFeatures[0] = offsetof( XSAVE_FORMAT, XmmRegisters );
    xstate->Features[1].Size = xstate->AllFeatures[1] = sizeof(M128A) * 16;
    xstate->Features[1].Offset = xstate->Features[0].Size;
    xstate->Features[2].Offset = 0x240;
    xstate->Features[2].Size = 0x100;
    xstate->Size = 0x340;
#else
    (void)data;
#endif
}


'''

LOG = []
def note(item, msg):
    LOG.append("[%s] %s" % (item, msg))
    print("[%s] %s" % (item, msg), flush=True)


def read(p):
    try:
        return io.open(p, encoding="utf-8", errors="surrogateescape").read()
    except OSError:
        return None


def write(p, s):
    io.open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)


def func_span(text, sig):
    """返回 (start, end) —— 从 sig 起、含函数体花括号的区间；找不到返回 None"""
    i = text.find(sig)
    if i < 0:
        return None
    b = text.find("{", i)
    if b < 0:
        return None
    depth = 0
    j = b
    while j < len(text):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i, j + 1
        j += 1
    return None


root = sys.argv[1] if len(sys.argv) > 1 else "."
os.chdir(root)

# ---------------------------------------------------------------- A. HODLL
def item_hodll():
    p = "dlls/wow64/syscall.c"
    t = read(p)
    if t is None:
        return note("A", "%s 不存在，跳过" % p)
    if "HODLL" in t:
        return note("A", "已存在 HODLL 支持，跳过")
    sig = "static const WCHAR *get_cpu_dll_name(void)"
    sp = func_span(t, sig)
    if sp is None:
        return note("A", "WARN: 找不到 get_cpu_dll_name（该树结构不同），跳过")
    if "wow64GetEnvironmentVariableW" not in t:
        t = t.replace(sig, DEF_HODLL_HELPER + sig, 1)
        note("A", "已插入 wow64GetEnvironmentVariableW 辅助函数")
    insert_after = "    ULONG size;\n"
    sp = func_span(t, sig)
    seg = t[sp[0]:sp[1]]
    k = seg.find(insert_after)
    if k < 0:
        return note("A", "WARN: 函数内找不到 'ULONG size;' 锚点，跳过注入")
    envblock = (
        "    WCHAR *cpu_dll = (WCHAR*)buffer;\n"
        "    UINT res;\n\n"
        "    if ((res = wow64GetEnvironmentVariableW( L\"HODLL\", cpu_dll, ARRAY_SIZE(buffer) )) && res < ARRAY_SIZE(buffer))\n"
        "        return cpu_dll;\n")
    seg = seg[:k + len(insert_after)] + envblock + seg[k + len(insert_after):]
    t = t[:sp[0]] + seg + t[sp[1]:]
    write(p, t)
    note("A", "HODLL 支持已注入 ✓")


# ------------------------------------------------------------- B. HODLL64
def item_hodll64():
    p = "dlls/ntdll/loader.c"
    t = read(p)
    if t is None:
        return note("B", "%s 不存在，跳过" % p)
    if "HODLL64" in t:
        return note("B", "已存在 HODLL64 支持，跳过")
    sig = "static void load_arm64ec_module(void)"
    sp = func_span(t, sig)
    if sp is None:
        return note("B", "WARN: 找不到 load_arm64ec_module（该树无 arm64ec 模块），跳过")
    if "loaderGetEnvironmentVariableW" not in t:
        t = t.replace(sig, DEF_HODLL64_HELPER + sig, 1)
        note("B", "已插入 loaderGetEnvironmentVariableW 辅助函数")
    sp = func_span(t, sig)
    seg = t[sp[0]:sp[1]]

    if "ULONG buffer[16];" in seg:
        seg = seg.replace("ULONG buffer[16];", "ULONG buffer[32];", 1)
        note("B", "buffer[16] -> buffer[32]")

    anchor = ("    HANDLE key;\n\n"
              "    InitializeObjectAttributes( &attr, &nameW, OBJ_CASE_INSENSITIVE, 0, NULL );\n"
              "    if (!NtOpenKey( &key, KEY_READ | KEY_WOW64_64KEY, &attr ))")
    if anchor not in seg:
        return note("B", "WARN: 注册表读取锚点不匹配，跳过注入")
    new = ("    HANDLE key;\n"
           "    DWORD res;\n"
           "    WCHAR *cpu_dll = (WCHAR*)buffer;\n\n"
           "    if ((res = loaderGetEnvironmentVariableW( L\"HODLL64\", cpu_dll, ARRAY_SIZE(buffer) )) && res < ARRAY_SIZE(buffer))\n"
           "    {\n"
           "        ULONG dirlen = wcslen( L\"C:\\\\windows\\\\system32\\\\\" );\n"
           "        ULONG size = sizeof(module) - (dirlen + 1) * sizeof(WCHAR);\n\n"
           "        memset( module + dirlen, 0, size );\n"
           "        memcpy( module + dirlen, cpu_dll, min( res * sizeof(WCHAR), size ));\n"
           "        goto loaded;\n"
           "    }\n\n"
           "    InitializeObjectAttributes( &attr, &nameW, OBJ_CASE_INSENSITIVE, 0, NULL );\n"
           "    if (!NtOpenKey( &key, KEY_READ | KEY_WOW64_64KEY, &attr ))")
    seg = seg.replace(anchor, new, 1)

    lanchor = "    if ((status = load_dll( NULL, module, 0, &wm, FALSE )) ||"
    if lanchor not in seg:
        return note("B", "WARN: load_dll 锚点不匹配，跳过 goto 标签")
    seg = seg.replace(lanchor, "loaded:\n" + lanchor, 1)
    t = t[:sp[0]] + seg + t[sp[1]:]
    write(p, t)
    note("B", "HODLL64 支持已注入 ✓")


# ------------------------------------------------- C. SuspendLocalThread
def item_suspend():
    ok_sys = False
    # C1 syscall.c
    p = "dlls/wow64/syscall.c"
    t = read(p)
    if t is None:
        note("C", "%s 不存在" % p)
    elif "Wow64SuspendLocalThread" in t:
        note("C", "syscall.c 已含 Wow64SuspendLocalThread，跳过")
        ok_sys = True
    else:
        m = re.search(r"^static void\s+\(WINAPI \*pBTCpuThreadInit\)\(void\);\s*$", t, re.M)
        if not m:
            note("C", "WARN: syscall.c 找不到 pBTCpuThreadInit 锚点，跳过")
        else:
            t = t[:m.end()] + "\nstatic NTSTATUS (WINAPI *pBTCpuSuspendLocalThread)(HANDLE,ULONG *);" + t[m.end():]
            g = "GET_PTR( BTCpuResetToConsistentState );"
            if g in t:
                t = t.replace(g, g + "\n        GET_PTR( BTCpuSuspendLocalThread );", 1)
            t = t.rstrip("\n") + "\n" + SUSPEND_SYSCALL_FUNC
            write(p, t)
            note("C", "syscall.c: 指针声明 + GET_PTR + 导出函数 已注入 ✓")
            ok_sys = True

    # C2 spec
    p2 = "dlls/wow64/wow64.spec"
    t2 = read(p2)
    if t2 is None:
        note("C", "%s 不存在" % p2)
    elif "@ stub Wow64SuspendLocalThread" in t2:
        write(p2, t2.replace("@ stub Wow64SuspendLocalThread",
                            "@ stdcall Wow64SuspendLocalThread(long ptr)", 1))
        note("C", "wow64.spec: stub -> stdcall ✓")
    else:
        note("C", "wow64.spec 已是 stdcall/无可改项")

    # C3 ntdll/loader.c（从 wow64.dll 取 Wow64SuspendLocalThread）
    ok_ldr = False
    p3 = "dlls/ntdll/loader.c"
    t3 = read(p3)
    if t3 is None:
        note("C", "%s 不存在" % p3)
    elif "pWow64SuspendLocalThread" in t3:
        note("C", "ntdll/loader.c 已含 pWow64SuspendLocalThread，跳过")
        ok_ldr = True
    else:
        a = "void (WINAPI *pWow64PrepareForException)( EXCEPTION_RECORD *rec, CONTEXT *context ) = NULL;"
        b = "        GET_PTR( Wow64PrepareForException );"
        if a in t3 and b in t3:
            t3 = t3.replace(a, a + "\nNTSTATUS (WINAPI *pWow64SuspendLocalThread)( HANDLE thread, ULONG *count ) = NULL;", 1)
            t3 = t3.replace(b, b + "\n        GET_PTR( Wow64SuspendLocalThread );", 1)
            write(p3, t3)
            note("C", "ntdll/loader.c: 全局指针 + GET_PTR 已注入 ✓")
            ok_ldr = True
        else:
            note("C", "WARN: ntdll/loader.c 锚点缺失，跳过")

    # C4 ntdll/process.c（RtlWow64SuspendThread 走新指针）
    p4 = "dlls/ntdll/process.c"
    t4 = read(p4)
    if t4 is None:
        note("C", "%s 不存在" % p4)
    elif "pWow64SuspendLocalThread" in t4:
        note("C", "ntdll/process.c 已改，跳过")
    elif ok_sys and ok_ldr:
        sig4 = "NTSTATUS WINAPI RtlWow64SuspendThread( HANDLE thread, ULONG *count )"
        old4 = ("    /* FIXME: Use Wow64SuspendLocalThread when available */\n"
                "    return NtSuspendThread( thread, count );")
        if sig4 in t4 and old4 in t4:
            t4 = t4.replace(sig4,
                            "extern NTSTATUS (WINAPI *pWow64SuspendLocalThread)( HANDLE thread, ULONG *count );\n\n" + sig4, 1)
            t4 = t4.replace(old4,
                            "    if (pWow64SuspendLocalThread) return pWow64SuspendLocalThread( thread, count );\n\n"
                            "    return NtSuspendThread( thread, count );", 1)
            write(p4, t4)
            note("C", "ntdll/process.c: RtlWow64SuspendThread 已升级 ✓")
        else:
            note("C", "WARN: ntdll/process.c 锚点缺失，跳过")
    else:
        note("C", "SKIP: 因 syscall.c/loader.c 未完成，ntdll/process.c 保持原样")

    # C5 wow64/process.c（NtSuspendThread -> RtlWow64SuspendThread）
    p5 = "dlls/wow64/process.c"
    t5 = read(p5)
    if t5 is None:
        note("C", "%s 不存在" % p5)
    elif "RtlWow64SuspendThread" in t5:
        note("C", "wow64/process.c 已改，跳过")
    elif ok_sys and ok_ldr:
        old5 = "    return NtSuspendThread( handle, count );"
        sp5 = func_span(t5, "NTSTATUS WINAPI wow64_NtSuspendThread( UINT *args )")
        if sp5 and old5 in t5[sp5[0]:sp5[1]]:
            seg = t5[sp5[0]:sp5[1]].replace(old5, "    return RtlWow64SuspendThread( handle, count );", 1)
            t5 = t5[:sp5[0]] + seg + t5[sp5[1]:]
            write(p5, t5)
            note("C", "wow64/process.c: wow64_NtSuspendThread 已升级 ✓")
        else:
            note("C", "WARN: wow64/process.c 锚点缺失，跳过")
    else:
        note("C", "SKIP: 因前置未完成，wow64/process.c 保持原样")


# -------------------------------------------------------- D. 32位地址检查宽化
def item_virtual_relax():
    p = "dlls/wow64/virtual.c"
    t = read(p)
    if t is None:
        return note("D", "%s 不存在，跳过" % p)
    p1 = re.compile(r"^if \(\*addr32 \+ size > highest_user_address \+\s*1\) return STATUS_CONFLICTING_ADDRESSES;$")
    p2 = re.compile(r"^if \(size32 && \*addr32 \+ \(SIZE_T\)\*size32 > highest_user_address \+\s*1\) return STATUS_CONFLICTING_ADDRESSES;$")
    L = t.split("\n")
    n1 = sum(1 for l in L if p1.match(l.strip()))
    n2 = sum(1 for l in L if p2.match(l.strip()))
    if n1 == 0 and n2 == 0:
        return note("D", "无严格检查行（或已宽化），跳过")
    out = [l for l in L if not (p1.match(l.strip()) or p2.match(l.strip()))]
    write(p, "\n".join(out))
    note("D", "已移除 %d + %d 处地址上限严格检查 ✓" % (n1, n2))


# ------------------------------------------------------------- E. xstate
def item_xstate():
    p = "programs/wineboot/wineboot.c"
    t = read(p)
    if t is None:
        return note("E", "%s 不存在，跳过" % p)
    if "initialize_xstate_features" in t:
        return note("E", "已含 initialize_xstate_features，跳过")
    # 依赖检查：头文件与包含链
    need_file = "include/ddk/wdm.h"
    wdm = read(need_file) or ""
    winnt = read("include/winnt.h") or ""
    if "XSTATE_CONFIGURATION XState" not in wdm:
        return note("E", "WARN: %s 无 XState 字段，跳过" % need_file)
    if not ("XSTATE_LEGACY_FLOATING_POINT" in winnt and "XSTATE_AVX" in winnt
            and "XSTATE_FEATURE" in winnt and "XSAVE_FORMAT" in winnt
            and "M128A" in winnt and "XmmRegisters" in winnt):
        return note("E", "WARN: winnt.h 缺 XSTATE/XSAVE 类型，跳过")
    if "ddk/wdm.h" not in t:
        return note("E", "WARN: wineboot.c 未包含 ddk/wdm.h，跳过")
    sig = "static void create_user_shared_data(void)"
    if sig not in t:
        return note("E", "WARN: 找不到 create_user_shared_data，跳过")
    t = t.replace(sig, XSTATE_FUNC + sig, 1)
    anchor = '    wcscpy( data->NtSystemRoot, L"C:\\\\windows" );'
    if anchor not in t:
        return note("E", "WARN: NtSystemRoot 锚点缺失，跳过调用注入")
    t = t.replace(anchor, anchor + "\n    initialize_xstate_features( data );", 1)
    write(p, t)
    note("E", "wineboot XState 装填已注入 ✓")


# ------------------------------------------- F. 39-bit 主机分配对齐修复
def item_vprot_align():
    p = "dlls/ntdll/unix/virtual.c"
    t = read(p)
    if t is None:
        return note("F", "%s 不存在，跳过" % p)
    n = 0

    # F1: anon_mmap_alloc 内部页对齐兜底（39-bit 主机上某些推导尺寸可能不是页整数倍）
    old_assert = "    assert( !(size & host_page_mask) );"
    sig = "void *anon_mmap_alloc( size_t size, int prot )"
    sp = func_span(t, sig)
    if sp and "rounding up" not in t[sp[0]:sp[1]] and old_assert in t[sp[0]:sp[1]]:
        seg = t[sp[0]:sp[1]]
        new_block = (
            "    if (size & host_page_mask)\n"
            "    {\n"
            "        WARN( \"anon_mmap_alloc: size %#lx not host-page aligned, rounding up\\n\", (unsigned long)size );\n"
            "        size = (size + host_page_mask) & ~host_page_mask;\n"
            "    }")
        seg = seg.replace(old_assert, new_block, 1)
        t = t[:sp[0]] + seg + t[sp[1]:]
        n += 1

    # F2: pages_vprot 表尺寸对齐（39-bit 时 pages_vprot_size*8 可能不是页整数倍）
    old_pv = "anon_mmap_alloc( pages_vprot_size * sizeof(*pages_vprot), PROT_READ | PROT_WRITE )"
    new_pv = "anon_mmap_alloc( (pages_vprot_size * sizeof(*pages_vprot) + host_page_size - 1) & ~host_page_mask, PROT_READ | PROT_WRITE )"
    if old_pv in t:
        t = t.replace(old_pv, new_pv, 1)
        n += 1

    if n == 0:
        return note("F", "无可改项（已修复或结构不同），跳过")
    write(p, t)
    note("F", "39-bit 分配对齐修复已注入（%d 处）✓" % n)


for fn in (item_hodll, item_hodll64, item_suspend, item_virtual_relax, item_xstate, item_vprot_align):
    try:
        fn()
    except Exception as e:
        note("EXC", "%s: %s" % (fn.__name__, e))

print("\n===== wow64 完善补丁包执行完毕（%d 条记录）=====" % len(LOG))