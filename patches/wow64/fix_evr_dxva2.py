#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
termux-glibc wine: EVR / DXVA2 视频路径补口（幂等锚点注入）

现象：GE wine 播放视频“白屏有声音”。日志证据：
  warn:evr:video_mixer_transform_ProcessMessage Message not handled 268435459
       # 0x10000003 = MFT_MESSAGE_NOTIFY_START_OF_STREAM
  fixme:evr:video_presenter_control_RepaintVideo            # 返回 E_NOTIMPL
  fixme:dxva2:...GetVideoProcessorDeviceGuids ... semi-stub
  warn:quartz:dmo_demux_thread Stream 1 EOF, queued packets 4010

改动清单（全部带 termux_evr_dxva2 标记）：
  1) evr/mixer.c     ProcessMessage: 显式处理 MFT_MESSAGE_NOTIFY_START_OF_STREAM；
                     default 分支从 E_NOTIMPL 改为 S_OK
  2) evr/presenter.c RepaintVideo: E_NOTIMPL -> S_OK
                     ProcessMessage: default 的 E_NOTIMPL -> S_OK
  3) dxva2/main.c    本地补 D3DFMT_YV12 / D3DFMT_I420 的 FOURCC 定义
  4) dxva2/main.c    处理器输入格式表补 UYVY / YV12 / I420
  5) dxva2/main.c    GetVideoProcessorDeviceGuids: 无匹配时退到设备 0，不再 E_FAIL
  6) dxva2/main.c    GetVideoProcessorRenderTargets: 未知格式只 WARN，不再 E_FAIL
  7) dxva2/main.c    VideoProcessBlt: YUV -> RGB32 走 CPU 转换（d3d9 的 StretchRect
                     不做色彩空间转换；转换不适用时才回退 StretchRect）

注意：d3d9 的 StretchRect 拒绝 access 含 CPU 的表面(d3d9/device.c)，
      所以离屏临时面必须用 D3DPOOL_DEFAULT —— 该池的 offscreen plain surface
      在 d3d9/device.c 里被显式加了 MAP_R|MAP_W，可 LockRect。

