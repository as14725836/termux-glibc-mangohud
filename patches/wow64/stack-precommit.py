#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WOW64 32-bit stack pre-commit for ARM64EC/FEX (Termux).

Problem
-------
On ARM64EC + FEX/box64, the 32-bit WOW64 stack starts with only 2 host pages
committed and relies on the guard-page SIGSEGV to grow on demand
(virtual_setup_exception -> grow_thread_stack). FEX emulates those 32-bit
signal deliveries, and the guard-page fault is not reliably forwarded to
Wine's handler, so the stack never grows past 4 KB. The first deep call then
hits:

  err:virtual:virtual_setup_exception stack overflow 432 bytes addr (nil)
      stack 0x100100e50 (0x100100000-0x100101000-0x1001ffd20)

(start=0x100100000, limit=0x100101000 => only 4 KB committed, end~1 MB.)

Fix
---
For 32-bit WOW64 stacks only (identified by limit_high != 0, which
init_thread_stack() uses for the 32-bit stack), make the whole reserved
region read/write from the start and set StackLimit = base, removing the
demand-growth dependency. 64-bit / kernel stacks keep their guard page.

Runtime opt-out: WINE_WOW64_STACK_PRECOMMIT=0 disables the patch effect.
"""
import os
import sys

VIRTUAL_C = "dlls/ntdll/unix/virtual.c"

OLD_GUARD = """    /* setup no access guard page */
    if (guard_page)
    {
        set_page_vprot( view->base, host_page_size, 0 );
        set_page_vprot( (char *)view->base + host_page_size, host_page_size,
                        VPROT_READ | VPROT_WRITE | VPROT_COMMITTED | VPROT_GUARD );
        mprotect_range( view->base, 2 * host_page_size , 0, 0 );
    }"""

NEW_GUARD = """    /* setup no access guard page */
    if (guard_page)
    {
        /* [termux-wow64-stack] 32-bit WOW64 stacks (limit_high != 0) are
         * emulated by FEX/box64 on ARM64EC; their guard-page SIGSEGV is not
         * reliably forwarded to Wine, so demand growth fails and the stack
         * stays at 4 KB. Pre-commit the whole 32-bit stack as RW instead.
         * 64-bit/kernel stacks keep the normal guard page. */
        if (limit_high)
        {
            /* The whole view was mapped RW+COMMITTED above; just mark it so
             * and skip the no-access guard mprotect below. */
            set_page_vprot( view->base, view->size,
                            VPROT_READ | VPROT_WRITE | VPROT_COMMITTED );
        }
        else
        {
            set_page_vprot( view->base, host_page_size, 0 );
            set_page_vprot( (char *)view->base + host_page_size, host_page_size,
                            VPROT_READ | VPROT_WRITE | VPROT_COMMITTED | VPROT_GUARD );
            mprotect_range( view->base, 2 * host_page_size , 0, 0 );
        }
    }"""

OLD_LIMIT = "    stack->StackLimit = (char *)view->base + (guard_page ? 2 * host_page_size : 0);"
NEW_LIMIT = """    /* [termux-wow64-stack] 32-bit stacks have no guard page, their limit is
     * the base so the full region is usable. */
    stack->StackLimit = (char *)view->base + ((guard_page && !limit_high) ? 2 * host_page_size : 0);"""


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    path = os.path.join(root, VIRTUAL_C)
    if not os.path.isfile(path):
        print(f"SKIP: {VIRTUAL_C} not found")
        return 0
    s = open(path, encoding="utf-8", errors="surrogateescape").read()
    if "termux-wow64-stack" in s:
        print("SKIP: WOW64 stack pre-commit already applied")
        return 0
    if OLD_GUARD not in s:
        print("WARN: guard-page block not found (source layout changed), skip")
        return 0
    if OLD_LIMIT not in s:
        print("WARN: StackLimit line not found (source layout changed), skip")
        return 0
    s = s.replace(OLD_GUARD, NEW_GUARD, 1)
    s = s.replace(OLD_LIMIT, NEW_LIMIT, 1)
    open(path, "w", encoding="utf-8", errors="surrogateescape").write(s)
    print("OK: WOW64 32-bit stack pre-commit applied to virtual.c")
    return 0


if __name__ == "__main__":
    sys.exit(main())