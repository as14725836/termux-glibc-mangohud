#!/usr/bin/env bash
# ============================================================
# 以 GE-Proton（GloriousEggroll/proton-ge-custom）的方式构建 FFmpeg 8.1.1
#
# 为什么需要它：
#   Wine 的 dlls/winedmo（winedmo.dll / winedmo.so）本身没有独立的
#   --enable-winedmo 开关。它的 Makefile.in 里只有：
#       UNIX_CFLAGS = $(FFMPEG_CFLAGS)
#       UNIX_LIBS   = $(FFMPEG_LIBS) $(PTHREAD_LIBS)
#   也就是说「启用 winedmo」在工程上等价于「configure --with-ffmpeg
#   且能通过 pkg-config 找到 libavutil/libavformat/libavcodec」。
#   上游 Wine 默认 --with-ffmpeg，但我们之前显式传了 --without-ffmpeg，
#   于是 winedmo 被编成空壳。这里补上 FFmpeg 依赖。
#
# 为什么自编而不是用 apt：
#   ubuntu-24.04 自带的 libav* 是 6.x/7.x，版本不满足固定到 8.1.1 的要求；
#   而且 apt 版本带一堆用不到的解码器/协议，体积大。GE 的做法是自编一套
#   最小化 shared 库（--disable-everything 再逐项打开），这里直接沿用。
#
# GE 的 FFMPEG_CONFIGURE_ARGS（见 proton-ge-custom/Makefile.in）：
#   --enable-shared --disable-static --disable-everything --disable-programs
#   --disable-doc --disable-inline-asm --enable-lzma --enable-bzlib
#   --enable-gnutls --enable-libdav1d --enable-demuxers
#   --enable-protocol=https --enable-decoders --enable-encoders
#   --enable-bsfs --disable-decoder=vvc
#   FFMPEG_DEPENDS = bzip2 dav1d xz
# GE 在 Makefile 里给 i386/x86_64/aarch64 各写了一套 cross-prefix；本 CI 的
# runner 与 Wine 宿主架构都是 x86_64，不需要 cross，直接 native 构建。
#
# 产物：
#   $FFMPEG_PREFIX/{lib,include,lib/pkgconfig}
# 由 pack_winedmo_ffmpeg.py 负责把 libav*.so* 随 Wine 产物一起分发。
# ============================================================
set -euo pipefail

FFMPEG_VERSION="${FFMPEG_VERSION:-8.1.1}"
FFMPEG_PREFIX="${FFMPEG_PREFIX:-/tmp/ffmpeg}"
# ffmpeg.org/releases/ffmpeg-8.1.1.tar.xz 的 sha256（固定版本、固定校验）
FFMPEG_SHA256="${FFMPEG_SHA256:-b6863adde98898f42602017462871b5f6333e65aec803fdd7a6308639c52edf3}"
JOBS="${JOBS:-$(nproc)}"
WORK="${FFMPEG_WORK:-/tmp/ffmpeg-build}"

echo "=========================================="
echo "构建 FFmpeg ${FFMPEG_VERSION}（GE-Proton 方式）"
echo "  prefix : ${FFMPEG_PREFIX}"
echo "  jobs   : ${JOBS}"
echo "=========================================="

# 已构建过则直接复用（同一次 run 内两个 job 各跑一次，互不影响；
# 这里主要是让重复执行幂等）
if [ -f "${FFMPEG_PREFIX}/lib/pkgconfig/libavformat.pc" ] \
   && [ -f "${FFMPEG_PREFIX}/lib/libavformat.so" ]; then
  echo "已存在 ${FFMPEG_PREFIX}，跳过重复构建"
  echo "FFMPEG_ROOT=${FFMPEG_PREFIX}" >> "${GITHUB_ENV:-/dev/null}" 2>/dev/null || true
  [ -n "${GITHUB_ENV:-}" ] && echo "FFMPEG_ROOT=${FFMPEG_PREFIX}" >> "$GITHUB_ENV"
  exit 0
fi

mkdir -p "$WORK"
cd "$WORK"

# ---- 构建依赖（GE 的 FFMPEG_DEPENDS = bzip2 dav1d xz，另加 gnutls）----
_need_apt=""
for p in libbz2-dev liblzma-dev libdav1d-dev libgnutls28-dev zlib1g-dev; do
  dpkg -s "$p" >/dev/null 2>&1 || _need_apt="$_need_apt $p"
done
command -v nasm >/dev/null 2>&1 || _need_apt="$_need_apt nasm"
command -v patchelf >/dev/null 2>&1 || _need_apt="$_need_apt patchelf"
if [ -n "$_need_apt" ]; then
  echo "安装 FFmpeg 构建依赖:$_need_apt"
  sudo apt-get update -qq
  # shellcheck disable=SC2086
  sudo apt-get install -y -qq $_need_apt