用法: python3 fix_evr_dxva2.py <wine-source-root>
"""

import os
import sys

MARK = "termux_evr_dxva2"

RESULT = []


def log(msg):
    print("[evr-dxva2] %s" % msg)


def sub(text):
    return text.replace("@@MARK@@", MARK)


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="surrogateescape") as fp:
            return fp.read()
    except OSError:
        return None


def write_file(path, text):
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as fp:
        fp.write(text)


# ---------------------------------------------------------------- evr/mixer.c

MIXER_CASE_OLD = r"""        case MFT_MESSAGE_NOTIFY_BEGIN_STREAMING:
        case MFT_MESSAGE_NOTIFY_END_STREAMING:"""

MIXER_CASE_NEW = r"""        /* @@MARK@@: 上游把 0x10000003 (MFT_MESSAGE_NOTIFY_START_OF_STREAM)
         * 落到 default 分支返回 E_NOTIMPL，调用方据此认为 mixer 拒绝起流，
         * 于是永远不出帧（日志里的 Message not handled 268435459）。 */
        case MFT_MESSAGE_NOTIFY_START_OF_STREAM:
            break;

        case MFT_MESSAGE_NOTIFY_BEGIN_STREAMING:
        case MFT_MESSAGE_NOTIFY_END_STREAMING:"""

MIXER_DEFAULT_OLD = r"""        default:
            WARN("Message not handled %d.\n", message);
            hr = E_NOTIMPL;"""

MIXER_DEFAULT_NEW = r"""        default:
            /* @@MARK@@: 未实现的控制消息不应让整条视频管线失败 */
            WARN("Message not handled %d.\n", message);
            hr = S_OK;"""


def patch_mixer(root):
    path = os.path.join(root, "dlls/evr/mixer.c")
    text = read_file(path)
    if text is None:
        return "missing dlls/evr/mixer.c"
    if MARK in text:
        return "already"

    changed = []

    if text.count(MIXER_CASE_OLD) == 1:
        text = text.replace(MIXER_CASE_OLD, sub(MIXER_CASE_NEW), 1)
        changed.append("start-of-stream")
    else:
        return "anchor-miss (BEGIN_STREAMING)"

    if text.count(MIXER_DEFAULT_OLD) == 1:
        text = text.replace(MIXER_DEFAULT_OLD, sub(MIXER_DEFAULT_NEW), 1)
        changed.append("default-sok")
    else:
        return "anchor-miss (mixer default)"

    write_file(path, text)
    return "patched (%s)" % ",".join(changed)


# ------------------------------------------------------------ evr/presenter.c

PRESENTER_REPAINT_KEY = "static HRESULT WINAPI video_presenter_control_RepaintVideo(IMFVideoDisplayControl *iface)"

PRESENTER_DEFAULT_OLD = r"""        default:
            FIXME("Unsupported message %u.\n", message);
            hr = E_NOTIMPL;"""

PRESENTER_DEFAULT_NEW = r"""        default:
            /* @@MARK@@: MFVP_MESSAGE_FLUSH 等消息上游未实现，返回失败会让 presenter
             * 停摆（画面一直白），这里只记录不再失败。 */
            FIXME("Unsupported message %u.\n", message);
            hr = S_OK;"""


def patch_presenter(root):
    path = os.path.join(root, "dlls/evr/presenter.c")
    text = read_file(path)
    if text is None:
        return "missing dlls/evr/presenter.c"
    if MARK in text:
        return "already"

    start = text.find(PRESENTER_REPAINT_KEY)
    if start < 0:
        return "anchor-miss (RepaintVideo)"
    end = text.find("\n}\n", start)
    if end < 0:
        return "anchor-miss (RepaintVideo body)"

    body = text[start:end]
    if body.count("hr = E_NOTIMPL;") != 1:
        return "anchor-miss (E_NOTIMPL in RepaintVideo)"

    body = body.replace(
        "hr = E_NOTIMPL;",
        "hr = S_OK; /* %s: 上游返回 E_NOTIMPL，调用方视为致命 */" % MARK,
        1,
    )
    text = text[:start] + body + text[end:]

    if text.count(PRESENTER_DEFAULT_OLD) == 1:
        text = text.replace(PRESENTER_DEFAULT_OLD, sub(PRESENTER_DEFAULT_NEW), 1)
        changed = "repaint-sok,default-sok"
    else:
        changed = "repaint-sok"

    write_file(path, text)
    return "patched (%s)" % changed


# --------------------------------------------------------------- dxva2/main.c

DVXA_DEFINE_OLD = r"""#define D3DFMT_NV12 MAKEFOURCC('N','V','1','2')"""

DVXA_DEFINE_NEW = r"""#define D3DFMT_NV12 MAKEFOURCC('N','V','1','2')
/* @@MARK@@: d3d9types.h 只有 UYVY/YUY2，这两个 FOURCC 本地补 */
#ifndef D3DFMT_YV12
#define D3DFMT_YV12 MAKEFOURCC('Y','V','1','2')
#endif
#ifndef D3DFMT_I420
#define D3DFMT_I420 MAKEFOURCC('I','4','2','0')
#endif"""

DVXA_FORMATS_OLD_SOFT = r"""static const D3DFORMAT software_processor_input_formats[] =
{
    D3DFMT_A8R8G8B8, D3DFMT_X8R8G8B8, D3DFMT_YUY2, 0
};"""

DVXA_FORMATS_NEW_SOFT = r"""static const D3DFORMAT software_processor_input_formats[] =
{
    /* @@MARK@@: 补 UYVY/YV12/I420，软件解码器与播放器最常输出的格式 */
    D3DFMT_A8R8G8B8, D3DFMT_X8R8G8B8, D3DFMT_YUY2, D3DFMT_UYVY,
    D3DFMT_YV12, D3DFMT_I420, 0
};"""

DVXA_FORMATS_OLD_PROG = r"""static const D3DFORMAT progressive_processor_input_formats[] =
{
    D3DFMT_A8R8G8B8, D3DFMT_X8R8G8B8, D3DFMT_YUY2, D3DFMT_NV12, 0
};"""

DVXA_FORMATS_NEW_PROG = r"""static const D3DFORMAT progressive_processor_input_formats[] =
{
    /* @@MARK@@: 补 UYVY/YV12/I420（NV12 保持原样） */
    D3DFMT_A8R8G8B8, D3DFMT_X8R8G8B8, D3DFMT_YUY2, D3DFMT_UYVY,
    D3DFMT_NV12, D3DFMT_YV12, D3DFMT_I420, 0
};"""

