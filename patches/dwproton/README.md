# DWProton Termux 补丁：保留源码原有同步实现

对于没有 esync 的 Wine 分支，不需要先补入 esync 才能使用本目录的
Termux 路径、fsync 共享内存和其他通用改动。使用以下入口，不要直接遍历
`*.patch` 按编号全部应用：

```sh
# 在本仓库根目录执行；源码必须是 Git 工作树根目录。
bash patches/dwproton/apply.sh --check /path/to/wine
bash patches/dwproton/apply.sh /path/to/wine
```

`--check` 只检查，不修改源码。实际应用前也会完成全部预检；通用补丁不兼容
或部分应用时返回非零状态，不写入任何新改动，不重置已有工作区修改。
重复运行会识别已经完整应用的补丁。

## 应用策略

| 补丁 | 新入口的处理方式 |
| --- | --- |
| `03-tgmux-shm-path.patch` | 必需，最先应用；提供通用路径、fsync backing file、模拟器检测头文件。 |
| `02-fsync.patch` | 可选；服务端和客户端均有 fsync 源文件且整份补丁适用时一起应用。不存在或不兼容时明确输出 `SKIP`，保留原有 fsync 实现。 |
| `05-tgmux-integration.patch` | 必需，应用通用 Termux 改动；不再引入任何 esync 头文件、类型或初始化调用。服务端/客户端连接目录一起预检和应用。 |
| `01-esync.patch`、`04-esync-integration.patch` | 跳过，保留目标源码已有的同步后端，包括已有的 esync；入口不会新增 esync，也不会禁用 fsync 或 ntsync。 |

fsync 改动必须两端一致：共享内存文件名包含设备号和 inode，并放在
`WINE_FSYNC_SHM_DIR` → `WINE_TMP_DIR` → `TMPDIR` → Termux tmp 目录。
两端缺任一实现或补丁上下文不兼容时，不会只改其中一端。若识别出已有一端
完整应用、另一端未应用或无法识别，则在写入前报错，请先处理已有的半套改动。
其他无法识别的上下文会明确输出 `SKIP`，仅保证原文件未变，并不验证原有两端
是否已经匹配，也意味着该次没有获得这项 Termux fsync 路径适配；仍需按目标
环境检查并选择原有可用后端。

通用改动保留了临时目录、machine-id、zoneinfo、NLS、Z: 映射、DNS、
模拟器地址范围及 loader 调整。是否适用仍由目标源码的真实上下文决定；
本入口不会强行套用失败的 hunk 或把半套接线留在源码中。

## 为什么隔离 esync

原来的通用补丁还包含 `dlls/ntdll/unix/server.c` 的 `esync.h` 和
`ESYNC_USED_BY_SERVER` 初始化分支。现在这两处归入
`04-esync-integration.patch`，所以跳过 esync 组不会留下 esync 引用。
通用补丁中 Z: 映射的上下文也不再要求存在 `set_case_insensitive()`，
可兼容没有该行的 Valve Wine 源码。

`01` / `04` 保留为单独的 esync backport 材料，不是可独立启用的完整补丁集：
当前文件依赖目标源码已有 `enum esync_type`、`ESYNC_*` 和
`ESYNC_USED_BY_SERVER` 等协议定义。它们没有为所有无 esync 分支补齐协议、
生成文件和初始化路径，事件前状态、mutex 所有者/递归计数及后端协商也仍需
独立适配。不能以 `git apply --check` 成功等同于可编译或可运行。
新入口刻意不应用这两份补丁。

## 验证范围与构建入口

代表性真实源码为 ValveSoftware/Proton `experimental_11.0` 固定的
ValveSoftware/wine 提交 `4c5e47d409a8012da3c678f09650acef4a7a27a1`，
该版本原本没有 esync 实现。验证使用该提交的补丁目标文件及协议/接口文件，
做顺序适用性、重复应用、无 esync 引用和文件差异检查；不涉及本地 Wine 编译
或运行。其他分支请先执行 `--check`；本目录不承诺任意版本都能套用。

本目录与 `patches/dwproton-functions` 是两套独立补丁。工作流
`termux-glibc-wine.yml` 新增 `apply_dwproton_termux` 输入，默认 `false`。
当前 CI 集成限 `proton_repo=ValveSoftware/Proton`；手动选择
`proton_branch=experimental_11.0` 和 `apply_dwproton_termux=true` 可构建本组补丁。
其他来源暂不允许启用该 CI 选项，独立 helper 仍可在预检通过后使用。

工作流先应用独立函数补丁，再运行本入口，之后执行现有的环境优化和构建。
启用时跳过重复的 machine-id / zoneinfo 路径注入，保留兼容单参数与双参数
loader 的 WoW64 host guard，并由现有 DNS guard 避免重复定义。
必需补丁失败会停止 CI，不会吞掉错误继续发布。

启用后的 artifact、包名和 Release tag 使用独立 `-dwtermux` 后缀。
`BUILD_INFO.txt`、Actions summary 和 Release 说明记录通用补丁、fsync、esync
状态及实际使用的 helper、验证器、02/03/05 和 WoW64 host guard 的补丁集 SHA256。
这里的 esync `skipped` 指没有启用 01/04 backport；源码原有的同步实现保持不变。

全部源码注入完成后、configure 之前，`verify.py` 检查通用补丁和已应用的 fsync
改动仍然存在、共享头文件策略完整、单参数 loader 的 host guard 完整且未禁用
原生 ntsync。失败会停止构建。该检查允许现有 CI 的路径改写和代码插入，属于
静态文本检查，不能替代编译或运行验证。通过后，包内保存受检源码（包括 loader）
的 `DWPROTON_SOURCE_SHA256SUMS`；构建信息和 Release 同时记录该清单的 SHA256。
