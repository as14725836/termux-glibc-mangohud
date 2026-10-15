#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decoder-registrations: quartz / MediaFoundation / DMO 解码器类注册补全。

来源
----
Pipetto-crypto/wine 分支 proton-9.0-arm64ec，区间：

    cbfce9d3fe3fc59f970e43dc5320322d878e60b9  (msmpeg2vdec, 最新)
      ... 共 21 条 ...                          (含 quartz/decoder.c、l3codecx.ax 等)
    16f3afd0cadbb0c84c7377b51a935df760fae0a5  (l3codecx.ax, 最旧)

这 21 条提交把原本内联在 winegstreamer.dll 的 DllRegisterServer 注册代码，
搬进各自的 DLL（quartz / l3codecx.ax / colorcnv / mfasfsrcsnk / mfh264enc /
mfmp4srcsnk / msauddecmft / msmpeg2vdec / msvproc / resampledmo / wmadmod），
并在 configure.ac / loader/wine.inf.in 登记。

覆盖的解码器类
--------------
  l3codecx.ax    MP3 Decoder
  quartz         MPEG Video / MPEG Audio / WAVE Parser / AVI Splitter / MPEG1 Splitter
  mfh264enc      H264 Encoder MFT
  msauddecmft    AAC Decoder MFT
  resampledmo    Resampler DMO
  msvproc        Video Processor MFT
  mfmp4srcsnk    MP3 / MPEG4 sink factory + MPEG4 Byte Stream Handler
  mfasfsrcsnk    Asf Byte Stream Handler
  mfsrcsnk       WAV / AVI Byte Stream Handler
  colorcnv       Color Converter DMO
  wmadmod        WMA Decoder DMO
  msmpeg2vdec    H264 Decoder MFT

幂等策略
--------
本补丁为「新建文件型」，无法用内容锚点判断，改用**哨兵文件**：
下列上游 wine 尚未出现的文件若已齐备，则认定「已应用」→ 直接跳过。
部分中间版本可能只含其中几项，因此同样支持「全部齐备」判定。

用法:
    inject_decoder_registrations.py <wine-source-dir> [--dry-run]
"""
import os
import subprocess
import sys

# 哨兵：这些文件在「应用后」必然存在（上游旧版本 / 精简树可能缺）
SENTINELS = [
    "dlls/l3codecx.ax/l3codecx.c",
    "dlls/colorcnv/colorcnv.c",
    "dlls/wmadmod/wmadmod.c",
    "dlls/msvproc/msvproc.c",
    "dlls/resampledmo/resampledmo.c",
    "dlls/msauddecmft/msauddecmft.c",
    "dlls/msmpeg2vdec/msmpeg2vdec.c",
    "dlls/mfh264enc/mfh264enc.c",
]

PATCH_NAME = "decoder-registrations.patch"

# 关键注册痕迹：quartz 自己注册 MPEG Audio Decoder
ANCHOR_FILE = "dlls/quartz/decoder.c"


def note(item, msg):
    print("[dec-reg] %s: %s" % (item, msg), flush=True)


def find_patch():
    here = os.path.dirname(os.path.abspath(__file__))
    ws = os.environ.get("GITHUB_WORKSPACE", "")
    cands = [
        os.path.join(here, PATCH_NAME),
        os.path.join(here, "..", PATCH_NAME),
        os.path.join(here, "..", "decoder-reg", PATCH_NAME),
        os.path.join(ws, "patches", "wow64", PATCH_NAME),
        os.path.join(ws, "patches", "decoder-reg", PATCH_NAME),
        os.path.join(ws, PATCH_NAME),
    ]
    for c in cands:
        c = os.path.normpath(c)
        if c and os.path.isfile(c):
            return c
    return None


def run(cmd, cwd):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa
        return 127, "exec error: %s" % e


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <wine-source-dir> [--dry-run]" % sys.argv[0])
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv

    if not os.path.isdir(root):
        note("find", "SKIP: %s 不是目录" % root)
        return 0
    if not os.path.isfile(os.path.join(root, "configure.ac")):
        note("find", "SKIP: 无 configure.ac，非 wine 源码树")
        return 0

    present = [s for s in SENTINELS if os.path.isfile(os.path.join(root, s))]
    if len(present) == len(SENTINELS):
        note("idempotent", "已应用（%d/%d 哨兵齐备）→ 跳过" % (len(present), len(SENTINELS)))
        return 0
    note("find", "哨兵 %d/%d 存在 → 判定未应用，继续" % (len(present), len(SENTINELS)))

    patch_path = find_patch()
    if not patch_path:
        note("find", "SKIP: 找不到 %s" % PATCH_NAME)
        return 0
    note("find", "使用补丁 %s" % patch_path)

    if dry:
        note("dry-run", "would apply %s to %s" % (patch_path, root))
        return 0

    # 1) 首选 git apply --3way（能处理 rename / new file，且部分上下文偏移）
    rc, out = run(["git", "apply", "--check", "--3way", patch_path], root)
    if rc == 0:
        rc2, out2 = run(["git", "apply", "--3way", patch_path], root)
        if rc2 == 0:
            note("write", "git apply --3way 成功")
            ok = sum(1 for s in SENTINELS if os.path.isfile(os.path.join(root, s)))
            note("verify", "哨兵 %d/%d" % (ok, len(SENTINELS)))
            return 0
        note("apply", "git apply --3way 执行失败 → 回落 patch")
    else:
        note("apply", "git apply --check 未通过 → 回落 patch")

    # 2) 回落 patch -p1（--forward 让"已应用"的 hunk 自动跳过）
    rc3, out3 = run(
        ["patch", "-p1", "--batch", "--forward", "--no-backup-if-mismatch", "-i", patch_path],
        root)
    if rc3 in (0, 1):
        bad = out3.count("FAILED")
        note("write", "patch -p1 完成 rc=%d FAILED=%d" % (rc3, bad))
        ok = sum(1 for s in SENTINELS if os.path.isfile(os.path.join(root, s)))
        note("verify", "哨兵 %d/%d" % (ok, len(SENTINELS)))
        if bad:
            note("apply", "（非致命，继续构建）")
        return 0

    note("apply", "SKIP: 两种方式均失败（非致命）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