DVXA_GUIDS_OLD = r"""    if (!*count)
    {
        CoTaskMemFree(*guids);
        *guids = NULL;
        return E_FAIL;
    }"""

DVXA_GUIDS_NEW = r"""    if (!*count)
    {
        /* @@MARK@@: 输入格式不在表里时不再直接失败，退回设备 0；
         * 真正的 YUV -> RGB 由 VideoProcessBlt 的 CPU 回退负责。 */
        WARN("Unsupported content format %#x, falling back to device 0.\n", video_desc->Format);
        (*guids)[0] = *processor_devices[0].guid;
        *count = 1;
    }"""


def _rt_anchor(formats_name):
    return r"""        if (!dxva_is_supported_stream_format(video_desc, @@FMT@@))
        {
            WARN("Unsupported content format %#x.\n", video_desc->Format);
            return E_FAIL;
        }""".replace("@@FMT@@", formats_name)


def _rt_patch(formats_name):
    return r"""        /* @@MARK@@: 未知输入格式不再让 GetVideoProcessorRenderTargets 整体失败，
         * 否则 mixer 的 SetInputType 会失败、画面永远不出来。 */
        if (!dxva_is_supported_stream_format(video_desc, @@FMT@@))
            WARN("Unsupported content format %#x.\n", video_desc->Format);""".replace("@@FMT@@", formats_name)


DVXA_DECL_OLD = r"""    IDirect3DDevice9 *device;
    unsigned int i;
    RECT dst_rect;
    HRESULT hr;"""

DVXA_DECL_NEW = r"""    IDirect3DDevice9 *device;
    unsigned int i;
    RECT dst_rect;
    HRESULT hr, convert_hr;"""

DVXA_BLT_OLD = r"""        if (FAILED(hr = IDirect3DDevice9_StretchRect(device, samples[i].SrcSurface, &samples[i].SrcRect,
                rt, &dst_rect, D3DTEXF_POINT)))
        {
            WARN("Failed to copy sample %u, hr %#lx.\n", i, hr);
        }"""

DVXA_BLT_NEW = r"""        /* @@MARK@@: d3d9 的 StretchRect 不做色彩空间转换，YUV 源贴进 RGB32
         * 渲染目标只会得到白块；这里先做 CPU 转换（YUV -> X8R8G8B8），
         * 转换不适用（源/目标已经是 RGB）时才回退 StretchRect。 */
        convert_hr = video_processor_convert_copy(device, samples[i].SrcSurface,
                &samples[i].SrcRect, rt, &dst_rect);
        if (FAILED(convert_hr))
        {
            if (FAILED(hr = IDirect3DDevice9_StretchRect(device, samples[i].SrcSurface, &samples[i].SrcRect,
                    rt, &dst_rect, D3DTEXF_POINT)))
            {
                WARN("Failed to copy sample %u, hr %#lx (convert hr %#lx).\n", i, hr, convert_hr);
            }
        }"""

