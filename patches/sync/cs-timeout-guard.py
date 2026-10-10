#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cs-timeout-guard: ntdll 临界区超时"现场转储 + 限时处置" + 堆锁自旋优化

用法: python3 cs-timeout-guard.py <wine源码树目录> [--dry]

效果:
  P1 首次超时转储等待者调用栈 (RtlCaptureStackBackTrace);
  P2 超阈值(默认300s)后按 WINE_CS_TIMEOUT_ACTION=log|raise|abort 处置;
  P3 主进程堆锁自旋数 0 -> 0xfa0 (4000)。
"""
import sys, os, re

DRY = '--dry' in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith('--')]
root = args[0] if args else os.getcwd()
sync_p = os.path.join(root, 'dlls/ntdll/sync.c')
heap_p = os.path.join(root, 'dlls/ntdll/heap.c')

def read(p):
    return open(p, encoding='utf-8', errors='ignore').read()

def write(p, t):
    if not DRY:
        open(p, 'w', encoding='utf-8').write(t)

report = []
ok = True

# ---------------- 1. sync.c ----------------
t = read(sync_p)

HELPERS = '''/* cs-timeout-guard: 临界区超时处置（WINE_CS_TIMEOUT_ACTION=log|raise|abort, WINE_CS_TIMEOUT_SECS=300） */
static BOOL cs_guard_get_env( const WCHAR *name, WCHAR *buf, ULONG buflen )
{
    UNICODE_STRING nameW, valW;

    RtlInitUnicodeString( &nameW, name );
    valW.Buffer        = buf;
    valW.Length        = 0;
    valW.MaximumLength = (buflen - 1) * sizeof(WCHAR);
    buf[0] = 0;
    if (RtlQueryEnvironmentVariable_U( NULL, &nameW, &valW )) return FALSE;
    buf[valW.Length / sizeof(WCHAR)] = 0;
    return TRUE;
}

static ULONG cs_guard_get_env_ulong( const WCHAR *name, ULONG def )
{
    WCHAR buf[32];
    ULONG i, v = 0;

    if (!cs_guard_get_env( name, buf, (ULONG)ARRAY_SIZE(buf) ) || !buf[0]) return def;
    for (i = 0; buf[i] >= '0' && buf[i] <= '9'; i++) v = v * 10 + (buf[i] - '0');
    return i ? v : def;
}

'''

if 'cs-timeout-guard' in t:
    report.append('sync.c: 已是补丁态，跳过注入')
else:
    a1 = re.search(r'/\*+\n \* +RtlpWaitForCriticalSection +\(NTDLL\.@\)\n \*/\n', t)
    assert a1, 'sync.c: 未找到 RtlpWaitForCriticalSection 注释锚点'
    t = t[:a1.start()] + HELPERS + t[a1.start():]

    a2 = re.search(r'( *)unsigned int timeout = ?5;\n', t)
    assert a2, 'sync.c: 未找到 timeout=5 行'
    ins = a2.group(0) + '    ULONG waited_secs = 0;\n    BOOL guard_dumped = FALSE;\n'
    t = t[:a2.start()] + ins + t[a2.end():]

    a3 = re.search(
        r'( *)timeout = \(TRACE_ON\(relay\) \?[ \t]*300[ \t]*:[ \t]*60\);\n(?:[ \t]*\n)?'
        r'[ \t]*ERR\( "section %p %s wait timed out in thread %04lx, blocked by %04lx, retrying \(%u sec\)\\n",\n'
        r'[ \t]*crit, debugstr_a\(crit_section_get_name\(crit\)\), GetCurrentThreadId\(\), HandleToULong\(crit->OwningThread\), timeout \);\n',
        t)
    assert a3, 'sync.c: 未找到超时 ERR 块'
    ind = a3.group(1)
    GUARD = f'''{ind}/* cs-timeout-guard: 首次超时转储等待者栈；超阈值后按 env 处置 */
{ind}{{
{ind}    static ULONG guard_limit;
{ind}    static char guard_action;
{ind}    static BOOL guard_env_done;

{ind}    if (!guard_env_done)
{ind}    {{
{ind}        guard_limit = cs_guard_get_env_ulong( L"WINE_CS_TIMEOUT_SECS", 300 );
{ind}        if (guard_limit < 10) guard_limit = 10;
{ind}        {{
{ind}            WCHAR cs_act[16];

{ind}            if (cs_guard_get_env( L"WINE_CS_TIMEOUT_ACTION", cs_act, (ULONG)ARRAY_SIZE(cs_act) ) && cs_act[0])
{ind}                guard_action = (char)(cs_act[0] | 0x20);
{ind}        }}
{ind}        guard_env_done = TRUE;
{ind}    }}
{ind}    if (!guard_dumped)
{ind}    {{
{ind}        void *cs_frames[24];
{ind}        USHORT i, n = RtlCaptureStackBackTrace( 0, (ULONG)ARRAY_SIZE(cs_frames), cs_frames, NULL );

{ind}        ERR( "cs-guard: waiter stack (%u frames), owner=%04lx recursion=%ld\\n",
{ind}             n, HandleToULong(crit->OwningThread), crit->RecursionCount );
{ind}        for (i = 0; i < n; i++) ERR( "cs-guard: #%02u %p\\n", i, cs_frames[i] );
{ind}        guard_dumped = TRUE;
{ind}    }}
{ind}    waited_secs += timeout;
{ind}    if (waited_secs >= guard_limit)
{ind}    {{
{ind}        if (guard_action == 'r')
{ind}        {{
{ind}            ERR( "cs-guard: action=raise STATUS_POSSIBLE_DEADLOCK cs=%p\\n", crit );
{ind}            return STATUS_POSSIBLE_DEADLOCK;
{ind}        }}
{ind}        if (guard_action == 'a')
{ind}        {{
{ind}            ERR( "cs-guard: action=abort cs=%p blocked by %04lx, terminating\\n",
{ind}                 crit, HandleToULong(crit->OwningThread) );
{ind}            NtTerminateProcess( NtCurrentProcess(), STATUS_POSSIBLE_DEADLOCK );
{ind}        }}
{ind}        ERR( "cs-guard: threshold reached (cs=%p), action=log\\n", crit );
{ind}    }}
{ind}}}
'''
    t = t[:a3.end()] + GUARD + t[a3.end():]
    write(sync_p, t)
    report.append('sync.c: guard 已注入（helpers + 局部变量 + 超时块）')

chk = all(s in t for s in ['cs_guard_get_env', 'cs_guard_get_env_ulong', 'waited_secs',
                            'guard_dumped', 'WINE_CS_TIMEOUT_ACTION', 'RtlCaptureStackBackTrace',
                            'STATUS_POSSIBLE_DEADLOCK', 'NtTerminateProcess'])
report.append('sync self-check: ' + ('OK' if chk else 'FAIL'))
ok = ok and chk

# ---------------- 2. heap.c ----------------
h = read(heap_p)
chk_h = False
if '0xfa0' in h and 'heap->cs.SpinCount' in h:
    report.append('heap.c: 已是补丁态，跳过')
    chk_h = True
else:
    h2, n1 = re.subn(r'(heap->cs\.SpinCount[ \t]*=[ \t]*)0;', r'\g<1>0xfa0;', h)
    h2, n2 = re.subn(r'RtlInitializeCriticalSectionEx\( &heap->cs,[ \t]*0,[ \t]*RTL_CRITICAL_SECTION_FLAG_FORCE_DEBUG_INFO \)',
                     'RtlInitializeCriticalSectionEx( &heap->cs,0xfa0, RTL_CRITICAL_SECTION_FLAG_FORCE_DEBUG_INFO )', h2)
    report.append('heap.c: SpinCount 命中 %d 处, init 命中 %d 处' % (n1, n2))
    chk_h = (n1 == 1 and n2 == 1)
    if chk_h:
        write(heap_p, h2)

# ---------------- 3. 汇总 ----------------
print('\n'.join(report))
print('cs-guard self-check: sync=%s heap=%s dry=%s' % (
    'OK' if chk else 'FAIL', 'OK' if chk_h else 'FAIL', 'YES' if DRY else 'NO'))
sys.exit(0 if ok else 2)
