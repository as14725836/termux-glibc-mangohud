# patch11.16-ge11.0

`patch11.16/` 里的补丁是按 **Wine 11.16** 源码行号写的。本仓实际构建的树是
`WinNative-Emu/proton-wine@c53678ab22a85f0fad3588dd34f0452a463bd015`
（GE，ValveSoftware/wine `proton_11.0` + wine-staging，`Wine 11.0`），
而且构建前还会叠加仓库根目录那一大票 media / video-rework 补丁。

两者在同名文件上已有分叉，于是 `termux-wine-full-11.16.patch` 里
`server/mapping.c` 一处 hunk 打不上，整份补丁被构建脚本 `SKIP`，导致
`/tmp` 修复**没有**进入发布的 GE 包，设备上表现为：

```
wineserver: mkdir /tmp/.wine-10521: Permission denied
```

本目录放按 GE 11.0 源码重新生成的补丁，`--fuzz=0` 干净应用。

## 补丁清单

| 文件 | 对应 `patch11.16/` | 状态 |
|---|---|---|
| `termux-wine-full-ge11.0.patch` | `termux-wine-full-11.16.patch` | ✅ 已适配，8 个文件全部干净应用 |

### termux-wine-full-ge11.0.patch

覆盖 8 个文件，与 11.16 版语义完全一致：

| 文件 | 改动 |
|---|---|
| `dlls/ntdll/unix/server.c` | `init_server_dir()`：`/tmp/.wine-<uid>/server-...` → `/data/data/com.termux/files/usr/tmp/...`；`setup_config_dir()`：`Z:` → `/data/data/com.termux/files`，新增 `D:` → `/sdcard` |
| `server/request.c` | `create_server_dir()`：同上（server 侧） |
| `dlls/crypt32/unixlib.c` | `CRYPT_knownLocations[]` 追加 Termux glibc `cacert.pem` |
| `server/unicode.c` | `nls_dirs[]` 追加 Termux glibc `nls` 目录 |
| `dlls/ntdll/unix/thread.c` | 未处理异常继续执行（`NtContinue`）而非终止进程 |
| `dlls/ntdll/unix/virtual.c` | `address/user/working_set_limit`：`0x7fffffff0000` → `0x7fffff0000` |
| `programs/winemenubuilder/winemenubuilder.c` | XDG 数据目录 → Termux glibc share |
| `server/mapping.c` | `init_memory()` 高位空洞 `0x600000000000/0x100000000000` → `0x4000000000/0x1000000000` |

**与 11.16 原补丁的唯一实质差异**：GE 把 `server/mapping.c` 的
`free_map_addr()` 高位版本改名成了 `free_available_high_map_addr()`：

```c
/* Wine 11.16 */
free_map_addr( 0x600000000000, 0x100000000000 );
/* GE 11.0 */
free_available_high_map_addr( 0x600000000000, 0x100000000000 );
```

原 hunk 因此 `FAILED at 225`。这里按新函数名重写同一处地址范围：

```c
free_available_high_map_addr( 0x4000000000, 0x1000000000 );
```

其余 7 个文件的改动内容与 11.16 完全一致，只是重新 diff 以对齐行号。

## 未适配（有意不做）

| 文件 | 原因 |
|---|---|
| `LAA-unix-staging-wow64.patch` | GE/Proton 11.0 **重写了地址空间管理**：`dlls/ntdll/unix/virtual.c` 里已经没有 `set_large_address_space()` 函数（`grep` 为空），`dlls/kernel32/heap.c` 的 `GlobalMemoryStatus()` 也被 Proton 改过，6/10 hunk 无处落点。本仓在构建期用 `patches/wow64/inject_vmem_max_size.py`（`WINEVMEMMAXSIZE`）覆盖同类需求。 |
| `0061-qasf-deliver-compressed-asf-streams.patch` | 需要 Wine 11.16 的 asf 基底结构（`struct asf_stream` 的 `number` 字段、`asf_stream_is_compressed()` 与 reader 侧配套改动），GE 11.0 的 `dlls/qasf` 仍是旧版，4/11 hunk 失败；强行移植要连结构体一起改，风险大于收益，且与 Termux 运行无关。 |
| `0060-quartz-implement-colour-filter.patch` | 构建里已有 `ge-video-rework` 组（`0004-quartz-*`、`0071-winedmo-*` 等）在处理 quartz/winedmo 媒体栈，本目录不再重复注入（试过一版适配，日志里是 `Reversed (or previously applied)`，说明树里已经有对应改动）。 |

## 原样可用（仍留在 `patch11.16/`）

以下补丁对 GE 11.0 直接可用，构建日志里是 `OK  :`：

- `termux-dns-fix.patch`
- `github-custom.patch`
- `github-custom-2.patch`
- `ndis-p10.patch`

## 应用方式

workflow 在 `patch11.16/*.patch` 那一轮循环之前先跑本目录：

```bash
for _ap in "$GITHUB_WORKSPACE"/patch11.16-ge11.0/*.patch; do
  patch -p1 --batch --dry-run --forward --no-backup-if-mismatch < "$_ap" ...
done
```

同样是「先 dry-run 预检、失败就跳过」，不会留 `.rej`，也不会因补丁与新源码
分叉而中断构建。日志里会打印 `OK (adapted): ...` / `SKIP(adapted): ...`。

同一份修复在 `patches/wow64/fix_termux_wine_tmp.py` 里也有一份 Python 兜底
（幂等，检测到已是 Termux 路径就跳过），两者互不冲突：先打补丁，脚本再看到
`already`。