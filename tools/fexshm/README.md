# fexshm 垫片（让 MangoHud 能读到 FEX 的 stats）

## 背景：为什么 MangoHud 一直显示 `version mismatch` / `FEX Not Found!`

设备实测链路（wine + FEX-2608，hangover 系 wine 的 aarch64 原生 ntdll 侧）：

```
wine/FEX 建出 /data/data/com.termux/files/usr/tmp/fex-<pid>-stats   （大小 0）
     ↓
FEX 立刻 mmap 这个文件并写入 stats header
     ↓  页落在 EOF 之外 → SIGBUS
FEX 判定 stats 不可用，之后不再写  →  文件永远是 0 字节（header.Version == 0）
     ↓
MangoHud: "FEX stats: skip ... (size 0 < header 64)" / "version mismatch (header=0)"
```

关键点：**必须赢在 open 返回之前**。事后用 inotify/轮询把文件撑大（见 `fexsizer`）已经太晚，
FEX 早已因为 SIGBUS 放弃写入 —— 撑出来的只是 1 MiB 全 0 文件，HUD 读到的 header 还是 0。

## 这个垫片做什么

`libfexshm.so` 通过 `LD_PRELOAD` 注入 wine/box64 进程（aarch64 原生侧），拦截：

| 被拦截 | 行为 |
|---|---|
| `shm_open` / `shm_open64` | 重定向到 `$FEXSHM_DIR`（默认 `$PREFIX/tmp`）下的普通文件 |
| `open` / `open64` / `openat` / `openat64` / `creat` / `creat64` | 若目标是 `fex-<数字>-stats` 且 `fstat` 显示 0 字节 → 就地 `ftruncate` 到 `$FEXSHM_SIZE`（默认 1 MiB） |

要点：

* 预分配发生在 **fd 返回给调用方之前**，所以 FEX 的 mmap 一定看到足够大的文件，写 header 不再 SIGBUS；
* 内部只用 `syscall(SYS_openat)` / `syscall(SYS_write)`，不经被 hook 的入口，无自递归；
* 不使用 `dlsym()`，依赖保持 GLIBC_2.17，Termux glibc 可直接加载；
* 日志写到 `$FEXSHM_DIR/fexshm.log`（`FEXSHM_LOG=0` 关闭），用来确认"到底谁建了文件"。

## 编译

```bash
gcc -shared -fPIC -O2 -Wall -o libfexshm.so fexshm.c
```

## 挂载（启动脚本里，必须在启动行之前）

```bash
FEXSHM_LIB="$PREFIX/glibc/opt/fexshm/libfexshm.so"
if [ -f "$FEXSHM_LIB" ]; then
    export FEXSHM_DIR="${FEXSHM_DIR:-$PREFIX/tmp}"
    export LD_PRELOAD="$FEXSHM_LIB${LD_PRELOAD:+:$LD_PRELOAD}"
fi
...  mangohud box64 "$wine" ...
```

## 验证（本地 A/B，`test_open_path.c`）

| 组 | open 后大小 | 写 header 后读回 |
|---|---|---|
| 有垫片（走 `open`） | 1048576 | `Version=2 app_type=3` ✅ |
| 有垫片（走 `openat`） | 1048576 | `Version=2 app_type=3` ✅ |
| 无垫片（对照） | 0 | **Bus error，exit 135** ❌ |

```bash
gcc -O2 -Wall -o fexshm_ab test_open_path.c
TPATH=/data/data/com.termux/files/usr/tmp/fex-12345-stats \
  LD_PRELOAD=$PWD/libfexshm.so ./fexshm_ab open
```

## 与 fexsizer 的关系

`fexsizer`（inotify 目录守护）是**兜底**：万一创建者绕过 libc（静态二进制、直接 syscall），
依旧会把 0 字节文件撑大，至少让后续写入不再 SIGBUS。两者互补，都留着最稳。
