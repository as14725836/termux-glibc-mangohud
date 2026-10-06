#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自己往 stats 文件里写 64 字节 header（Version=2 + 版本串），让 MangoHud 能显示 FEX 版本。

背景（源码实证，FEX-2608 = e869aa644）：
  Source/Windows/Common/SHMStats.cpp
      StatAlloc::StatAlloc(AppType) {
        auto Result = UnixLib::AllocateSHMSlots(Base, FEX_PAGE_SIZE, MAX_STATS_SIZE);
        if (Result.SHMBase) { Base = Result.SHMBase; SaveHeader(AppType); }
      }
  -> 只有 AllocateSHMSlots 返回非空映射，header 才会被写。
  而 legacy 路径（Source/Windows/Common/FEXUnixLib.cpp 的 Opaque handle path）在 Wine 下
  NtCreateSection / NtMapViewOfSection 常常失败 -> 返回 {} -> SaveHeader 被跳过
  -> 文件已被上一个补丁撑到 MAX_STATS_SIZE(1 MiB)，但内容全 0
  -> MangoHud 打 "version mismatch (header=0)"，版本号显示不出来。

做法：在文件已经被撑到 MaxSize 之后，紧接着把 64 字节 header 直接写进文件开头：
      [0]    = 2      Version（对应 FEXCore::SHMStats::STATS_VERSION）
      [1]    = app_type（arm64ec=2 / wow64=3）
      [2..3] = 0      ThreadStatsSize（0 表示让读取方用自己的尺寸）
      [4..51]= 版本字符串（"FEX-2608" 之类）
  这样即使 section 映射失败，磁盘上的文件也已经是合法 stats 文件。
  若映射成功，FEX 自己的 SaveHeader 会随后覆盖成权威数值，两者不冲突。

幂等：已打过跳过；锚点（上一个补丁写入的 NtWriteFile 那一行）不在 -> 明确跳过。
"""
import os
import subprocess
import sys

MARK = "FEXStatsHeaderFallback"
REL = "Source/Windows/Common/FEXUnixLib.cpp"
ANCHOR = ("    NtWriteFile(handle, nullptr, nullptr, nullptr, &FEXStatsIOSB, "
          "&FEXStatsZero, 1, &FEXStatsEnd, nullptr);\n")


def guess_version(src):
    """尽量拿到真实版本串，拿不到就退化为 FEX。"""
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
    for rel in ("VERSION", "version.txt"):
        p = os.path.join(src, rel)
        if os.path.isfile(p):
            try:
                v = open(p, encoding="utf-8", errors="ignore").read().strip().splitlines()[0]
                if v:
                    return v
            except Exception:
                pass
    return "FEX"


SNIPPET = '''  // ---- [Termux patch] %s：自己写 64 字节 header ----
  // 上面已把文件撑到 MaxSize；Wine 下 NtCreateSection 可能失败，SaveHeader 就永远不会跑，
  // 于是文件 1 MiB 但内容全 0（MangoHud 报 version mismatch header=0）。
  // 这里直接按 FEXCore::SHMStats::ThreadStatsHeader 的布局手写一份 header。
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

''' % (MARK, "%s")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1].rstrip('/')
    path = os.path.join(src, REL)
    if not os.path.isfile(path):
        raise SystemExit("ERROR: 找不到 %s" % path)

    text = open(path, encoding='utf-8', errors='surrogateescape').read()
    if MARK in text:
        print("跳过（已打过补丁）: %s" % REL)
        return
    if ANCHOR not in text:
        print("跳过（没有 legacy 撑大小补丁留下的锚点，说明该版本无需此补丁）: %s" % REL)
        return

    ver = guess_version(src)
    print("header 版本串采用: %r" % ver)
    text = text.replace(ANCHOR, ANCHOR + (SNIPPET % ver), 1)

    if "NtWriteFile" not in text or "FEXStatsHeader" not in text:
        raise SystemExit("ERROR: 替换结果异常")
    open(path, 'w', encoding='utf-8', errors='surrogateescape').write(text)
    print("已改写: %s（写 64 字节 header，版本串 %s）" % (REL, ver))


if __name__ == '__main__':
    main()