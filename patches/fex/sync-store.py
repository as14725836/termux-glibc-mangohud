#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 DiskCache::Store 从「丢给 WorkQueueThread 异步写」改回「调用线程同步写」。

背景（实测二分结论）：
  FEX-2608-58-g561c32b （能跑 32 位）… e3f208f61《DiskCache: offload Store to a WorkQueueThread》起 32 位崩
  （崩线程名就是 FEX:DiskCache，guest i386 / WOW64）

只做两件事：1) 不再创建 Writer 线程；2) Store() 里 work item 就地 Run()（同步写）。
幂等：已打过跳过；该版本还没有 WorkQueueThread（如 FEX-2608）-> 提示并跳过；锚点数不对 -> 报错。
"""
import os
import re
import sys

MARK = "FEXSyncStore"
REL = "FEXCore/Source/Interface/Core/DiskCache.cpp"
QUEUE_RE = re.compile(r'Writer->QueueWork\(\s*fextl::make_unique<CacheStoreWorkItem>\((.*?)\)\s*\)\s*;', re.S)
WRITER_RE = re.compile(r'Writer = fextl::make_unique<WorkQueueThread>\([^;]*\)\s*;')


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = os.path.join(sys.argv[1].rstrip('/'), REL)
    if not os.path.isfile(path):
        print("跳过（该版本还没有 DiskCache.cpp，即 Disk Cache 特性尚未引入，无需此补丁）: %s" % REL)
        return
    text = open(path, encoding='utf-8', errors='surrogateescape').read()
    if MARK in text:
        print("跳过（已打过补丁）: %s" % REL)
        return
    if 'WorkQueueThread' not in text:
        print("跳过（该版本还没有 DiskCache offload / WorkQueueThread，无需此补丁）: %s" % REL)
        return

    q = QUEUE_RE.findall(text)
    w = WRITER_RE.findall(text)
    if len(q) != 1:
        raise SystemExit("ERROR: %s 里 Writer->QueueWork(make_unique<CacheStoreWorkItem>(...)) 匹配 %d 次（应为 1）" % (REL, len(q)))
    if len(w) != 1:
        raise SystemExit("ERROR: %s 里 Writer 创建语句匹配 %d 次（应为 1）" % (REL, len(w)))

    text = QUEUE_RE.sub(
        lambda m: ('{ // [Termux patch] %s：不在 Writer 线程上写，改回同步（32 位/WOW64 下 WorkQueueThread 会崩）\n'
                   '      auto FEXSyncStore = fextl::make_unique<CacheStoreWorkItem>(%s);\n'
                   '      FEXSyncStore->Run();\n'
                   '    }' % (MARK, m.group(1))), text, count=1)
    text = WRITER_RE.sub('Writer.reset(); // [Termux patch] %s：不创建 Writer 线程（32 位/WOW64 下会崩）' % MARK, text, count=1)

    open(path, 'w', encoding='utf-8', errors='surrogateescape').write(text)
    print("已改写: %s" % REL)
    print("  · Writer->QueueWork(...) -> 就地 .Run()（同步写）")
    print("  · Writer 线程不再创建")


if __name__ == '__main__':
    main()