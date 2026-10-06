#!/data/data/com.termux/files/usr/bin/bash
# 部署 fexshm 垫片（Termux 无 /dev/shm，FEX 的 shm_open 需要落到可写目录）
# 用法: bash tools/fexshm/deploy.sh [目标目录]
set -u
SD="$(cd "$(dirname "$0")" && pwd)"
DST="${1:-$PREFIX/glibc/opt/fexshm}"
mkdir -p "$DST"
cp -f "$SD/fexshm.c" "$DST/fexshm.c"
gcc -shared -fPIC -O2 -o "$DST/libfexshm.so" "$DST/fexshm.c"
echo "已部署: $DST/libfexshm.so"
echo
echo "然后在启动 wine 之前注入（startonwinefex 已在启动行前自动注入）:"
echo "  export LD_PRELOAD=$DST/libfexshm.so"
echo "可选环境变量: FEXSHM_DIR（默认 /data/data/com.termux/files/usr/tmp）、FEXSHM_SIZE（默认 1MiB）、FEXSHM_LOG=0 关闭日志"
