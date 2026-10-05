#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 FEX 运行时生成的 stats 文件从 /dev/shm 重定向到真实目录。

默认目标：/data/data/com.termux/files/usr/tmp  （Termux；运行期可用 FEX_STATS_DIR 覆盖）

为什么必须改源码：
  glibc/musl 的 shm_open() 只接受 "/name" 形式（名字里不允许再出现 '/'），
  也就是说没法把 POSIX shm 指到任意目录；而 Termux/Android 上 /dev/shm 常常
  根本不存在 → shm_open() 返回 -1 → FEX 直接放弃 stats（静默失败）。
  改成普通文件 + open()/unlink() 即可，后面 ftruncate() + mmap(MAP_SHARED)
  的语义与 POSIX shm 完全一致。

涉及的两个源码文件：
  1) Source/Windows/UnixLib/FEXUnixLib.cpp                        （WOW64 / Wine 侧）
  2) Source/Tools/LinuxEmulation/LinuxSyscalls/ThreadManager.cpp   （Linux 宿主侧）

结构感知 + 幂等：已打过就跳过；匹配数不符即报错退出（不静默放过）。
用法: termux-shm-dir.py <fex-src-root> [目标目录]
"""
import os
import sys

MARK = "FEXStatsFilePath"
DEFAULT_DIR = "/data/data/com.termux/files/usr/tmp"

HELPER = '''// ---- [Termux patch] FEX stats 文件重定向到真实目录（不再是 /dev/shm）----
// Termux/Android 上 /dev/shm 往往不存在，而且 shm_open 只接受 "/name" 形式，
// 所以这里改用普通文件 + open()/unlink()；随后的 ftruncate + mmap(MAP_SHARED)
// 语义与 POSIX shm 一致，功能不变。
// 运行期可用环境变量 FEX_STATS_DIR 覆盖目录。
constexpr static const char* FEX_STATS_DIR_DEFAULT_PATH = "@DIR@";
static inline std::string FEXStatsFilePath(const char* Name) {
  const char* Dir = ::getenv("FEX_STATS_DIR");
  if (!Dir || !*Dir) {
    Dir = FEX_STATS_DIR_DEFAULT_PATH;
  }
  ::mkdir(Dir, 0755); // best effort：已存在 / 无权限都无所谓
  return std::string(Dir) + "/" + Name;
}
// ---- [Termux patch] end ----
'''

# (文件, 插入位置锚点, 插入方式, [(旧, 新, 期望次数)])
SPEC = [
    ("Source/Windows/UnixLib/FEXUnixLib.cpp", "static inline void* InitializeSHM(", "before",
     [("int fd = shm_open(Name.c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);",
       "int fd = ::open(FEXStatsFilePath(Name.c_str()).c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);", 1),
      ("int fd = shm_open(Name.c_str(), O_RDWR, USER_PERMS);",
       "int fd = ::open(FEXStatsFilePath(Name.c_str()).c_str(), O_RDWR, USER_PERMS);", 1),
      ("shm_unlink(Name.c_str());",
       "::unlink(FEXStatsFilePath(Name.c_str()).c_str());", 1)]),
    ("Source/Tools/LinuxEmulation/LinuxSyscalls/ThreadManager.cpp", "namespace FEX::HLE {", "after",
     [('int fd = shm_open(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);',
       'int fd = ::open(FEXStatsFilePath(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str()).c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);', 1),
      ('int fd = shm_open(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str(), O_RDWR, USER_PERMS);',
       'int fd = ::open(FEXStatsFilePath(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str()).c_str(), O_RDWR, USER_PERMS);', 1),
      ('shm_unlink(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str());',
       '::unlink(FEXStatsFilePath(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str()).c_str());', 1)]),
]

NEED_INC = ["#include <cstdlib>", "#include <string>", "#include <sys/stat.h>"]


def add_includes(text):
    """在第一个 '#include <unistd.h>' / '#include <fcntl.h>' 之后补齐需要的头文件。"""
    add = [i for i in NEED_INC if i not in text]
    if not add:
        return text, []
    for anchor in ("#include <unistd.h>", "#include <fcntl.h>", "#include \"FEXUnixLib.h\"",
                   "#include \"LinuxSyscalls/ThreadManager.h\""):
        if anchor in text:
            return text.replace(anchor, anchor + "\n" + "\n".join(add), 1), add
    raise SystemExit("ERROR: 找不到可用的 #include 锚点")

def patch_profile_stats(root):
    """把 FEX 的 ProfileStats 默认值改成 true —— 也就是"默认就生成 fex-<pid>-stats"。
    仍然可以用 FEX_PROFILESTATS=0 / Config.json 关掉。"""
    rel = "FEXCore/Source/Interface/Config/Config.json.in"
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        raise SystemExit("ERROR: 找不到 %s" % path)
    with open(path, encoding="utf-8", errors="surrogateescape") as fp:
        text = fp.read()
    key = '"ProfileStats"'
    if text.count(key) != 1:
        raise SystemExit("ERROR: %s 里 %s 出现 %d 次" % (rel, key, text.count(key)))
    i = text.index(key)
    j = text.find('"Default"', i)
    if j == -1 or j - i > 300:
        raise SystemExit("ERROR: ProfileStats 后面找不到 Default")
    k = text.find('"', j + len('"Default"') + 1)
    e = text.find('"', k + 1)
    cur = text[k + 1:e]
    if cur == "true":
        print("跳过（本来就默认开启）: %s ProfileStats Default=true" % rel)
        return False
    if cur != "false":
        raise SystemExit("ERROR: ProfileStats Default 既不是 false 也不是 true，而是 %r" % cur)
    text = text[:k + 1] + "true" + text[e:]
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as fp:
        fp.write(text)
    print("已改写: %s -> ProfileStats Default=true（默认生成 stats）" % rel)
    return True


def main():

    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = sys.argv[1].rstrip("/")
    target_dir = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("FEX_STATS_DIR") or DEFAULT_DIR)
    helper = HELPER.replace("@DIR@", target_dir)
    total = 0

    for rel, anchor, where, subs in SPEC:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            raise SystemExit("ERROR: 找不到源文件 %s" % path)
        with open(path, encoding="utf-8", errors="surrogateescape") as fp:
            text = fp.read()

        if MARK in text:
            print("跳过（已打过补丁）: %s" % rel)
            continue

        for old, new, n in subs:
            got = text.count(old)
            if got != n:
                raise SystemExit("ERROR: %s 里匹配数 %d != %d -> %s" % (rel, got, n, old[:80]))
            text = text.replace(old, new)

        # 收尾校验（在插入 helper 之前，避免注释里出现同名调用的干扰）
        for bad in ("shm_open(", "shm_unlink("):
            if bad in text:
                raise SystemExit("ERROR: %s 里仍残留 %s" % (rel, bad))

        new_text, added = add_includes(text)
        text = new_text

        if anchor not in text:
            raise SystemExit("ERROR: %s 里找不到插入锚点: %s" % (rel, anchor))
        if where == "before":
            text = text.replace(anchor, helper + anchor, 1)
        else:
            text = text.replace(anchor, anchor + "\n\n" + helper, 1)

        # 收尾校验：不允许再残留 POSIX shm 调用
        for bad in ("shm_open(", "shm_unlink("):
            if bad in text:
                raise SystemExit("ERROR: %s 里仍残留 %s" % (rel, bad))

        with open(path, "w", encoding="utf-8", errors="surrogateescape") as fp:
            fp.write(text)
        total += 1
        print("已改写: %s（补头文件: %s）" % (rel, ", ".join(a.split()[1] for a in added) or "无"))

    # ---- 默认开启 stats（不依赖 FEX_PROFILESTATS 环境变量）----
    ps = patch_profile_stats(root)

    print("FEX stats 目录 = %s；改写文件数 = %d；ProfileStats 默认开启改动 = %s"
          % (target_dir, total, "有" if ps else "无（本来就是 true）"))


if __name__ == "__main__":
    main()
