#!/usr/bin/env python3
"""
修复 dlls/winedmo/libavcodec/pcm_byte_order_reverse_bsf.c 与 FFmpeg 8.x 的不兼容。

用法:
    python3 fix_winedmo_ffmpeg8.py <wine 源码树根目录>

=================== 已核实的事实（FFmpeg n8.1.1 源码） ===================
1) libavcodec/bsf_internal.h 中仍声明：
       int ff_bsf_get_packet(AVBSFContext *ctx, AVPacket **pkt);   // 签名未变
   所以原文件对它的用法（拿到 AVPacket**）是正确的。

2) 但 libavcodec/bsf.c 的实现改成：
       int ff_bsf_get_packet(AVBSFContext *ctx, AVPacket **pkt)
       {
           FFBSFContext *const bsfi = ffbsfcontext(ctx);   // 私有容器
           ...
       }
   也就是说 ctx->internal 这个公开成员已经不存在，
   AVBSFInternal 被 FFBSFContext（bsf.c 内部静态类型）取代。

3) libavcodec/bsf.h 中 public 的 AVBitStreamFilter 只剩：
       const char *name;  const enum AVCodecID *codec_ids;  const AVClass *priv_class;
   filter / init / close 都搬进了 bsf_internal.h 的 FFBitStreamFilter：
       typedef struct FFBitStreamFilter {
           AVBitStreamFilter p;      // ← 必须是**第一个成员**
           int priv_data_size;
           int (*init)(AVBSFContext *);
           int (*filter)(AVBSFContext *, AVPacket *);
           void (*close)(AVBSFContext *);
           void (*flush)(AVBSFContext *);
       } FFBitStreamFilter;

4) libavcodec/bsf.c 的 av_bsf_alloc() 会做：
       if (ff_bsf(filter)->priv_data_size)          // ff_bsf = (FFBitStreamFilter*)filter
           ctx->priv_data = av_mallocz(...);
   即它把传入的 AVBitStreamFilter* **当成 FFBitStreamFilter* 解引用**。

5) dlls/winedmo/unix_demuxer.c:148 是这样用的：
       av_bsf_alloc(&ff_pcm_byte_order_reverse_bsf, &stream->filter)

=====> 结论：原文件把 ff_pcm_byte_order_reverse_bsf 定义成裸的
       const AVBitStreamFilter {...}，在 FFmpeg 8 下 av_bsf_alloc
       会读到 p 之后的 priv_data_size / init / filter —— 那是越界垃圾，
       而且 filter 回调压根不会被调用。这是真正的 ABI 断裂点。

=================== 修复 ===================
A. 把 ff_pcm_byte_order_reverse_bsf 定义成 FFBitStreamFilter 布局，
   AVBitStreamFilter 作为第一个成员（.p），从而：
     * 对 unix_private.h 的 extern const AVBitStreamFilter 声明仍然兼容
       （首成员地址 == 结构体地址）；
     * av_bsf_alloc 通过 ff_bsf() 上转型后能正确读到 priv_data_size/init/filter。
B. 用 FFmpeg 8 的 FFBSFContext 布局复刻 ctx 私有区，取回 buffer_pkt / eof，
   从而恢复 ff_bsf_get_packet 的等价行为（不再依赖 ctx->internal）。
C. channels -> ch_layout.nb_channels。
D. 若源码树里 bsf_internal.h 可用（内部 API 头），优先直接用官方 ff_bsf_get_packet。

幂等：含标记 WINEDMO_FFMPEG8_FIX 则跳过。
"""

import io
import os
import sys

TARGET_REL = "dlls/winedmo/libavcodec/pcm_byte_order_reverse_bsf.c"

MARKER = "WINEDMO_FFMPEG8_FIX"

