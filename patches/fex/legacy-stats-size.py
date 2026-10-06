#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让 FEX 的 stats 文件真的有大小（否则 MangoHud 读到 0 字节“空文件”）。

背景（源码实证）：
  FEX-2608 那代 Source/Windows/Common/FEXUnixLib.cpp 的 AllocateSHMSlots 有个 legacy 路径：
      auto handle = CreateFileA("/dev/shm/fex-<pid>-stats", ..., CREATE_ALWAYS, ...);   // 建出 0 字节
      NtCreateSection(&Section, SECTION_EXTEND_SIZE|..., &SectionSize /*MaxSize*/, ..., handle);
  Wine 下 CreateFileA 建的文件永远是 0 字节，NtCreateSection 只在内存里映射，
  不改文件大小 -> 数据写在映射里，文件仍是 0 字节 -> MangoHud 读到空文件。
  （main 上这条路径已被上游删掉，只剩 UnixLib 路径，所以本补丁在新版上是“跳过”。）

做法：建完文件、创建 section 之前，用 NtWriteFile 在 MaxSize-1 处写 1 字节，
      把文件撑到 MaxSize。NtWriteFile / IO_STATUS_BLOCK / LARGE_INTEGER 都在该文件
      已有的 include（winternl.h）里声明，不需要引入新的头文件。

幂等：已打过跳过；该版本没有 legacy 路径 -> 明确提示并跳过（不算失败）；锚点在但替换不完整 -> 报错。
"""
import os
import sys

MARK = "FEXStatsFileSize"
REL = "Source/Windows/Common/FEXUnixLib.cpp"
LEGACY_HINT = "Opaque handle path"

SNIPPET = '''  // ---- [Termux patch] %s：让 stats 文件真的有大小 ----
  // Wine 下 CreateFileA() 建出来的是 0 字节文件，随后的 NtCreateSection 只在内存里映射，
  // 文件大小永远是 0，MangoHud 之类工具读到的就是“空文件”。
  // 这里先在 MaxSize-1 处写 1 字节，把文件撑到 MaxSize，映射里的数据才能被读到。
  if (handle != INVALID_HANDLE_VALUE) {
    LARGE_INTEGER FEXStatsEnd;
    FEXStatsEnd.QuadPart = static_cast<LONGLONG>(MaxSize) - 1;
    IO_STATUS_BLOCK FEXStatsIOSB {};
    char FEXStatsZero {};
    NtWriteFile(handle, nullptr, nullptr, nullptr, &FEXStatsIOSB, &FEXStatsZero, 1, &FEXStatsEnd, nullptr);
  }

''' % MARK


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = os.path.join(sys.argv[1].rstrip('/'), REL)
    if not os.path.isfile(path):
        raise SystemExit("ERROR: 找不到 %s" % path)
    text = open(path, encoding='utf-8', errors='surrogateescape').read()
    if MARK in text:
        print("跳过（已打过补丁）: %s" % REL)
        return
    if LEGACY_HINT not in text:
        print("跳过（该版本没有 legacy CreateFileA/NtCreateSection 路径，无需此补丁）: %s" % REL)
        return

    anchor = "  // Create the section mapping for the file handle for the full size.\n"
    if text.count(anchor) != 1:
        raise SystemExit("ERROR: %s 里锚点（Create the section mapping ...）匹配 %d 次" % (REL, text.count(anchor)))
    if "NtWriteFile" not in text:
        pass  # 声明来自 winternl.h，无需在 cpp 里出现
    text = text.replace(anchor, SNIPPET + anchor, 1)
    if "CreateFileA(" not in text:
        raise SystemExit("ERROR: 替换后 CreateFileA 不见了？")
    open(path, 'w', encoding='utf-8', errors='surrogateescape').write(text)
    print("已改写: %s（legacy 路径：建文件后补 MaxSize 大小）" % REL)


if __name__ == '__main__':
    main()