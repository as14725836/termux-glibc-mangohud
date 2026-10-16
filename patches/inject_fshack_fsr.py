#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inject_fshack_fsr.py — 自适应注入 AMD FSR (fshack) 补丁

来源补丁: 0001-fshack-Implement-AMD-FSR-upscaler-for-fullscreen-hac.patch
          (Win32u fullscreen-hack FSR1: fsr_spv.h + vulkan.c + sysparams.c + win32u_private.h)

设计原则
--------
* 只对"结构兼容"的源码树生效：先 `patch --dry-run` 整体试打，
  任何 hunk FAILED 就判定为不适用 → 打印原因并跳过，绝不污染源码树。
* 幂等：已存在 fsr_spv.h / fs_hack_is_fsr 标记则跳过。
* 永不阻断构建：任何异常都返回 0。

用法
----
    python3 inject_fshack_fsr.py [wine_srcdir]

不带参数时自动探测常见源码树布局。
"""
import os
import re
import subprocess
import sys
import urllib.request

PATCH_NAME = "0001-fshack-Implement-AMD-FSR-upscaler-for-fullscreen-hac.patch"
RAW_URL = ("https://raw.githubusercontent.com/as14725836/termux-glibc-mangohud"
           "/main/" + PATCH_NAME)
MIN_PATCH_SIZE = 100000  # 152646 bytes，低于此视为下载失败

TAG = "[fshack-fsr]"


def log(*a):
    print(TAG, *a, flush=True)


def find_srcdir(explicit=None):
    """定位含 dlls/win32u/vulkan.c 的 wine 源码树。"""
    ws = os.environ.get("GITHUB_WORKSPACE", "")
    cands = []
    if explicit:
        cands.append(explicit)
    if ws:
        cands += [os.path.join(ws, "wine"),
                  os.path.join(ws, "wine", "wine"),
                  os.path.join(ws, "wine", "source"),
                  os.path.join(ws, "source"),
                  ws]
    cands += ["wine", "wine/wine", "wine/source", "source", ".",
              "/opt/wine-src/source", "/opt/wine-src"]
    for c in cands:
        try:
            if c and os.path.isfile(os.path.join(c, "dlls/win32u/vulkan.c")):
                return os.path.abspath(c)
        except OSError:
            pass
    return None


def get_patch():
    """按 环境变量 → workspace → 下载 的顺序获取补丁。"""
    p = os.environ.get("FSHACK_PATCH")
    if p and os.path.isfile(p) and os.path.getsize(p) > MIN_PATCH_SIZE:
        return p
    ws = os.environ.get("GITHUB_WORKSPACE")
    if ws:
        c = os.path.join(ws, PATCH_NAME)
        if os.path.isfile(c) and os.path.getsize(c) > MIN_PATCH_SIZE:
            return c
    dst = os.path.join("/tmp/wine-termux", PATCH_NAME)
    if os.path.isfile(dst) and os.path.getsize(dst) > MIN_PATCH_SIZE:
        return dst
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        urllib.request.urlretrieve(RAW_URL, dst)
        if os.path.getsize(dst) > MIN_PATCH_SIZE:
            return dst
    except Exception as exc:  # noqa: BLE001
        log("补丁下载失败:", exc)
    return None


def already_applied(src):
    if os.path.isfile(os.path.join(src, "dlls/win32u/fsr_spv.h")):
        return True
    v = os.path.join(src, "dlls/win32u/vulkan.c")
    try:
        t = open(v, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return ("fsr_spv.h" in t) or ("fs_hack_is_fsr" in t)


def _run_patch(src, patch, dry):
    cmd = ["patch", "-p1", "--batch", "--forward",
           "--no-backup-if-mismatch"]
    if dry:
        cmd.append("--dry-run")
    with open(patch, "rb") as fh:
        return subprocess.run(cmd, cwd=src, stdin=fh,
                              capture_output=True, text=True)


def apply_patch(src, patch):
    r = _run_patch(src, patch, dry=True)
    out = (r.stdout or "") + (r.stderr or "")
    fails = re.findall(r"^\s*Hunk #\d+ FAILED.*$", out, re.M)
    if fails or "can't find file" in out or "Reversed" in out:
        log(f"dry-run 判定：该源码树不兼容（{len(fails)} 个 hunk FAILED）→ 跳过")
        for line in fails[:6]:
            log("   ", line.strip())
        return False
    log("dry-run 通过：补丁与当前源码树结构兼容，开始应用")

    r2 = _run_patch(src, patch, dry=False)
    if r2.returncode != 0:
        log("应用返回非 0 (rc=%d)，回滚" % r2.returncode)
        subprocess.run(["git", "checkout", "--", "."], cwd=src,
                       capture_output=True)
        return False
    return True


def verify(src):
    ok = True
    if not os.path.isfile(os.path.join(src, "dlls/win32u/fsr_spv.h")):
        log("校验失败: dlls/win32u/fsr_spv.h 未生成")
        ok = False
    rej = subprocess.run(
        ["bash", "-c", "find . -name '*.rej' 2>/dev/null | head -5"],
        cwd=src, capture_output=True, text=True).stdout.strip()
    if rej:
        log("校验失败: 存在 .rej 文件:", rej.replace("\n", " "))
        ok = False
    for f in ("dlls/win32u/vulkan.c", "dlls/win32u/sysparams.c"):
        p = os.path.join(src, f)
        if not os.path.isfile(p):
            continue
        t = open(p, encoding="utf-8", errors="replace").read()
        for a, b in (("{", "}"), ("(", ")"), ("[", "]")):
            if t.count(a) != t.count(b):
                log(f"校验失败: {f} 括号不平衡 {a}{b} "
                    f"{t.count(a)}/{t.count(b)}")
                ok = False
    return ok


def main():
    src = find_srcdir(sys.argv[1] if len(sys.argv) > 1 else None)
    if not src:
        log("未找到 wine 源码树（缺少 dlls/win32u/vulkan.c），跳过")
        return 0
    log("源码树:", src)

    if already_applied(src):
        log("已包含 FSR（fsr_spv.h / fs_hack_is_fsr），跳过")
        return 0

    patch = get_patch()
    if not patch:
        log("补丁不可用，跳过")
        return 0
    log("补丁:", patch, os.path.getsize(patch), "bytes")

    if not apply_patch(src, patch):
        return 0

    if verify(src):
        log("OK: AMD FSR (fshack) 已成功注入 —— 运行期开关 "
            "WINE_FULLSCREEN_FSR=1 / WINE_FULLSCREEN_FSR_STRENGTH")
    else:
        log("WARN: 注入后校验存在问题（不阻断构建）")
    return 0


if __name__ == "__main__":
    sys.exit(main())