DVXA_HELPER = r"""/* @@MARK@@: d3d9 的 StretchRect 不做 YUV -> RGB 转换，这里给 VideoProcessBlt
 * 一个 CPU 色彩空间转换回退：先转进一块可锁的离屏 RGB32 表面，再贴到渲染目标。
 * 目标必须是 X8R8G8B8/A8R8G8B8；源支持 YUY2/UYVY/NV12/YV12/I420。 */
static DWORD video_processor_yuv_to_rgb32(BYTE y, BYTE u, BYTE v)
{
    int c = (int)y - 16, d = (int)u - 128, e = (int)v - 128;
    int r = (298 * c + 409 * e + 128) >> 8;
    int g = (298 * c - 100 * d - 208 * e + 128) >> 8;
    int b = (298 * c + 516 * d + 128) >> 8;

    if (r < 0) r = 0;
    if (r > 255) r = 255;
    if (g < 0) g = 0;
    if (g > 255) g = 255;
    if (b < 0) b = 0;
    if (b > 255) b = 255;

    return 0xff000000 | ((DWORD)r << 16) | ((DWORD)g << 8) | (DWORD)b;
}

static HRESULT video_processor_convert_copy(IDirect3DDevice9 *device, IDirect3DSurface9 *src,
        const RECT *src_rect, IDirect3DSurface9 *dst, const RECT *dst_rect)
{
    IDirect3DSurface9 *tmp = NULL;
    D3DSURFACE_DESC src_desc, dst_desc;
    D3DLOCKED_RECT src_locked, dst_locked;
    unsigned int x, y, width, height;
    HRESULT hr;

    if (FAILED(hr = IDirect3DSurface9_GetDesc(src, &src_desc)))
        return hr;
    if (FAILED(hr = IDirect3DSurface9_GetDesc(dst, &dst_desc)))
        return hr;

    if (dst_desc.Format != D3DFMT_X8R8G8B8 && dst_desc.Format != D3DFMT_A8R8G8B8)
        return E_NOTIMPL;
    if (src_desc.Format != D3DFMT_YUY2 && src_desc.Format != D3DFMT_UYVY
            && src_desc.Format != D3DFMT_NV12 && src_desc.Format != D3DFMT_YV12
            && src_desc.Format != D3DFMT_I420)
        return E_NOTIMPL;

    if (!src_desc.Width || !src_desc.Height)
        return E_INVALIDARG;

    /* D3DPOOL_DEFAULT 的 offscreen plain surface 在 d3d9/device.c 里被显式加了
     * MAP_R|MAP_W，可以 LockRect；SYSTEMMEM 反而会被 StretchRect 拒绝。 */
    if (FAILED(hr = IDirect3DDevice9_CreateOffscreenPlainSurface(device, src_desc.Width, src_desc.Height,
            D3DFMT_X8R8G8B8, D3DPOOL_DEFAULT, &tmp, NULL)))
    {
        WARN("Failed to create conversion surface, hr %#lx.\n", hr);
        return hr;
    }

    if (FAILED(hr = IDirect3DSurface9_LockRect(src, &src_locked, NULL, D3DLOCK_READONLY)))
    {
        WARN("Failed to lock source surface, hr %#lx.\n", hr);
        IDirect3DSurface9_Release(tmp);
        return hr;
    }
    if (FAILED(hr = IDirect3DSurface9_LockRect(tmp, &dst_locked, NULL, 0)))
    {
        WARN("Failed to lock conversion surface, hr %#lx.\n", hr);
        IDirect3DSurface9_UnlockRect(src);
        IDirect3DSurface9_Release(tmp);
        return hr;
    }

    width = src_desc.Width;
    height = src_desc.Height;

    for (y = 0; y < height; ++y)
    {
        DWORD *dst_row = (DWORD *)((BYTE *)dst_locked.pBits + y * dst_locked.Pitch);

        switch (src_desc.Format)
        {
            case D3DFMT_YUY2:
            {
                const BYTE *row = (const BYTE *)src_locked.pBits + y * src_locked.Pitch;

                for (x = 0; x < width; ++x)
                {
                    const BYTE *p = row + (x & ~1u) * 2;
                    BYTE luma = (x & 1u) ? p[2] : p[0];

                    dst_row[x] = video_processor_yuv_to_rgb32(luma, p[1], p[3]);
                }
                break;
            }

            case D3DFMT_UYVY:
            {
                const BYTE *row = (const BYTE *)src_locked.pBits + y * src_locked.Pitch;

                for (x = 0; x < width; ++x)
                {
                    const BYTE *p = row + (x & ~1u) * 2;
                    BYTE luma = (x & 1u) ? p[3] : p[1];

                    dst_row[x] = video_processor_yuv_to_rgb32(luma, p[0], p[2]);
                }
                break;
            }

            case D3DFMT_NV12:
            {
                const BYTE *y_row = (const BYTE *)src_locked.pBits + y * src_locked.Pitch;
                const BYTE *uv_row = (const BYTE *)src_locked.pBits
                        + src_locked.Pitch * height + (y / 2) * src_locked.Pitch;

                for (x = 0; x < width; ++x)
                    dst_row[x] = video_processor_yuv_to_rgb32(y_row[x], uv_row[(x / 2) * 2],
                            uv_row[(x / 2) * 2 + 1]);
                break;
            }

            case D3DFMT_YV12:
            {
                const BYTE *y_row = (const BYTE *)src_locked.pBits + y * src_locked.Pitch;
                const BYTE *v_row = (const BYTE *)src_locked.pBits + src_locked.Pitch * height
                        + (y / 2) * (src_locked.Pitch / 2);
                const BYTE *u_row = v_row + (src_locked.Pitch / 2) * ((height + 1) / 2);

                for (x = 0; x < width; ++x)
                    dst_row[x] = video_processor_yuv_to_rgb32(y_row[x], u_row[x / 2], v_row[x / 2]);
                break;
            }

            case D3DFMT_I420:
            {
                const BYTE *y_row = (const BYTE *)src_locked.pBits + y * src_locked.Pitch;
                const BYTE *u_row = (const BYTE *)src_locked.pBits + src_locked.Pitch * height
                        + (y / 2) * (src_locked.Pitch / 2);
                const BYTE *v_row = u_row + (src_locked.Pitch / 2) * ((height + 1) / 2);

                for (x = 0; x < width; ++x)
                    dst_row[x] = video_processor_yuv_to_rgb32(y_row[x], u_row[x / 2], v_row[x / 2]);
                break;
            }

            default:
                break;
        }
    }

    IDirect3DSurface9_UnlockRect(tmp);
    IDirect3DSurface9_UnlockRect(src);

    hr = IDirect3DDevice9_StretchRect(device, tmp, src_rect, dst, dst_rect, D3DTEXF_POINT);

    IDirect3DSurface9_Release(tmp);
    return hr;
}

"""


