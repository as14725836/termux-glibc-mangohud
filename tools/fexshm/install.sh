#!/data/data/com.termux/files/usr/bin/bash
# 安装 fexshm 垫片到 glibc 环境（在 Termux 里跑）
set -u

DEST="$PREFIX/glibc/opt/fexshm"
SRC="${1:-/sdcard/Download/libfexshm.so}"

if [ ! -f "$SRC" ]; then
    echo "找不到 $SRC"
    echo "也可以直接下载："
    echo "  curl -L -o /tmp/libfexshm.so https://raw.githubusercontent.com/as14725836/termux-glibc-mangohud/main/tools/fexshm/libfexshm.so"
    exit 1
fi

mkdir -p "$DEST"
cp -f "$SRC" "$DEST/libfexshm.so"
chmod 755 "$DEST/libfexshm.so"
echo "已安装: $DEST/libfexshm.so"
sha256sum "$DEST/libfexshm.so"
echo
echo "启动脚本会在启动行之前自动 export LD_PRELOAD=$DEST/libfexshm.so"
echo "验证：启动游戏后 cat \$PREFIX/tmp/fexshm.log"
