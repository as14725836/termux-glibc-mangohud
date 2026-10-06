# fexshm（v2）

把 FEX 的 `shm_open("/fex-<pid>-stats")` 重定向到可写目录，并保证文件不是 0 字节。

## 为什么需要
FEX 通过 `shm_open` 发布 stats，只能落在 glibc 的 SHMDIR（`/dev/shm`）。原生 Termux 没有
`/dev/shm`，于是对象根本没被创建，overlay 只能报 **FEX Not Found!**；即使文件被建出来，
0 字节的 shm 对象也会让 overlay 读到空/损坏的 header。

## v2 相对 v1
- O_CREAT 打开成功后，若文件仍为 0 字节，立刻 `ftruncate` 到 `$FEXSHM_SIZE`（默认 1 MiB）；
  这样即使调用方（FEX 或 wine）之后不做 ftruncate，mmap 也是文件支撑的、大小真实，
  guest 通过映射写入的 header 能被 MangoHud 这类工具读到；
- 每次拦截追加一行日志到 `$FEXSHM_DIR/fexshm.log`（`FEXSHM_LOG=0` 关闭）；
- 其它行为同 v1（非扁平名回落到 /dev/shm）。

## 部署
```sh
bash tools/fexshm/deploy.sh
```

## 自测
```sh
LD_PRELOAD=$PREFIX/glibc/opt/fexshm/libfexshm.so ./your-shm-test
ls -l /data/data/com.termux/files/usr/tmp/fex-*-stats   # 应 >= 4096
tail /data/data/com.termux/files/usr/tmp/fexshm.log
```