def patch_dxva2(root):
    path = os.path.join(root, "dlls/dxva2/main.c")
    text = read_file(path)
    if text is None:
        return "missing dlls/dxva2/main.c"
    if MARK in text:
        return "already"

    changed = []

    if text.count(DVXA_DEFINE_OLD) == 1:
        text = text.replace(DVXA_DEFINE_OLD, sub(DVXA_DEFINE_NEW), 1)
        changed.append("fourcc")
    else:
        return "anchor-miss (D3DFMT_NV12 define)"

    if text.count(DVXA_FORMATS_OLD_SOFT) == 1:
        text = text.replace(DVXA_FORMATS_OLD_SOFT, sub(DVXA_FORMATS_NEW_SOFT), 1)
        changed.append("soft-formats")
    else:
        return "anchor-miss (software formats)"

    if text.count(DVXA_FORMATS_OLD_PROG) == 1:
        text = text.replace(DVXA_FORMATS_OLD_PROG, sub(DVXA_FORMATS_NEW_PROG), 1)
        changed.append("prog-formats")
    else:
        return "anchor-miss (progressive formats)"

    missing = []
    for fmt_name, tag in (("software_processor_input_formats", "rt-soft"),
                          ("progressive_processor_input_formats", "rt-prog")):
        old = _rt_anchor(fmt_name)
        if text.count(old) == 1:
            text = text.replace(old, sub(_rt_patch(fmt_name)), 1)
            changed.append(tag)
        else:
            missing.append(tag)
    if missing:
        return "anchor-miss (%s)" % ",".join(missing)

    if text.count(DVXA_GUIDS_OLD) == 1:
        text = text.replace(DVXA_GUIDS_OLD, sub(DVXA_GUIDS_NEW), 1)
        changed.append("guids-fallback")
    else:
        return "anchor-miss (device guids)"

    if text.count(DVXA_DECL_OLD) == 1:
        text = text.replace(DVXA_DECL_OLD, DVXA_DECL_NEW, 1)
        changed.append("decl")
    else:
        return "anchor-miss (VideoProcessBlt decls)"

    if text.count(DVXA_BLT_OLD) == 1:
        text = text.replace(DVXA_BLT_OLD, sub(DVXA_BLT_NEW), 1)
        changed.append("blt-convert")
    else:
        return "anchor-miss (VideoProcessBlt body)"

    anchor = "static HRESULT WINAPI video_processor_VideoProcessBlt("
    if text.count(anchor) != 1:
        return "anchor-miss (video_processor_VideoProcessBlt)"

    text = text.replace(anchor, sub(DVXA_HELPER) + anchor, 1)
    changed.append("helper")

    write_file(path, text)
    return "patched (%s)" % ",".join(changed)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

    if not os.path.isdir(os.path.join(root, "dlls")):
        log("WARN: %s 不像 wine 源码根目录，跳过" % root)
        return 0

    for name, func in (
        ("evr/mixer.c", patch_mixer),
        ("evr/presenter.c", patch_presenter),
        ("dxva2/main.c", patch_dxva2),
    ):
        try:
            result = func(root)
        except Exception as exc:  # 任何异常都不阻断构建
            result = "ERROR %s" % exc
        log("%-18s %s" % (name, result))
        RESULT.append(result)

    if any(r.startswith("ERROR") for r in RESULT):
        log("WARN: 有异常，但不阻断构建（相关功能保持上游行为）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
