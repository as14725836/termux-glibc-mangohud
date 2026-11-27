# DWProton 函数补丁集

本目录从 [`as14725836/wine` 的 `upgrade/dwproton-11.0-17` 分支](https://github.com/as14725836/wine/tree/upgrade/dwproton-11.0-17)选取独立、可说明依赖关系的函数补丁，供本仓库的 [Wine 工作流](../../.github/workflows/wine.yml)使用。它不是整条 DWProton 分支的移植，也不宣称所有新增导出都已完整实现。

## 来源与适用基线

- 来源审计范围：`dawn/wine-11.0-17..8160abdb31761c904e8ecaefa39f06765952f970`，另纳入后续 MCI 修复 [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30)。
- 已审查目标：[`WinNative-Emu/proton-wine@e6a370ff7db61c230df94996f00131e22f9165cf`](https://github.com/WinNative-Emu/proton-wine/commit/e6a370ff7db61c230df94996f00131e22f9165cf)，`proton_11.0`。
- 工作流仅在 `wine_branch=proton` 时应用本目录补丁。其他源码类型记录为 `not-applicable`。
- `proton_commit` 仍允许留空。复现本次审查请显式填入上述目标提交；不同目标提交会产生警告，并且必须通过所有顺序应用检查才能继续。
- 完整分类、排除项、延期系列、ABI 证据与限制见[审计报告](../../docs/wine-function-patch-audit.md)。

## 补丁及顺序

[`series`](series) 是唯一应用顺序；[`SHA256SUMS`](SHA256SUMS) 校验补丁和 `series`。补丁集标识为 `SHA256(SHA256SUMS)`，因此补丁内容和应用顺序都会影响标识。

| 顺序 | 补丁 | 内容与边界 |
| --- | --- | --- |
| 1 | [WinMM 兼容导出、任务清理及 WOW 回调](0001-winmm-legacy-multimedia-compatibility.patch) | 合并、适配六个来源提交；保留目标原有的不相关导出。包含 ABI/返回值、计时器、MCI 清理回归用例，并补齐 `NotifyCallbackData` / `WOW32DriverCallback` 回调环。 |

WinMM 的来源提交依次为：

1. [`d6f3093e737238df5eee860a87810141300245a6`](https://github.com/as14725836/wine/commit/d6f3093e737238df5eee860a87810141300245a6)：i386 `WOW32ResolveMultiMediaHandle`。
2. [`661925a237a16c4667746bb7e9787fc11b119650`](https://github.com/as14725836/wine/commit/661925a237a16c4667746bb7e9787fc11b119650)：`WOWAppExit` 任务清理。
3. [`8160abdb31761c904e8ecaefa39f06765952f970`](https://github.com/as14725836/wine/commit/8160abdb31761c904e8ecaefa39f06765952f970)：旧式多媒体导出及既有 timer API 的回归覆盖。
4. [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30)：通过内部关闭路径清理其他线程所属的 MCI 设备；公开 `MCI_CLOSE` 仍检查调用线程。
5. [`089bbb7d01c6f04655811dfe35cb3bdd9654bfa0`](https://github.com/as14725836/wine/commit/089bbb7d01c6f04655811dfe35cb3bdd9654bfa0)：`WOW32DriverCallback` 及 16 位回调数据结构（`wowmm_callback_data` / `wowmm_callback_args`、临界区保护）。
6. [`b0e10c3ae5c59d55cd394fcc7c4e6c37b8bec1b1`](https://github.com/as14725836/wine/commit/b0e10c3ae5c59d55cd394fcc7c4e6c37b8bec1b1)：`NotifyCallbackData` 注册/注销 16 位回调数据指针。


## 功能限制
- `NotifyCallbackData` / `WOW32DriverCallback` 实现 16 位回调数据环的注册与写入（`DCB_WINDOW` 直接 `PostMessageA`）；它不模拟 NTVDM 中断，也不读取 16 位侧的 `wRecvCount` 推进。环满时静默丢弃回调，与 Windows WOW thunk 的行为仅作结构对齐，未做运行时对照。

- `WOW32ResolveMultiMediaHandle` 为六参数、仅 i386 的失败兼容实现，返回 `FALSE` 且不修改输出；未实现 NTVDM 句柄映射。
- 九个 `*32Message` 导出仅存在于 i386，均为五个 DWORD 参数，返回对应的失败值；未实现 16/32 位消息桥接。
- `mmDrvInstall` 为四参数、`UINT` 返回值，返回 0；未实现动态多媒体驱动安装。
- `WOWAppExit` 的 MCI 清理比较完整任务值，timer 清理使用低 DWORD；timer 任务 0 不清理。退出任务必须已停止访问所属设备。既有 MCI 裸指针/并发关闭和 timer ID 回绕风险仍存在。
- `timeBeginPeriod`、`timeEndPeriod`、`timeGetDevCaps`、`timeGetSystemTime` 和 `timeGetTime` 已存在于目标基线，本补丁只为其增加回归覆盖。

## 工作流与验证

工作流在源码获取后、子模块及 `autogen.sh` 前执行以下步骤：

1. `sha256sum --check --strict SHA256SUMS`。
2. 按 `series` 顺序对每个补丁执行 `git apply --check --whitespace=error-all`，再执行实际 `git apply --whitespace=error-all`。
3. 执行 `git diff --check`。任何校验或应用失败均终止构建，不跳过冲突，不把“已应用”当作成功。
4. 为产物和 Release 名追加 `-fn<补丁集 SHA256 前 12 位>`，并在构建信息及 Release 中记录完整标识、源码提交、审查基线和应用状态。

整合阶段已在精确目标基线文件组成的独立工作树中，顺序应用 `series` 中的补丁并通过应用检查及 `git diff --check`。本地没有编译、语法编译、运行 Wine 或执行测试。补丁携带的回归用例不等于已执行通过；远程交叉编译成功也不等于在目标设备上完成运行时验证。远程构建结论应以对应 GitHub Actions run、日志及产物为准。

维护补丁时须同步更新 `SHA256SUMS`；改变顺序还须同步更新 `series` 及其校验值。
