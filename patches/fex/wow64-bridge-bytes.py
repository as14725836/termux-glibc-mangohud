#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Align the wine <-> libwow64fex WOW64 bridge interface.

Symptom
-------
wine's 32-bit ntdll may execute its own inline `int 0x2e` syscall stub instead
of jumping to the 2-byte bop page handed out by libwow64fex through
BTCpuGetBopCode(). FEX recognises the bridge by *address equality* only:

    if (Frame->State.rip == (uint64_t)BridgeInstrs::Syscall) { ... }

so an inline stub is never intercepted -> #UD again and again at the same EIP
(the classic "eip never advances / c000001d forever" log).

What this does
--------------
Adds a byte-based recognition path for the same opcode the pair uses:
    CD 2E          (int 0x2e)
    2E CD 2E CD    (cs int 0x2e ; exactly what BridgeInstrs holds)
Default ON; set FEX_WOW64_BRIDGE_BYTES=0 to restore stock behaviour.

Idempotent, applied to Source/Windows/WOW64/Module.cpp.
"""
import io
import os
import sys

HELPERS = r'''
// [termux-align] ------------------------------------------------------------
// wine 的 32 位 ntdll 可能执行自己内联的 `int 0x2e` 系统调用桩，而不是跳到
// BTCpuGetBopCode() 给出的 bop 页；而本文件原先只按“地址相等”识别桥指令，
// 于是这类系统调用永远不会被接管 -> 同一个 EIP 上反复 #UD（c000001d）。
// 这里补一条“按指令字节”的识别路径，和 libwow64fex 自己写的那对字节一致。
// 默认开启；FEX_WOW64_BRIDGE_BYTES=0 可关掉，回到原行为。
static bool TermuxBridgeBytesEnabled() {
  static const bool Enabled = []() {
    for (char** E = _environ; E && *E; ++E) {
      const char* P = *E;
      const char Key[] = "FEX_WOW64_BRIDGE_BYTES=";
      size_t I = 0;
      while (Key[I] && P[I] == Key[I]) {
        ++I;
      }
      if (!Key[I]) {
        return P[I] != '\0' && P[I] != '0';
      }
    }
    return true; // 默认开启
  }();
  return Enabled;
}

static bool IsLegacySyscallBridge(uint64_t RIP) {
  if (!TermuxBridgeBytesEnabled()) {
    return false;
  }
  const auto P = reinterpret_cast<const uint8_t*>(RIP);
  return (P[0] == 0xCD && P[1] == 0x2E) || (P[0] == 0x2E && P[1] == 0xCD);
}
// ---------------------------------------------------------------------------
'''

OLD_CLASS = "class WowSyscallHandler : public FEXCore::HLE::SyscallHandler"
OLD_SYS = "} else if (Frame->State.rip == (uint64_t)BridgeInstrs::Syscall) {"
NEW_SYS = ("} else if (Frame->State.rip == (uint64_t)BridgeInstrs::Syscall ||\n"
           "               IsLegacySyscallBridge(Frame->State.rip)) {")
OLD_WB = ("    if (Frame->State.rip == (uint64_t)BridgeInstrs::Syscall || "
          "Frame->State.rip == (uint64_t)BridgeInstrs::UnixCall) {")
NEW_WB = ("    const bool Bridged = Frame->State.rip == (uint64_t)BridgeInstrs::Syscall ||\n"
          "                         Frame->State.rip == (uint64_t)BridgeInstrs::UnixCall ||\n"
          "                         IsLegacySyscallBridge(Frame->State.rip);\n"
          "    if (Bridged) {")


def main(root):
    f = os.path.join(root, "Source/Windows/WOW64/Module.cpp")
    if not os.path.exists(f):
        print("SKIP: %s 不存在（FEX 树里没有 WOW64 模块）" % f)
        return 0
    src = io.open(f, encoding="utf-8", errors="replace").read()
    if "IsLegacySyscallBridge" in src:
        print("OK(already): 对齐补丁已在位")
        return 0

    n = 0
    if OLD_CLASS in src:
        src = src.replace(OLD_CLASS, HELPERS.lstrip("\n") + "\n" + OLD_CLASS, 1)
        n += 1
    if OLD_SYS in src:
        src = src.replace(OLD_SYS, NEW_SYS, 1)
        n += 1
    if OLD_WB in src:
        src = src.replace(OLD_WB, NEW_WB, 1)
        n += 1

    if n != 3:
        print("FAIL: 只命中 %d/3 处，源码与预期不符，未改动" % n)
        return 1

    io.open(f, "w", encoding="utf-8").write(src)
    chk = io.open(f, encoding="utf-8").read()
    for token in ("IsLegacySyscallBridge(Frame->State.rip)", "const bool Bridged",
                  "FEX_WOW64_BRIDGE_BYTES", "_environ"):
        if token not in chk:
            print("FAIL: 自检缺 %s" % token)
            return 1
    print("OK: wow64 桥指令按字节识别已注入（默认开启，FEX_WOW64_BRIDGE_BYTES=0 关闭）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))