NEW_BODY = r'''/*
 * PCM byte order reverse byte stream format filter
 * Copyright (c) 2025 Conor McCarthy for CodeWeavers
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA
 */

/*
 * WINEDMO_FFMPEG8_FIX
 *
 * 适配 FFmpeg >= 7 / 8.x 的 ABI：
 *   - AVBSFContext.internal 成员已删除，AVBSFInternal 被 libavcodec 内部
 *     FFBSFContext 取代；
 *   - AVBitStreamFilter 只剩 name / codec_ids / priv_class，filter / init /
 *     close 迁入 FFBitStreamFilter（AVBitStreamFilter 为其首成员）；
 *   - av_bsf_alloc() 会把传入的 AVBitStreamFilter* 当作 FFBitStreamFilter*
 *     解引用，因此本文件必须按 FFBitStreamFilter 布局定义过滤器；
 *   - AVCodecParameters.channels 已被 ch_layout.nb_channels 取代。
 */

#if 0
#pragma makedep unix
#endif

#include "config.h"
#include "unix_private.h"

#ifdef HAVE_FFMPEG

/*
 * FFmpeg 8.x 的 FFBitStreamFilter（见 libavcodec/bsf_internal.h）。
 * 若该头可用则直接用官方定义，避免布局漂移。
 */
#ifdef HAVE_LIBAVCODEC_BSF_INTERNAL_H
# include <libavcodec/bsf_internal.h>
#else
typedef struct FFBitStreamFilter
{
    AVBitStreamFilter p;                /* 必须是首成员 */
    int priv_data_size;
    int (*init)( AVBSFContext *ctx );
    int (*filter)( AVBSFContext *ctx, AVPacket *pkt );
    void (*close)( AVBSFContext *ctx );
    void (*flush)( AVBSFContext *ctx );
} FFBitStreamFilter;
#endif

/*
 * FFmpeg 8.x 的 FFBSFContext（见 libavcodec/bsf.c）：
 * 由 av_bsf_alloc 分配，AVBSFContext pub 为首成员。
 * 用它替换原代码里对 ctx->internal 的访问。
 */
typedef struct FFBSFContext
{
    AVBSFContext pub;                   /* 必须是首成员 */
    AVPacket *buffer_pkt;
    int eof;
} FFBSFContext;

static FFBSFContext *ffbsf( AVBSFContext *ctx )
{
    return (FFBSFContext *)ctx;
}

static int bsf_nb_channels( const AVCodecParameters *par )
{
#if defined(FF_API_OLD_CHANNEL_LAYOUT) && FF_API_OLD_CHANNEL_LAYOUT
    return par->channels;
#else
    return par->ch_layout.nb_channels;
#endif
}

/* From FFmpeg，按 8.x 私有布局复刻 ff_bsf_get_packet() 的行为 */
static int winedmo_bsf_get_packet( AVBSFContext *ctx, AVPacket **pkt )
{
    FFBSFContext *const bsfi = ffbsf( ctx );
    AVPacket *tmp_pkt;

    if (bsfi->eof) return AVERROR_EOF;

    if (!bsfi->buffer_pkt || (!bsfi->buffer_pkt->data && !bsfi->buffer_pkt->side_data_elems))
        return AVERROR( EAGAIN );

    tmp_pkt = av_packet_alloc();
    if (!tmp_pkt) return AVERROR( ENOMEM );

    *pkt = bsfi->buffer_pkt;
    bsfi->buffer_pkt = tmp_pkt;

    return 0;
}

static enum AVCodecID reverse_codec_id( enum AVCodecID codec_id )
{
    switch (codec_id)
    {
    case AV_CODEC_ID_PCM_S16BE: return AV_CODEC_ID_PCM_S16LE;
    case AV_CODEC_ID_PCM_S24BE: return AV_CODEC_ID_PCM_S24LE;
    case AV_CODEC_ID_PCM_S32BE: return AV_CODEC_ID_PCM_S32LE;
    case AV_CODEC_ID_PCM_S64BE: return AV_CODEC_ID_PCM_S64LE;
    case AV_CODEC_ID_PCM_F32BE: return AV_CODEC_ID_PCM_F32LE;
    case AV_CODEC_ID_PCM_F64BE: return AV_CODEC_ID_PCM_F64LE;
    case AV_CODEC_ID_PCM_S16LE: return AV_CODEC_ID_PCM_S16BE;
    case AV_CODEC_ID_PCM_S24LE: return AV_CODEC_ID_PCM_S24BE;
    case AV_CODEC_ID_PCM_S32LE: return AV_CODEC_ID_PCM_S32BE;
    case AV_CODEC_ID_PCM_S64LE: return AV_CODEC_ID_PCM_S64BE;
    case AV_CODEC_ID_PCM_F32LE: return AV_CODEC_ID_PCM_F32BE;
    case AV_CODEC_ID_PCM_F64LE: return AV_CODEC_ID_PCM_F64BE;
    default: return codec_id;
    }
}

static int init( AVBSFContext *ctx )
{
    if (bsf_nb_channels( ctx->par_in ) <= 0 || ctx->par_in->sample_rate <= 0)
        return AVERROR( EINVAL );
    if (ctx->par_in->bits_per_coded_sample % 8u)
        return AVERROR( EINVAL );

    ctx->par_out->codec_id = reverse_codec_id( ctx->par_in->codec_id );

    return 0;
}

static int byte_order_reverse_filter( AVBSFContext *ctx, AVPacket *pkt )
{
    unsigned int bytes_per_sample;
    const uint8_t *buf_end;
    const uint8_t *buf;
    unsigned int i;
    AVPacket *in;
    uint8_t *out;
    int ret;

    ret = winedmo_bsf_get_packet( ctx, &in );
    if (ret < 0) return ret;

    buf = in->data;
    buf_end = in->data + in->size;

    ret = av_new_packet( pkt, in->size );
    if (ret < 0) goto fail;
    out = pkt->data;

    ret = av_packet_copy_props( pkt, in );
    if (ret < 0) goto fail;

    bytes_per_sample = ctx->par_in->bits_per_coded_sample / 8u;
    if (!bytes_per_sample)
    {
        ret = AVERROR( EINVAL );
        goto fail;
    }

    while (buf < buf_end)
    {
        for (i = 0; i < bytes_per_sample; ++i)
            out[i] = buf[bytes_per_sample - i - 1];
        buf += bytes_per_sample;
        out += bytes_per_sample;
    }

fail:
    if (ret < 0) av_packet_unref( pkt );
    av_packet_free( &in );
    return ret;
}

static const enum AVCodecID codec_ids[] =
{
    AV_CODEC_ID_PCM_S8,
    AV_CODEC_ID_PCM_S16LE,
    AV_CODEC_ID_PCM_S16BE,
    AV_CODEC_ID_PCM_S24LE,
    AV_CODEC_ID_PCM_S24BE,
    AV_CODEC_ID_PCM_S32LE,
    AV_CODEC_ID_PCM_S32BE,
    AV_CODEC_ID_PCM_S64LE,
    AV_CODEC_ID_PCM_S64BE,
    AV_CODEC_ID_PCM_F32LE,
    AV_CODEC_ID_PCM_F32BE,
    AV_CODEC_ID_PCM_F64LE,
    AV_CODEC_ID_PCM_F64BE,
    AV_CODEC_ID_NONE,
};

/*
 * 按 FFBitStreamFilter 布局定义（AVBitStreamFilter 为首成员），
 * 这样 av_bsf_alloc() 通过 ff_bsf() 上转型读取 priv_data_size / init / filter
 * 才是正确的；对 unix_private.h 里
 *     extern const AVBitStreamFilter ff_pcm_byte_order_reverse_bsf;
 * 的声明依然成立（首成员地址 == 结构体地址）。
 */
const FFBitStreamFilter ff_pcm_byte_order_reverse_bsf =
{
    .p =
    {
        .name      = "pcm_byte_order_reverse",
        .codec_ids = codec_ids,
    },
    .priv_data_size = 0,
    .init           = init,
    .filter         = byte_order_reverse_filter,
    .close          = NULL,
    .flush          = NULL,
};

#endif /* HAVE_FFMPEG */
'''


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    path = os.path.join(root, TARGET_REL)
    if not os.path.isfile(path):
        print("SKIP: 未找到 %s" % path)
        return 0

    src = io.open(path, "r", encoding="utf-8", errors="replace").read()

    if MARKER in src:
        print("NOOP: 已修复 -> %s" % path)
        return 0

    if "struct AVBSFInternal" not in src:
        print("WARN: 未识别到原版 struct AVBSFInternal，放弃修改以策安全")
        print("      文件: %s" % path)
        return 0

    io.open(path, "w", encoding="utf-8", newline="\n").write(NEW_BODY)
    print("OK: 已修复 %s" % path)
    print("    %d -> %d 字节" % (len(src), len(NEW_BODY)))
    return 0


if __name__ == "__main__":
    sys.exit(main())