fi

TARBALL="ffmpeg-${FFMPEG_VERSION}.tar.xz"
if [ ! -s "$TARBALL" ]; then
  echo "下载 ${TARBALL} ..."
  curl -fsSL --retry 3 --retry-delay 5 -o "$TARBALL.part" \
    "https://ffmpeg.org/releases/${TARBALL}"
  mv "$TARBALL.part" "$TARBALL"
fi

echo "${FFMPEG_SHA256}  ${TARBALL}" | sha256sum -c -
echo "校验通过: ${TARBALL}"

rm -rf "src-${FFMPEG_VERSION}"
mkdir -p "src-${FFMPEG_VERSION}"
tar -xf "$TARBALL" -C "src-${FFMPEG_VERSION}" --strip-components=1
cd "src-${FFMPEG_VERSION}"

# GE 的最小化参数；native x86_64，不设 cross-prefix
./configure \
  --prefix="${FFMPEG_PREFIX}" \
  --arch=x86_64 \
  --target-os=linux \
  --enable-shared \
  --disable-static \
  --disable-everything \
  --disable-programs \
  --disable-doc \
  --disable-inline-asm \
  --enable-lzma \
  --enable-bzlib \
  --enable-gnutls \
  --enable-libdav1d \
  --enable-demuxers \
  --enable-protocol=file \
  --enable-protocol=https \
  --enable-decoders \
  --enable-encoders \
  --enable-bsfs \
  --disable-decoder=vvc

echo "开始编译 FFmpeg ${FFMPEG_VERSION} ..."
make -j"${JOBS}"
make install

# ---- 校验 ----
# 注意：pkg-config --modversion 给的是库 ABI 版本（libavformat 62.12.101），
# 不是 FFmpeg 发行号（8.1.1）。发行号在源码树根的 RELEASE 文件里，
# ffmpeg 8.1.1 的 libavformat ABI major = 62、libavcodec = 62、libavutil = 60。
_pcdir="${FFMPEG_PREFIX}/lib/pkgconfig"
_pcver="$(PKG_CONFIG_PATH="${_pcdir}" pkg-config --modversion libavformat)"
echo "libavformat ABI 版本: ${_pcver}"

_rel="$(cat RELEASE 2>/dev/null | tr -d '[:space:]')"
echo "源码 RELEASE: ${_rel:-<缺失>}"
if [ "${_rel}" != "${FFMPEG_VERSION}" ]; then
  echo "FATAL: 源码 RELEASE=${_rel} != 期望 ${FFMPEG_VERSION}" >&2
  exit 1
fi

# FFmpeg 8.1.1 的 ABI major 硬校验（版本表见 libav*/version*.h）
_pcmajor="${_pcver%%.*}"
if [ "${_pcmajor}" != "62" ]; then
  echo "FATAL: libavformat ABI major=${_pcmajor}，FFmpeg 8.1.1 应为 62" >&2
  exit 1
fi

for m in libavutil libavformat libavcodec; do
  h="$(PKG_CONFIG_PATH="${_pcdir}" pkg-config --variable=includedir "$m")"
  n="$(PKG_CONFIG_PATH="${_pcdir}" pkg-config --modversion "$m")"
  [ -n "$h" ] || { echo "FATAL: pkg-config 拿不到 $m 的头文件路径" >&2; exit 1; }
  [ -f "${h}/${m}/version.h" ] || [ -f "${h}/${m}/version_major.h" ] \
    || { echo "FATAL: ${h}/${m}/version.h 不存在" >&2; exit 1; }
  echo "  $m ABI ${n} @ ${h}"
done

# 确认关键库文件与 SONAME 都在（winedmo.so 的 DT_NEEDED 就是 .so.62 等）
for so in libavformat.so.62 libavcodec.so.62 libavutil.so.60; do
  [ -f "${FFMPEG_PREFIX}/lib/${so}" ] \
    || { echo "FATAL: 缺少 ${FFMPEG_PREFIX}/lib/${so}" >&2; exit 1; }
  echo "  ${so} OK"
done

echo "FFMPEG_ROOT=${FFMPEG_PREFIX}" >> "${GITHUB_ENV:-/dev/null}" 2>/dev/null || true
echo "FFMPEG_ABI=$(PKG_CONFIG_PATH="${_pcdir}" pkg-config --modversion libavformat)" \
  >> "${GITHUB_ENV:-/dev/null}" 2>/dev/null || true
echo "FFmpeg ${FFMPEG_VERSION} 安装到 ${FFMPEG_PREFIX} 完成"
du -sh "${FFMPEG_PREFIX}" || true
