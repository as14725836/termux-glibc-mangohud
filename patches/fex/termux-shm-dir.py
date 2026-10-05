#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""termux-shm-dir.py v3（FEX stats 文件）：
 · Wine/WOW64 侧 FEXUnixLib.cpp：多目录兜底（FEX_STATS_DIR → Termux tmp → /dev/shm）、
   记住成功的路径、open/ftruncate 失败把 errno 打到 stderr（wine 日志可见）。
 · Linux 宿主侧 ThreadManager.cpp：单目录 + FEXStatsFilePath()，同样带失败日志。
 · ProfileStats 默认 true（默认就生成 fex-<pid>-stats）。
"""
import os
import sys

MARK = "FEXStatsFilePath"
DEFAULT_DIR = "/data/data/com.termux/files/usr/tmp"

BASE = '''// ---- [Termux patch] FEX stats 文件重定向到真实目录（不再是 /dev/shm）----
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
'''

TRUNC_LINUX = '''
static inline bool FEXStatsTruncate(int fd, off_t Size) {
  if (::ftruncate(fd, Size) == 0) {
    return true;
  }
  ::fprintf(stderr, "[FEX-stats] ftruncate(%lld) 失败: %s\\n", (long long)Size, ::strerror(errno));
  return false;
}
'''

WIN_EXTRA = '''
// 多目录兜底：把真正打开成功的路径记下来，后续 AllocateMoreSlots / Delete 复用同一个文件。
static inline std::string& FEXStatsChosenPath() {
  static std::string Path;
  return Path;
}

static inline int FEXStatsOpen(const char* Name, int Flags, int Mode) {
  const char* Env = ::getenv("FEX_STATS_DIR");
  const char* Dirs[3];
  int DirCount = 0;
  if (Env && *Env) {
    Dirs[DirCount++] = Env;
  }
  Dirs[DirCount++] = FEX_STATS_DIR_DEFAULT_PATH;
  Dirs[DirCount++] = "/dev/shm";

  for (int i = 0; i < DirCount; ++i) {
    if (!Dirs[i] || !*Dirs[i]) {
      continue;
    }
    if (Flags & O_CREAT) {
      ::mkdir(Dirs[i], 0755);
    }
    std::string Path = std::string(Dirs[i]) + "/" + Name;
    int fd = ::open(Path.c_str(), Flags, Mode);
    if (fd != -1) {
      FEXStatsChosenPath() = Path;
      return fd;
    }
    ::fprintf(stderr, "[FEX-stats] open(%s) 失败: %s\\n", Path.c_str(), ::strerror(errno));
  }
  return -1;
}

static inline int FEXStatsOpenExisting(const char* Name, int Flags, int Mode) {
  if (!FEXStatsChosenPath().empty()) {
    int fd = ::open(FEXStatsChosenPath().c_str(), Flags, Mode);
    if (fd != -1) {
      return fd;
    }
    ::fprintf(stderr, "[FEX-stats] reopen(%s) 失败: %s\\n", FEXStatsChosenPath().c_str(), ::strerror(errno));
  }
  return FEXStatsOpen(Name, Flags, Mode);
}

static inline void FEXStatsUnlink(const char* Name) {
  if (!FEXStatsChosenPath().empty()) {
    ::unlink(FEXStatsChosenPath().c_str());
    return;
  }
  ::unlink(FEXStatsFilePath(Name).c_str());
  ::unlink((std::string("/dev/shm/") + Name).c_str());
}

static inline bool FEXStatsTruncate(int fd, off_t Size) {
  if (::ftruncate(fd, Size) == 0) {
    return true;
  }
  ::fprintf(stderr, "[FEX-stats] ftruncate(%lld) 失败: %s（文件 %s）\\n", (long long)Size, ::strerror(errno),
            FEXStatsChosenPath().c_str());
  return false;
}
'''

LINUX_SPEC = ("Source/Tools/LinuxEmulation/LinuxSyscalls/ThreadManager.cpp", "namespace FEX::HLE {", "after",
              BASE + TRUNC_LINUX,
              [('int fd = shm_open(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);',
                'int fd = ::open(FEXStatsFilePath(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str()).c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);', 1),
               ('int fd = shm_open(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str(), O_RDWR, USER_PERMS);',
                'int fd = ::open(FEXStatsFilePath(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str()).c_str(), O_RDWR, USER_PERMS);', 1),
               ('shm_unlink(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str());',
                '::unlink(FEXStatsFilePath(fextl::fmt::format("fex-{}-stats", ::getpid()).c_str()).c_str());', 1),
               ("if (ftruncate(fd, CurrentSize) == -1) {", "if (!FEXStatsTruncate(fd, CurrentSize)) {", 1),
               ("if (ftruncate(fd, NewSize) == -1) {", "if (!FEXStatsTruncate(fd, NewSize)) {", 1)])

WIN_SPEC = ("Source/Windows/UnixLib/FEXUnixLib.cpp", "static inline void* InitializeSHM(", "before",
            BASE + WIN_EXTRA,
            [("int fd = shm_open(Name.c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);",
              "int fd = FEXStatsOpen(Name.c_str(), O_CREAT | O_TRUNC | O_RDWR, USER_PERMS);", 1),
             ("int fd = shm_open(Name.c_str(), O_RDWR, USER_PERMS);",
              "int fd = FEXStatsOpenExisting(Name.c_str(), O_RDWR, USER_PERMS);", 1),
             ("shm_unlink(Name.c_str());", "FEXStatsUnlink(Name.c_str());", 1),
             ("if (ftruncate(fd, MapSize) == -1) {", "if (!FEXStatsTruncate(fd, MapSize)) {", 1),
             ("if (ftruncate(fd, NewSize) == -1) {", "if (!FEXStatsTruncate(fd, NewSize)) {", 1)])

SPEC = [LINUX_SPEC, WIN_SPEC]

NEED_INC = ["#include <cstdlib>", "#include <cstdio>", "#include <cstring>", "#include <cerrno>",
            "#include <string>", "#include <sys/stat.h>"]


def add_includes(text):
    add = [i for i in NEED_INC if i not in text]
    if not add:
        return text, []
    for anchor in ("#include <unistd.h>", "#include <fcntl.h>", "#include \"FEXUnixLib.h\"",
                   "#include \"LinuxSyscalls/ThreadManager.h\""):
        if anchor in text:
            return text.replace(anchor, anchor + "\n" + "\n".join(add), 1), add
    raise SystemExit("ERROR: 找不到可用的 #include 锚点")


def patch_profile_stats(root):
    rel = "FEXCore/Source/Interface/Config/Config.json.in"
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        raise SystemExit("ERROR: 找不到 %s" % path)
    text = open(path, encoding="utf-8", errors="surrogateescape").read()
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
    open(path, "w", encoding="utf-8", errors="surrogateescape").write(text[:k + 1] + "true" + text[e:])
    print("已改写: %s -> ProfileStats Default=true（默认生成 stats）" % rel)
    return True


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = sys.argv[1].rstrip("/")
    target_dir = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("FEX_STATS_DIR") or DEFAULT_DIR)
    total = 0
    for rel, anchor, where, helper_tpl, subs in SPEC:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            raise SystemExit("ERROR: 找不到源文件 %s" % path)
        text = open(path, encoding="utf-8", errors="surrogateescape").read()
        if MARK in text:
            print("跳过（已打过补丁）: %s" % rel)
            continue
        for old, new, n in subs:
            got = text.count(old)
            if got != n:
                raise SystemExit("ERROR: %s 里匹配数 %d != %d -> %s" % (rel, got, n, old[:80]))
            text = text.replace(old, new)
        for bad in ("shm_open(", "shm_unlink(", "ftruncate("):
            if bad in text:
                raise SystemExit("ERROR: %s 里仍残留 %s" % (rel, bad))
        text, added = add_includes(text)
        if anchor not in text:
            raise SystemExit("ERROR: %s 里找不到插入锚点: %s" % (rel, anchor))
        helper = helper_tpl.replace("@DIR@", target_dir)
        text = text.replace(anchor, helper + anchor, 1) if where == "before" else text.replace(anchor, anchor + "\n\n" + helper, 1)
        open(path, "w", encoding="utf-8", errors="surrogateescape").write(text)
        total += 1
        print("已改写: %s（补头文件: %s）" % (rel, ", ".join(a.split()[1] for a in added) or "无"))
    ps = patch_profile_stats(root)
    print("stats 目录 = %s（兜底 /dev/shm）；改写文件数 = %d；ProfileStats 默认开启 = %s"
          % (target_dir, total, "有" if ps else "无（本来就是 true）"))


if __name__ == "__main__":
    main()