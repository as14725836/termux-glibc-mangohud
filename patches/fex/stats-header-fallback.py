#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让 FEX 的两条 stats 路径都自己写出 64 字节 header（Version=2 + 版本串）。

背景（源码实证，FEX-2608 = e869aa644）：
  Source/Windows/Common/SHMStats.cpp
      StatAlloc::StatAlloc(AppType) {
        auto Result = UnixLib::AllocateSHMSlots(Base, FEX_PAGE_SIZE, MAX_STATS_SIZE);
        if (Result.SHMBase) { Base = Result.SHMBase; SaveHeader(AppType); }   // ← 写 header
      }
  => 只要 AllocateSHMSlots 没返回映射，SaveHeader 就不会跑，文件就是全 0。
     MangoHud 读首字节 != 2 -> "version mismatch (header=0)" -> 版本号显示不出来。

AllocateSHMSlots 有两条路，两边都可能失败，所以两边都兜底：

  (A) UnixLib 路径（Source/Windows/UnixLib/FEXUnixLib.cpp）
      open -> ftruncate(MapSize) -> mmap(MAP_SHARED|MAP_FIXED)
      我们在这里【直接用 fd pwrite 写 header】—— 不依赖后面的 mmap 成功与否。

  (B) Legacy 路径（Source/Windows/Common/FEXUnixLib.cpp）
      CreateFileA("/dev/shm/fex-<pid>-stats") -> NtCreateSection -> NtMapViewOfSection
      Wine 下 NtCreateSection 常失败。这里在“撑大小”之后【用 NtWriteFile 写 header】。

两条路都写同一份布局：
      [0]    = 2      Version（FEXCore::SHMStats::STATS_VERSION）
      [1]    = 2/3    AppType（arm64ec / wow64）
      [2..3] = 0      ThreadStatsSize（0 = 读取方用自己的尺寸）
      [4..51]= 版本串
若之后 FEX 自己的 SaveHeader 跑到了，会覆盖成权威数值，两者不冲突。

幂等：已打过跳过；找不到锚点 -> 明确跳过（不算失败）。
"""
import os
import subprocess
import sys

MARK = "FEXStatsHeaderFallback"
REL_UNIX = "Source/Windows/UnixLib/FEXUnixLib.cpp"
REL_LEGACY = "Source/Windows/Common/FEXUnixLib.cpp"

ANCHOR_UNIX = "  // Reserve a region of MAX_STATS_SIZE so we can grow the allocation buffer.\n"

SNIPPET_UNIX = '''  // ---- [Termux patch] %s：直接经 fd 写 64 字节 header（不依赖后面的 mmap）----
  // 若 mmap 失败，FEX 的 SaveHeader 永远不会跑；这里先把 header 落到磁盘上，
  // 让 MangoHud 至少能读出 FEX 版本，而不是报 version mismatch (header=0)。
  {
    char FEXStatsUHeader[64] {};
    FEXStatsUHeader[0] = 2;      // Version = STATS_VERSION
#ifdef ARCHITECTURE_arm64ec
    FEXStatsUHeader[1] = 2;      // AppType::WIN_ARM64EC
#else
    FEXStatsUHeader[1] = 3;      // AppType::WIN_WOW64
#endif
    const char FEXStatsUVersionString[] = "%s";
    for (size_t i = 0; i < sizeof(FEXStatsUVersionString) - 1 && i < 48; ++i) {
      FEXStatsUHeader[4 + i] = FEXStatsUVersionString[i];
    }
    ssize_t FEXStatsUWritten = pwrite(fd, FEXStatsUHeader, sizeof(FEXStatsUHeader), 0);
    (void)FEXStatsUWritten;   // best effort：失败也不影响原有流程
  }

'''

ANCHOR_LEGACY = ("    NtWriteFile(handle, nullptr, nullptr, nullptr, &FEXStatsIOSB, "
                 "&FEXStatsZero, 1, &FEXStatsEnd, nullptr);\n")

SNIPPET_LEGACY = '''  // ---- [Termux patch] %s：用 NtWriteFile 写 64 字节 header ----
  // 上面已把文件撑到 MaxSize；Wine 下 NtCreateSection 可能失败，SaveHeader 就不会跑，
  // 于是文件 1 MiB 但内容全 0。这里直接按 FEXCore::SHMStats::ThreadStatsHeader 布局手写。
  if (handle != INVALID_HANDLE_VALUE) {
    char FEXStatsHeader[64] {};
    FEXStatsHeader[0] = 2;      // Version = STATS_VERSION
#ifdef ARCHITECTURE_arm64ec
    FEXStatsHeader[1] = 2;      // AppType::WIN_ARM64EC
#else
    FEXStatsHeader[1] = 3;      // AppType::WIN_WOW64
#endif
    // [2..3] ThreadStatsSize = 0 -> 读取方使用自己的尺寸
    const char FEXStatsVersionString[] = "%s";
    for (size_t i = 0; i < sizeof(FEXStatsVersionString) - 1 && i < 48; ++i) {
      FEXStatsHeader[4 + i] = FEXStatsVersionString[i];
    }
    LARGE_INTEGER FEXStatsHeaderOffset {};
    IO_STATUS_BLOCK FEXStatsHeaderIOSB {};
    NtWriteFile(handle, nullptr, nullptr, nullptr, &FEXStatsHeaderIOSB, FEXStatsHeader,
                sizeof(FEXStatsHeader), &FEXStatsHeaderOffset, nullptr);
  }

'''


def guess_version(src):
    for env in ("FEX_VERSION_STRING", "FEX_DESCRIBE", "FEX_TAG"):
        v = os.environ.get(env, "").strip()
        if v:
            return v
    try:
        out = subprocess.run(["git", "-C", src, "describe", "--tags"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        if out:
            return out
    except Exception:
        pass
    return "FEX"


def patch(path, anchor, snippet, ver, label, require_marker=None):
    if not os.path.isfile(path):
        print("跳过（文件不存在）: %s" % label)
        return False
    text = open(path, encoding='utf-8', errors='surrogateescape').read()
    if MARK in text:
        print("跳过（已打过补丁）: %s" % label)
        return False
    if anchor not in text:
        print("跳过（锚点不在，该版本/该路径无需此补丁）: %s" % label)
        return False
    if require_marker and require_marker not in text:
        print("跳过（缺少前置补丁 %s）: %s" % (require_marker, label))
        return False
    text = text.replace(anchor, (snippet % (MARK, ver)) + anchor, 1)
    open(path, 'w', encoding='utf-8', errors='surrogateescape').write(text)
    print("已改写: %s（写 64 字节 header，版本串 %s）" % (label, ver))
    return True


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1].rstrip('/')
    ver = guess_version(src)
    print("header 版本串采用: %r" % ver)

    n = 0
    if patch(os.path.join(src, REL_UNIX), ANCHOR_UNIX, SNIPPET_UNIX, ver, REL_UNIX):
        n += 1
    if patch(os.path.join(src, REL_LEGACY), ANCHOR_LEGACY, SNIPPET_LEGACY, ver, REL_LEGACY,
             require_marker="FEXStatsIOSB"):
        n += 1

    if n == 0:
        print("两条路径都没改（可能已打过，或该版本结构不同）")
    else:
        print("共改写 %d 个文件" % n)


if __name__ == '__main__':
    main()