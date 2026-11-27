# Wine 自定义函数补丁审计

审计记录日期：2026-11-27（UTC）。本报告说明 [DWProton 函数补丁集](../patches/dwproton-functions/README.md)的选取理由、依赖、ABI 边界和验证限制，供维护及复现时核对。

## 1. 结论与本批边界

本批将六个来源提交的窄范围变更整理为三份补丁：WinMM 的非 NTVDM 失败导出、经修正的任务退出清理和 legacy message 失败导出；D3D11 视频解码器创建参数 getter；EVR sample 两个转发实现。原始审计固定在 [`8160abdb31761c904e8ecaefa39f06765952f970`](https://github.com/as14725836/wine/commit/8160abdb31761c904e8ecaefa39f06765952f970)，另纳入后续已发布的 MCI 修正 [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30)。

| 来源提交 | 结论 | 必须保留的条件 |
| --- | --- | --- |
| [`d6f3093e737238df5eee860a87810141300245a6`](https://github.com/as14725836/wine/commit/d6f3093e737238df5eee860a87810141300245a6) | 纳入窄范围 WinMM 失败导出 | `WOW32ResolveMultiMediaHandle` 仅 i386 导出；返回 FALSE 且不改写输出，不能描述成实现了 NTVDM handle 映射。 |
| [`661925a237a16c4667746bb7e9787fc11b119650`](https://github.com/as14725836/wine/commit/661925a237a16c4667746bb7e9787fc11b119650) | 纳入经后续修正的 `WOWAppExit` | 不照搬原提交的跨线程公共 MCI close 路径；完整任务值验证和内部关闭路径须与后续修正一并保留。 |
| [`8160abdb31761c904e8ecaefa39f06765952f970`](https://github.com/as14725836/wine/commit/8160abdb31761c904e8ecaefa39f06765952f970) | 纳入窄范围 legacy message 失败导出 | 保持失败码、参数 ABI 和 `.spec` 架构限制；`mmDrvInstall` 单独保持其 all-architecture 声明。 |
| [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30) | 纳入已发布 MCI 清理修正 | 内部 helper 以完整 `ULONG_PTR task` 检查归属后直接关闭驱动；公开外线程 close 继续拒绝，并携带 worker-MCI 回归用例。 |
| [`82cf881e82527d4c01f1c8c29f39d2259da0a1c9`](https://github.com/as14725836/wine/commit/82cf881e82527d4c01f1c8c29f39d2259da0a1c9) | 纳入真实 getter 实现 | 一并保留私有对象字段、构造时的参数副本、getter 的空指针检查和测试。 |
| [`0e751b956e558782dfa3c9884cf929828dbf8322`](https://github.com/as14725836/wine/commit/0e751b956e558782dfa3c9884cf929828dbf8322) | 纳入真实 sample 转发 | 两个方法转发至包装的 sample；无需带入 EVR child-window/GDI 实验系列。 |

| 应用顺序 | 仓库产物 | 内容边界 |
| --- | --- | --- |
| 1 | [WinMM 兼容导出与任务清理](../patches/dwproton-functions/0001-winmm-legacy-multimedia-compatibility.patch) | 合并、适配上述四个 WinMM 来源提交，保留目标不相关的导出和驱动实现。 |
| 2 | [D3D11 创建参数](../patches/dwproton-functions/0002-d3d11-video-decoder-creation-parameters.patch) | 私有参数副本、getter 和成功路径回归测试；不改变公共 COM vtable。 |
| 3 | [EVR sample 方法委托](../patches/dwproton-functions/0003-evr-forward-video-sample-buffer-methods.patch) | 仅转发两个 sample 缓冲区方法，不引入窗口/GDI 系列。 |

实际应用顺序以 [series](../patches/dwproton-functions/series) 为准；补丁及顺序文件的校验值见 [SHA256SUMS](../patches/dwproton-functions/SHA256SUMS)。

明确不随本批带入：`NotifyCallbackData`/`WOW32DriverCallback` 两提交、MFPlay 非标准 vtable 插槽、不准确的 DXGI frame statistics、仅返回成功的 `SetDisabled`、未接通的 HTTP bytestream、大型图形/媒体/同步/ARM64EC 功能移植，以及普通上游修复和测试补丁。

在固定目标基线的独立文件树中，三份补丁已按顺序完成应用检查、实际应用及 `git diff --check`。这只证明该文件基线上的文本应用和空白检查通过；没有进行本地编译、语法编译、Wine 测试或运行时验证，远程 CI 结果仍须另行核对。具体命令和偏移见第 10 节。

## 2. 审计对象、证据和限制

### 2.1 固定对象

| 对象 | 固定值 |
| --- | --- |
| 源仓库 | [as14725836/wine](https://github.com/as14725836/wine) |
| 选定源分支 | `upgrade/dwproton-11.0-17`；分支名用于说明来源，复现以固定提交为准。 |
| 原始源审计 pin | [`8160abdb31761c904e8ecaefa39f06765952f970`](https://github.com/as14725836/wine/commit/8160abdb31761c904e8ecaefa39f06765952f970) |
| 元数据筛查区间 | `dawn/wine-11.0-17..8160abdb31761c904e8ecaefa39f06765952f970`，391 条提交元数据。 |
| 审计范围外的后续 MCI 修正 | [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30)；已单独读取其实际 diff 并纳入本批。 |
| 目标仓库 | [WinNative-Emu/proton-wine](https://github.com/WinNative-Emu/proton-wine) |
| 目标分支 | `proton_11.0` |
| 实际比对及应用检查的目标 pin | [`e6a370ff7db61c230df94996f00131e22f9165cf`](https://github.com/WinNative-Emu/proton-wine/commit/e6a370ff7db61c230df94996f00131e22f9165cf) |
| 工作流入口 | [Wine 工作流](../.github/workflows/wine.yml) |

源分支后续推进到 MCI 修正提交，不改变原始审计 pin 的结论。工作流的 `proton_commit` 留空时会跟随目标分支的移动 HEAD；要复现本次检查，必须显式指定上述目标 pin。不同目标提交不能沿用本次应用通过结论。

### 2.2 方法与证据层级

- 对 391 条元数据做功能引入候选筛查，重点辨别自定义入口、已有接口的实际实现、内部后端接线、兼容开关、仅成功 stub、普通修复及测试。391 不是逐条、逐行安全审计完成的数量。
- 对下文 WinMM 原始五提交、后续 MCI 修正、窄范围非 WinMM 候选、HTTP/Colour/ASF 候选和补充 13 提交读取实际补丁；对较大功能系列按组件和依赖边界归组。
- 对固定目标 pin 的 WinMM 文件、D3D11 getter、EVR sample 转发、WOW64 notify 接线和 ntdll wrapper 做了定点源码比对。没有逐行证明所有大型系列在目标缺失。
- 补丁整合阶段的顺序应用检查与本节源码审计分开记录，见第 10 节。没有在本地编译、语法编译、运行 Wine 或执行测试；没有可据此认定远程构建通过的结果。
- “没有识别到硬依赖”指已检查源码未发现本批其他自定义提交是运行前提，不代表已证明任意移动目标都能干净应用或正确运行。
- 区分源码/运行时硬依赖、共享测试文件的补丁上下文依赖和单纯 Git 父子关系；下文不把三者混同。
- 证据以实际成功读取的固定提交 diff 和定点源文件为准；读取失败或被截断而未补读的内容不计入已审阅范围。第 9 节提供可复查的固定提交和源码链接。

### 2.3 审计判定口径

新增一个内部 helper 不自动等于新增独立功能；若 helper 只服务既有 API 的生命周期或缓存修复，仍归普通修复。把 E_NOTIMPL 改为 S_OK 而不实现状态，不算真实实现。把失败导出补齐可以纳入，但必须按“可预测失败入口”描述，不能声称支持背后的完整旧子系统。

## 3. WinMM 原始五提交与后续修正

### 3.1 提交、文件及结论

| 提交及原始标题 | 修改文件、规模 | 实际引入 | 依赖与目标兼容性 | 风险与决定 |
| --- | --- | --- | --- | --- |
| [`b0e10c3ae5c59d55cd394fcc7c4e6c37b8bec1b1`](https://github.com/as14725836/wine/commit/b0e10c3ae5c59d55cd394fcc7c4e6c37b8bec1b1) — `winmm: Implement NotifyCallbackData().` | `dlls/winmm/driver.c`、`winemm.h`、`winmm.spec`；25 增、1 删 | 保存 DWORD 回调注册值的 `NotifyCallbackData` 及全局 `wow_mm_callback_data`。 | 是后续 callback 实现的真实前置；固定目标中相关导出仍注释。 | 把 16:16 SEGPTR 当成 DWORD 状态保存，未建立分段指针映射、有效期和所有权协议；不纳入本批。 |
| [`089bbb7d01c6f04655811dfe35cb3bdd9654bfa0`](https://github.com/as14725836/wine/commit/089bbb7d01c6f04655811dfe35cb3bdd9654bfa0) — `winmm: Implement WOW32DriverCallback() and WOW callback data layout.` | 同上三文件；69 增、3 删 | `WOW32DriverCallback` 和 16-slot callback 数据布局。 | 对 `b0e10c3ae5...` 的全局状态/布局有硬依赖；不是 resolver、AppExit 或 legacy message 的运行依赖。 | SEGPTR/线性地址混用、DWORD 指针截断、consumer/wakeup 不完整等为阻断项；不纳入。 |
| [`d6f3093e737238df5eee860a87810141300245a6`](https://github.com/as14725836/wine/commit/d6f3093e737238df5eee860a87810141300245a6) — `winmm: Add WOW32ResolveMultiMediaHandle for non-NTVDM callers.` | `dlls/winmm/winmm.c`、`winmm.spec`、`tests/Makefile.in`、新增 `tests/winmm.c`；103 增、2 删 | i386 `WOW32ResolveMultiMediaHandle` 入口，返回 FALSE 并保留输出。 | 无上述 callback 对的运行依赖；目标缺失新测试文件。其历史父提交是 OpenGL 修复 `35993b4eee...`，不构成函数依赖。 | 仅接受非 NTVDM 的明确失败语义，不能宣称有 handle 转换能力；纳入。 |
| [`661925a237a16c4667746bb7e9787fc11b119650`](https://github.com/as14725836/wine/commit/661925a237a16c4667746bb7e9787fc11b119650) — `winmm: Implement WOWAppExit task cleanup.` | `dlls/winmm/mci.c`、`time.c`、`winemm.h`、`winmm.c`、`winmm.spec`、`tests/winmm.c`；232 增、1 删 | `WOWAppExit(ULONG_PTR task)`：MCI 清理、timer 清理、可选 avicap32 `AppCleanup` 调用。 | 运行逻辑不依赖 resolver；补丁继续修改 resolver 新建的测试文件，因此共享测试上下文依赖 d6。固定目标需要移植对应内部声明/实现。 | 原始 MCI 路径会被公共跨线程 creator 检查拒绝；必须修正后纳入。 |
| [`8160abdb31761c904e8ecaefa39f06765952f970`](https://github.com/as14725836/wine/commit/8160abdb31761c904e8ecaefa39f06765952f970) — `winmm: Add legacy multimedia message exports.` | `dlls/winmm/driver.c`、`winmm.c`、`winmm.spec`、`tests/timer.c`、`tests/winmm.c`；260 增、10 删 | `mmDrvInstall` 及九个 legacy 五 DWORD message 入口。 | 无 callback 运行依赖；共享测试补丁上下文沿 d6 → 661 → 816。固定目标对应导出仍注释。 | 以原始失败码和架构 ABI 为边界纳入；不是完整 16-bit 驱动子系统实现。 |
| [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30) — `winmm: Close task-owned MCI devices during WOWAppExit.` | `dlls/winmm/mci.c`、`tests/winmm.c`；57 增、33 删 | 引入 `MCI_CloseTaskDevice`，内部直接关闭已验证归属的 MCI 驱动；测试加入 worker MCI 和公共外线程 close 拒绝检查。 | 后续修正，位于原审计 pin 之后；基于原 AppExit 清理及同一测试文件。 | 已纳入第一份适配补丁；没有消除原有全部 MCI 并发生命周期风险。 |

### 3.2 ABI 与 callback 阻断项

`b0e10c3ae5...` 的函数声明为：

```c
DWORD WINAPI NotifyCallbackData(UINT uDevID, UINT uMsg, DWORD dwInstance,
        DWORD dwParam1, DWORD parg16);
```

它把 `parg16` 存入 `DWORD wow_mm_callback_data`，返回 0；字段注释明确该值是 16-bit callback data 的 SEGPTR。后续实现却直接将其转换为线性结构指针。

`089bbb7d01...` 的声明为：

```c
BOOL WINAPI WOW32DriverCallback(DWORD dwCallback, DWORD dwFlags, WORD wID,
        WORD wMsg, DWORD dwUser, DWORD dw1, DWORD dw2);
```

具体问题：

1. 没有 SEGPTR 到线性地址的有效映射协议，也没有与 16-bit 消费端的共享内存/生命周期约束；单纯增加 `MapSL` 式调用不能替代完整设计。
2. DWORD 注册值/回调值在 64-bit 线性指针情形会截断，不能因为 `.spec` 可导出就视为架构安全。
3. 临界区仅在此前全局为零、且收到非零注册值的特定路径初始化，注册切换/重入协议没有完整处理。
4. ring 的下一索引按 16 取模，但访问使用未经完整验证的 `args[wSendCount]`；修复索引仍不能补齐消费端。
5. ring 满时仍返回 TRUE；未见完整的消费唤醒、积压处理和回调完成协议。
6. `DCB_WINDOW` 把 `LOWORD(dwCallback)` 当成 HWND，依赖未说明的句柄语义。

因此，不应只修临界区或索引后就带入这对提交。本批失败导出、任务退出清理均不需要它们。

### 3.3 Resolver 与 legacy 失败导出的精确语义

Resolver：

```c
BOOL WINAPI WOW32ResolveMultiMediaHandle(UINT type, UINT direction,
        WORD handle16, WORD *result16, HANDLE handle32, HANDLE *result32);
```

`.spec` 限 i386，参数形式 `(long long long ptr long ptr)`。当前实现一律返回 FALSE，输出指针所指值保持不变。其价值是让非 NTVDM 调用者收到稳定失败，未实现 16/32 位 handle 双向映射。

Legacy 入口矩阵：

| 入口 | 架构/参数 | 返回语义 |
| --- | --- | --- |
| `mmDrvInstall` | all architectures；四参数、`UINT` 返回；`.spec` 为 `(ptr wstr ptr long)` | 恒定返回 0；不执行动态多媒体驱动安装。 |
| `aux32Message`、`mid32Message`、`mod32Message`、`mxd32Message`、`wid32Message`、`wod32Message` | i386；五个 DWORD 参数 | `MMSYSERR_NOTSUPPORTED`。 |
| `joy32Message`、`tid32Message` | i386；五个 DWORD 参数 | `TIMERR_NOCANDO`。 |
| `mci32Message` | i386；五个 DWORD 参数 | 返回 1。 |

以上应保留源码中的具体值，不要统一成 S_OK、0 或同一个通用失败码。

`timeBeginPeriod`、`timeEndPeriod`、`timeGetDevCaps`、`timeGetSystemTime` 和 `timeGetTime` 已存在于目标基线；本批只增加这些 API 的回归覆盖，不把测试计为新实现。

### 3.4 WOWAppExit 的清理依赖与已发布修正

入口先做 MCI 清理，再以 `(DWORD)task` 做 timer 清理，最后仅在 avicap32 已加载且导出存在时调用 `AppCleanup`。本批采用原 AppExit 提交与后续已发布修正 [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30) 的组合，不单独移植原始清理路径。

- **原始 MCI 阻断**：原提交从其他线程调用公共 close，会命中 creator-thread 限制而失败。不能简单删除公共 creator 检查，也不能经 `MCI_SendCommandFrom32` 绕行——该 dispatcher 自身亦有独立 creator 检查。
- **已发布修正**：`MCI_CleanupTask` 通过 `MCI_CloseTaskDevice` 清理。helper 以完整 `ULONG_PTR task` 核对 `CreatorThread`，不先窄化成 DWORD；验证后直接调用 `SendDriverMessage(..., MCI_CLOSE_DRIVER, ...)`，再沿 `MCI_UnLoadMciDriver` 卸载。公开 `MCI_Close` 仍以 `GetCurrentThreadId()` 作为期望 owner 调用 helper，因此外线程公开关闭继续返回 `MCIERR_INVALID_DEVICE_NAME`。
- **Timer**：creator 记录是 DWORD；清理在锁内快照 timer IDs、锁外 kill，task 0 跳过 timer 清理。保留这一锁序；WORD timer ID 可回绕的既存约束仍存在，不能把此次移植宣称为完整 timer 并发重构。64 位任务值在 MCI 与 timer 路径上的处理不同，不能统一窄化。
- **MCI 生命周期**：退出任务必须已经停止访问自己的设备。原有查询使用解锁后裸指针，仍有并发 close/lifetime 风险；本批修正任务清理的必要路径，没有解决所有既存并发生命周期问题。
- **avicap32**：原源 pin 的 builtin avicap32 导出表没有 `AppCleanup`。因此这个可选 hook 对 builtin 不产生实际清理；不能据此声称已增加 builtin avicap 清理实现。
- **测试边界**：原提交的 worker 只创建 timer，不能证明跨线程 MCI 清理。后续修正让 worker 创建 MCI 设备，增加外线程公开 close 拒绝、任务清理关闭 worker 设备、无关任务不误清理等用例；这些测试随补丁交付，但尚未执行。测试源码存在不等于测试通过。

### 3.5 依赖类型与最小文件并集

| 关系 | 类型 | 移植解释 |
| --- | --- | --- |
| `b0e10c3ae5...` → `089bbb7d01...` | 真实源码/运行依赖 | callback 消费新增的全局注册状态和布局；两者一起排除。 |
| `35993b4eee...` → `d6f3093e73...` | Git 历史父子 | OpenGL framebuffer 修复不是 WinMM resolver 的依赖。 |
| `d6f3093e73...` → `661925a237...` → `8160abdb31...` | 共享测试补丁上下文 | `tests/winmm.c` 逐步建立/扩展；生产入口之间没有据此形成 callback 或 resolver 的运行依赖。 |
| `WOWAppExit` → MCI/timer helper | 真实内部实现依赖 | 必须一并移植私有声明和清理实现，并修正 MCI 路径。 |
| [`661925a237a16c4667746bb7e9787fc11b119650`](https://github.com/as14725836/wine/commit/661925a237a16c4667746bb7e9787fc11b119650) → [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30) | 清理实现修正及共享测试上下文 | 原 AppExit 功能与后续 MCI 修正作为同一 WinMM 交付单元；不能省略修正或只增加测试。 |

WinMM 最小文件并集：

```text
dlls/winmm/driver.c
dlls/winmm/winmm.c
dlls/winmm/winmm.spec
dlls/winmm/winemm.h
dlls/winmm/mci.c
dlls/winmm/time.c
dlls/winmm/tests/Makefile.in
dlls/winmm/tests/winmm.c
dlls/winmm/tests/timer.c
```

这只是精确变更会触及的并集，不是整文件覆盖清单。整体替换 `driver.c`、`winemm.h` 或 `.spec` 会重新带入被排除的 callback 对和其他分支差异。

固定目标的 `tests/winmm.c` 确实不存在；`winemm.h` 才是本目录私有头文件，不能误用不存在的 `winmm_private.h`。

## 4. 非 WinMM 窄范围实现和排除矩阵

| 提交及原始标题 | 文件/实际作用 | 依赖、风险与结论 |
| --- | --- | --- |
| [`82cf881e82527d4c01f1c8c29f39d2259da0a1c9`](https://github.com/as14725836/wine/commit/82cf881e82527d4c01f1c8c29f39d2259da0a1c9) — `d3d11: Implement video decoder creation parameters.` | `dlls/d3d11/d3d11_private.h`、`decoder.c`、`tests/d3d11.c`；28 增、3 删。在私有对象保存 desc/config，构造时拷贝，`ID3D11VideoDecoder::GetCreationParameters` 检查输出指针并返回副本/S_OK。 | 真实实现；字段、构造赋值、getter、测试不可只取其一。固定目标 getter 返回 E_NOTIMPL，私有对象没有这两个字段。未识别到本分支其他自定义功能的硬依赖；本批纳入。 |
| [`0e751b956e558782dfa3c9884cf929828dbf8322`](https://github.com/as14725836/wine/commit/0e751b956e558782dfa3c9884cf929828dbf8322) — `evr: implement video_sample ConvertToContiguousBuffer()/CopyToBuffer().` | `dlls/evr/sample.c`；10 增、2 删。对包装的 sample 真实转发两个方法。 | 固定目标两个方法返回 E_NOTIMPL；独立于 child-window、窗口显隐和 GDI 呈现系列；本批纳入。 |
| [`10487b0812d80761378dc3886a985b0899323250`](https://github.com/as14725836/wine/commit/10487b0812d80761378dc3886a985b0899323250) — `ntdll: Compress LZNT1 buffers` | `dlls/ntdll/rtl.c`、`tests/rtl.c`；112 增、21 删。增加贪心 LZNT1 编码；4 KiB chunk、栈缓冲 `UCHAR compressed[0x1200]`、压缩/原始头 `0xb000`/`0x3000`。 | 是真实算法工作，但 workspace、chunk_size 合约仍需审查，需边界、往返、兼容和性能验证。目标 wrapper 的 semi-stub/lznt1 helper 路径已看到，未据此证明目标 helper 完全无实现。本批排除，单独评估。 |
| [`a8fd12ce361969112abc75bb902c3b6ae53b5745`](https://github.com/as14725836/wine/commit/a8fd12ce361969112abc75bb902c3b6ae53b5745) — `wow64: Add BTCpuNotifyProcessExecuteFlagsChange interface.` | `dlls/wow64/process.c`、`syscall.c`、`wow64_private.h`；9 增、1 删。成功设置 ProcessExecuteFlags 后，可选调用动态解析的 CPU backend notify。 | 是后端接线，不是独立通用 WOW64 能力；需提供该入口的 backend 及错误语义配合。固定目标相关路径直接转发，未见新增 symbol；本批不带入。 |
| [`dc0b6e5fe7eaa4c8b9f65ef45f6c108da79d8470`](https://github.com/as14725836/wine/commit/dc0b6e5fe7eaa4c8b9f65ef45f6c108da79d8470) — `mfplay: add the missing IMFPMediaPlayer::SetVideoWindow().` | `dlls/mfplay/player.c`；27 增。新增 helper 并把方法槽插在 `GetAspectRatioMode` 与 `GetVideoWindow` 之间。 | **拒绝，ABI 阻断**：标准 `IMFPMediaPlayer` 没有 `SetVideoWindow`；本 pin 的 `include/mfplay.idl` 也没有。插槽使后续所有 COM 方法偏移，包括 Shutdown。不能按标题“missing”认定标准接口缺失。 |
| [`2f99d74c8cbd4f5dd2545bb4d165fa7efc20f693`](https://github.com/as14725836/wine/commit/2f99d74c8cbd4f5dd2545bb4d165fa7efc20f693) — `dxgi: semi-stub IDXGISwapChain::GetFrameStatistics.` | `dlls/dxgi/swapchain.c`；68 增、4 删。用 QPF/Hz 估计 refresh，sync count 用 Hz，GPU 时间置 0；静态 once 在 swapchain 间共享且无同步。 | 返回 DISJOINT 后 S_OK，但值不是有效 frame statistics；不准确的 semi-stub，本批排除。 |
| [`3a4781f6a846a4fc077f46874fd811b79851ac2f`](https://github.com/as14725836/wine/commit/3a4781f6a846a4fc077f46874fd811b79851ac2f) — `mfplat: Return success from SetDisabled` | `dlls/mfplat/main.c`、`tests/mfplat.c`；17 增、1 删。E_NOTIMPL 改 S_OK，没有实现 disabled 状态。 | 成功-only stub，不算真实状态实现；本批排除。 |
| [`cb2b60edeec68b7e53e5128e9b3239606409754d`](https://github.com/as14725836/wine/commit/cb2b60edeec68b7e53e5128e9b3239606409754d) — `mfplat: allow stubbing out MFCreateDXGIDeviceManager.` | `dlls/mfplat/main.c`；11 增。非空环境变量 `WINE_DO_NOT_CREATE_DXGI_DEVICE_MANAGER` 让函数在参数验证前返回 E_NOTIMPL。 | 兼容绕过开关，不是实现；字符串 `"0"` 也会触发。可影响错误优先级；本批排除。 |

### 4.1 本批两个真实实现的附加限制

D3D11 补丁只扩展私有对象状态，不增加或移动公共 COM vtable 方法槽。getter 的空输出参数返回 `E_INVALIDARG` 是候选实现的策略，尚无 Windows 对照验证；附带回归测试只覆盖成功路径，不足以验证全部错误语义。

EVR 两个方法的 HRESULT、锁和引用计数语义由包装的内部 sample 决定。直接 non-NULL surface 路径仍有 `Lock`/`Unlock` 未实现、缺少 2D 接口等限制；这次转发不能推导出所有视频路径均已修复，也不能当成零拷贝保证。

### 4.2 固定目标 pin 的源码证据

以下链接固定到 [`e6a370ff7db61c230df94996f00131e22f9165cf`](https://github.com/WinNative-Emu/proton-wine/commit/e6a370ff7db61c230df94996f00131e22f9165cf)，行号仅适用于该提交：

| 位置 | 已观察到的事实 |
| --- | --- |
| [WinMM 导出表 194–202](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/winmm/winmm.spec#L194-L202) | Notify/WOW callback/resolver/AppExit、mmDrvInstall/aux32Message 等相关声明仍注释。 |
| [MCI_Close 区域](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/winmm/mci.c#L1810-L1845)、[command dispatcher 区域](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/winmm/mci.c#L2073-L2105) | 已有 MCI_Close、递归 close 与 command dispatcher；移植不能照用源 pin 行号。 |
| [WinMM 私有声明区域 146–159](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/winmm/winemm.h#L146-L159) | 正确私有头为 `winemm.h`。 |
| [D3D11 getter 119–123](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/d3d11/decoder.c#L119-L123)、[私有结构 625–633](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/d3d11/d3d11_private.h#L625-L633) | getter 为 E_NOTIMPL，结构缺 desc/config 副本。 |
| [EVR ConvertToContiguousBuffer 1344–1348](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/evr/sample.c#L1344-L1348)、[CopyToBuffer 1387–1391](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/evr/sample.c#L1387-L1391) | 两个被选中的 sample 方法为 E_NOTIMPL。 |
| [WOW64 ProcessExecuteFlags 934–939](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/wow64/process.c#L934-L939) | 原路径直接转发，未见候选增加的 backend notify。 |
| [ntdll RtlCompressBuffer 区域 1133–1149](https://github.com/WinNative-Emu/proton-wine/blob/e6a370ff7db61c230df94996f00131e22f9165cf/dlls/ntdll/rtl.c#L1133-L1149) | wrapper、semi-stub 标记及 lznt1 helper 调用；不据此外推整个 helper 的实现质量。 |

## 5. HTTP、Colour/ASF 等较大候选

| 提交 | 实际内容 | 耦合/阻断与结论 |
| --- | --- | --- |
| [`73049a8854b9ab23b553b3b945cca9c354c2675f`](https://github.com/as14725836/wine/commit/73049a8854b9ab23b553b3b945cca9c354c2675f) — `mfplat: add HTTP/HTTPS IMFByteStream implementation.` | `dlls/mfplat/Makefile.in`、`http_error.c`、`main.c`、`mfplat_private.h`、`network.c`；2407 增、31 删。2016 行 WinHTTP/bcrypt HTTP/HTTPS stream、356 行 HRESULT mapper、约 30 个 attribute helper 去 static。 | 单独该提交的 `network.c` 末尾残留字面量 `2.45.2`，是编译阻断；不能独立移植。 |
| [`536b925ae313f56c4304ac5eba6933acd3be4982`](https://github.com/as14725836/wine/commit/536b925ae313f56c4304ac5eba6933acd3be4982) — `mfplat: fix the HTTP bytestream build.` | `dlls/mfplat/network.c`、`include/mfidl.idl`；移除残留字面量，增加 `MFNETSOURCE_STATISTICS_SERVICE`。 | 是上一提交的必要编译伴随；但两者一起仍不等于已交付 HTTP 支持。 |
| 上述 HTTP 对在审计 pin 的接线检查 | `create_http_bytestream` 在 `network.c:1925` 只有定义；GUID 使用在 `network.c:1225`、定义在 `mfidl.idl:1631`。 | 未找到 caller 或将 HTTP scheme 路由到该工厂的注册；没有接上 `CLSID_HttpSchemePlugin`。因此功能在该 pin 未接通，不能声明本批已支持 HTTP/HTTPS。后续须完整检查路由、异步 I/O、seek、取消、错误和生命周期，再独立决定。 |
| [`1e1c10d7257b0dce09e0afc3f234e88a2b08d00f`](https://github.com/as14725836/wine/commit/1e1c10d7257b0dce09e0afc3f234e88a2b08d00f) — `quartz,qasf: add the colour space converter and deliver compressed ASF.` | `dlls/qasf/asfreader.c`、`tests/asfreader.c`；`dlls/quartz/Makefile.in`、`colour.c`、`main.c`、`quartz_private.h`、`quartz_strmif.idl`、`tests/Makefile.in`、`tests/colour.c`；1171 增、28 删。 | 是真实但较宽的功能：462 行注册的 CLSID_Colour，RGB8/555/565/24/32 GDI DIB 转换，MERIT_UNLIKELY，pins/seeking/quality/events；ASF 经 IWMProfile/GetStream 取 stream number/压缩 AM_MEDIA_TYPE，IWMReaderAdvanced2 开启压缩交付、OnStreamSample 推样本。依赖 strmbase/GDI/WM 解码和注册链；本批不带入，需单独审计。 |

## 6. 其他自定义功能系列的依赖分组

本节记录候选系列和最小组件边界，不声称逐行安全审计已完成，也不声称目标固定 pin 缺少每项 Proton 等价实现。它们均不属于本批 WinMM/D3D11 getter/EVR sample 的硬依赖。

### 6.1 Fshack、FSR、饱和度及 ArtCNN

| 系列/提交 | 主要文件 | 依赖结论 |
| --- | --- | --- |
| Fshack — [`1e46bd8865ed628936aa7c3b95a1daef871f0be4`](https://github.com/as14725836/wine/commit/1e46bd8865ed628936aa7c3b95a1daef871f0be4) | `dlls/win32u/vulkan.c`；`dlls/winemac.drv/vulkan.c`；`dlls/winewayland.drv/vulkan.c`；`dlls/winex11.drv/init.c`、`opengl.c`、`vulkan.c`、`x11drv.h`；`include/ntuser.h`、`include/wine/vulkan_driver.h` | 跨 win32u/平台驱动的协议与数据结构变更，不可只取某个 exported helper。 |
| FSR — [`5be4684a57699d23acce564bba1892a19b67271c`](https://github.com/as14725836/wine/commit/5be4684a57699d23acce564bba1892a19b67271c) | `FSR.md`；`dlls/win32u/fsr_spv.h`、`sysparams.c`、`vulkan.c`、`win32u_private.h` | 建立在 fshack 缩放/呈现基础设施上。 |
| SDR saturation — [`99c94ad8e28109706a30f853d37ed3db441a8457`](https://github.com/as14725836/wine/commit/99c94ad8e28109706a30f853d37ed3db441a8457) | FSR 文件及 `dlls/win32u/fsr_rcas.comp` | 依赖 FSR shader 和配置链。 |
| ArtCNN — [`c746a8163cfbf07e704fcff7a792fbb1e1fecc1d`](https://github.com/as14725836/wine/commit/c746a8163cfbf07e704fcff7a792fbb1e1fecc1d) | `ARTCNN.md`、`FSR.md`；`dlls/win32u/artcnn.comp`、`artcnn_c4f16.glsl`、`artcnn_generate.py`、`artcnn_spv.h`、`artcnn_test.py`、`sysparams.c`、`vulkan.c`、`win32u_private.h` | 包含模型/shader 生成、配置和呈现接线；依赖缩放基础设施，非独立小函数。 |

### 6.2 GDI+ 竖排文字

耦合顺序：

1. [`062d3b8df1ba9440f90f809b759aece97bf16957`](https://github.com/as14725836/wine/commit/062d3b8df1ba9440f90f809b759aece97bf16957)：私有头声明/状态。
2. [`13dc2ec56d5eddd561738c761dab89db5ecb8696`](https://github.com/as14725836/wine/commit/13dc2ec56d5eddd561738c761dab89db5ecb8696)：`font.c`。
3. [`8c86f003ceb99bb2746b9e394ed0ce64c9ad9b72`](https://github.com/as14725836/wine/commit/8c86f003ceb99bb2746b9e394ed0ce64c9ad9b72)：`graphicspath.c`。
4. [`27fe5fae2d18fb3a6d213a39091d14580412c0ce`](https://github.com/as14725836/wine/commit/27fe5fae2d18fb3a6d213a39091d14580412c0ce)：`graphics.c`。

按文字布局、路径和绘制共同能力看待，不将内部 helper 拆作彼此独立的函数交付；本批不带入。

### 6.3 HEVC 与 Proton 媒体栈

| 系列/提交 | 主要组件 | 依赖与分类 |
| --- | --- | --- |
| HEVC — [`3e76c8de5c6ec9bb24e87f58f193fbadd48858e2`](https://github.com/as14725836/wine/commit/3e76c8de5c6ec9bb24e87f58f193fbadd48858e2) | `.github/workflows/build.yml`；`dlls/mfreadwrite/reader.c`、`tests/Makefile.in`、`tests/hevc.c`、`tests/resource.rc`、`tests/test-hevc-main.mp4`、`tests/test-hevc-main10.mp4`；`dlls/mfsrcsnk/media_source.c`；`dlls/winedmo/main.c`、`unix_demuxer.c`、`unixlib.h`、`winedmo.spec`；`dlls/winegstreamer/gst_private.h`、`main.c`、`mfplat.c`、`unixlib.h`、`video_decoder.c`、`wg_media_type.c`、`winegstreamer_classes.idl`；`include/codecapi.h`、`include/wine/winedmo.h` | decoder/demux/registration/FFmpeg/GStreamer/test assets 的耦合功能；伴随失败读取修复 [`2571b3135167855914c08aba0640bef94ac37e59`](https://github.com/as14725836/wine/commit/2571b3135167855914c08aba0640bef94ac37e59)。 |
| Proton audio — [`4dcbcf9475cdeebb2cb236fcac6860852b392f71`](https://github.com/as14725836/wine/commit/4dcbcf9475cdeebb2cb236fcac6860852b392f71) | `dlls/winegstreamer/Makefile.in`、`audio_decoder.c`、`gst_private.h`、`mfplat.c` | 新音频解码路径；[`acfe819d767eb85a6dfe84214ddb28ff19b2f763`](https://github.com/as14725836/wine/commit/acfe819d767eb85a6dfe84214ddb28ff19b2f763) 移除旧 AAC 构建，需一起理解注册和构建替换。 |
| Media converter — [`dd618c53da12e133fd017136ab62fd11023332d4`](https://github.com/as14725836/wine/commit/dd618c53da12e133fd017136ab62fd11023332d4) | `dlls/winegstreamer/Makefile.in`；`media-converter/audioconv.c`、`audioconvbin.c`、`fossilize.c`、`lib.c`、`media-converter.h`、`murmur3.c`、`protondemuxer.c`、`videoconv.c`；`unix_private.h`、`unixlib.c`、`unixlib.h`、`wg_task_pool.c` | 完整插件/转码和缓存链，不是可单摘的一个 API。 |
| Decode/resampler — [`9af7859c2c477e8556a787b4723d9b7dd57a6de3`](https://github.com/as14725836/wine/commit/9af7859c2c477e8556a787b4723d9b7dd57a6de3) | `dlls/winedmo/unix_media_type.c`、`dlls/winegstreamer/resampler.c` | 依附媒体类型/后端链；单独移植前须比较目标等价实现。 |
| Proton media — [`b96c1278d26ad231839dd9b84ad9f8e92c10d8cd`](https://github.com/as14725836/wine/commit/b96c1278d26ad231839dd9b84ad9f8e92c10d8cd) | `.github/workflows/build.yml`、`configure`、`configure.ac`；`dlls/winegstreamer/color_convert.c`、`gst_private.h`、`main.c`、`media_source.c`、`mfplat.c`、`quartz_parser.c`、`unix_private.h`、`unixlib.c`、`unixlib.h`、`video_decoder.c`、`video_processor.c`、`wg_format.c`、`wg_media_type.c`、`wg_parser.c`、`wg_sample.c`、`wg_transform.c`、`winegstreamer.rgs`、`winegstreamer.spec`、`winegstreamer_classes.idl`、`wm_reader.c`、`wma_decoder.c` | 大型整栈移植，伴随语义修正 [`99257f5e46eb15f14f123b7df8bb7d5652faa493`](https://github.com/as14725836/wine/commit/99257f5e46eb15f14f123b7df8bb7d5652faa493) 和许多后续修复；不可只摘一个看似新函数。 |
| No-GL media — [`e8835211d54ea04264d0539ed68d90a8e358a07d`](https://github.com/as14725836/wine/commit/e8835211d54ea04264d0539ed68d90a8e358a07d) | `dlls/winegstreamer/quartz_parser.c`、`wg_parser.c` | 已有媒体路径适配。 |
| Caps — [`3610a6237f75c9e324a9118ff038840b9e25597a`](https://github.com/as14725836/wine/commit/3610a6237f75c9e324a9118ff038840b9e25597a) | `dlls/winegstreamer/wg_format.c`、`wg_media_type.c` | 类型/caps 链适配。 |
| AAC DirectShow — [`1a441101d684c2e00e7a8b97e1ea3d9655b23164`](https://github.com/as14725836/wine/commit/1a441101d684c2e00e7a8b97e1ea3d9655b23164) | `dlls/winegstreamer/quartz_parser.c` | parser/后端耦合适配。 |
| I420 — [`50fae48f899aca3c065c695eeb8e50935150d359`](https://github.com/as14725836/wine/commit/50fae48f899aca3c065c695eeb8e50935150d359) | `dlls/quartz/vmr7.c`；`dlls/wined3d/surface.c`、`utils.c`；`include/wine/wined3d.h` | 跨 renderer/wined3d 的格式链。 |
| GL/HW disable — [`c7c443535b214c0012a6d1b2f3fe4502d0d35f63`](https://github.com/as14725836/wine/commit/c7c443535b214c0012a6d1b2f3fe4502d0d35f63) | `dlls/winegstreamer/wg_parser.c` | 兼容开关，非新增独立 API。 |

其余已筛查媒体能力/行为适配：AV1 [`eabeb15d486879e5fe19c132c0bf6794feb68cf7`](https://github.com/as14725836/wine/commit/eabeb15d486879e5fe19c132c0bf6794feb68cf7)；software decode [`574e5a1e9ad6707ced875bc8c8ec6f6adc272d58`](https://github.com/as14725836/wine/commit/574e5a1e9ad6707ced875bc8c8ec6f6adc272d58)；MPEG1 [`34e7f9d90f6c488cdef257f85181a2130a0d42b9`](https://github.com/as14725836/wine/commit/34e7f9d90f6c488cdef257f85181a2130a0d42b9)、[`f47cd1a6da8e9f3bcdaba7be0988da7965700cc4`](https://github.com/as14725836/wine/commit/f47cd1a6da8e9f3bcdaba7be0988da7965700cc4)；default stream/type [`82a845dafed74ed8de6d6515ae53cb6c98b0cac9`](https://github.com/as14725836/wine/commit/82a845dafed74ed8de6d6515ae53cb6c98b0cac9)。这些均不是本批选定功能的依赖。

### 6.4 EVR 窗口/GDI 系列

- [`c5374a7a10c74e106085ad786a3a35246ef628ad`](https://github.com/as14725836/wine/commit/c5374a7a10c74e106085ad786a3a35246ef628ad)：child window。
- [`e471e4c2c3fdd978af1f851cdf7897ef95f6e30d`](https://github.com/as14725836/wine/commit/e471e4c2c3fdd978af1f851cdf7897ef95f6e30d)：初始隐藏窗口。
- [`8d4055986f56e07cda9987cb4fc68f9c5f0252b0`](https://github.com/as14725836/wine/commit/8d4055986f56e07cda9987cb4fc68f9c5f0252b0)：GDI presentation。
- [`62b9f1ee3a6aeb9f4ad11ddd4d9aab972ce95ac2`](https://github.com/as14725836/wine/commit/62b9f1ee3a6aeb9f4ad11ddd4d9aab972ce95ac2)：gdi32 import。

存在多次恢复/回退和实验；该系列依赖审计没有完成。不随 `0e751b956e...` 的 sample 转发带入。

### 6.5 ARM64EC relay / ARM64X

| 提交/组 | 文件及关联 |
| --- | --- |
| [`a0859255e173a94f0c26852ea18316443ee60240`](https://github.com/as14725836/wine/commit/a0859255e173a94f0c26852ea18316443ee60240) | `dlls/ntdll/relay.c`、`signal_x86_64.c`；`tools/winebuild/spec32.c`。 |
| [`ef4774b55000beaffa344d28351d0abe485d9f62`](https://github.com/as14725836/wine/commit/ef4774b55000beaffa344d28351d0abe485d9f62) | ntdll relay 与 winebuild spec32 配合。 |
| [`74967350e16dc2f78f620dfb306672f2e22dbda6`](https://github.com/as14725836/wine/commit/74967350e16dc2f78f620dfb306672f2e22dbda6) | `dlls/ntdll/loader.c` 配合。 |
| [`185fe23b4aec648973876c13c34ef65f7679a625`](https://github.com/as14725836/wine/commit/185fe23b4aec648973876c13c34ef65f7679a625) | winebuild spec32 配合。 |
| [`8593f3db63224cdbba226b28327e0b7c6d7ecb49`](https://github.com/as14725836/wine/commit/8593f3db63224cdbba226b28327e0b7c6d7ecb49) | msvcrt trace exclusions。 |
| [`73cb684948b56f86c5598f93da169c37affa36a3`](https://github.com/as14725836/wine/commit/73cb684948b56f86c5598f93da169c37affa36a3) | ARM64X：`dlls/winecrt0/arm64ec.c`、`tools/winebuild/spec32.c`。 |
| [`3cbad03586aee04bae1b1d7df014641553503618`](https://github.com/as14725836/wine/commit/3cbad03586aee04bae1b1d7df014641553503618) | ARM64X loader：`dlls/ntdll/unix/loader.c`。 |

与 compiler/header 伴随、PE 入口和架构 ABI 共同审计；不作为本批小函数引入。

### 6.6 Esync / fsync

主要入口提交：[`54297ad3233a49c9108a292be8f01b95a0fc0c1a`](https://github.com/as14725836/wine/commit/54297ad3233a49c9108a292be8f01b95a0fc0c1a)、后续 [`55468a5564813d66147d36ac4fd864e63138af2e`](https://github.com/as14725836/wine/commit/55468a5564813d66147d36ac4fd864e63138af2e)。

已识别伴随：

- [`72921ba7d64e77b45ec5ca2f0c3ebbc5600f0d22`](https://github.com/as14725836/wine/commit/72921ba7d64e77b45ec5ca2f0c3ebbc5600f0d22)
- [`fe23607132eaff775982eff7fa783d33c2f185aa`](https://github.com/as14725836/wine/commit/fe23607132eaff775982eff7fa783d33c2f185aa)
- [`05d283e48e2bfe15fa1910a9d05b39fda03a136d`](https://github.com/as14725836/wine/commit/05d283e48e2bfe15fa1910a9d05b39fda03a136d)
- [`98668aa8a0badd4f64a94a30e443bcd8b29a6562`](https://github.com/as14725836/wine/commit/98668aa8a0badd4f64a94a30e443bcd8b29a6562)
- [`41b63763922b93c7290a0bc5ba3973b165664fd9`](https://github.com/as14725836/wine/commit/41b63763922b93c7290a0bc5ba3973b165664fd9)
- [`c94b15a8ed3459c03464ec999d5649afb1487499`](https://github.com/as14725836/wine/commit/c94b15a8ed3459c03464ec999d5649afb1487499)
- [`f29bbecaed654a4b9f69029fe1d147edbc6143f7`](https://github.com/as14725836/wine/commit/f29bbecaed654a4b9f69029fe1d147edbc6143f7)
- [`5ab4ce079b271027d96bb1810a97193a13d26a5c`](https://github.com/as14725836/wine/commit/5ab4ce079b271027d96bb1810a97193a13d26a5c)
- [`7effc5781e4ae355d53cf90a7c309bb01f36b9ec`](https://github.com/as14725836/wine/commit/7effc5781e4ae355d53cf90a7c309bb01f36b9ec)
- [`176004ea80b793f7270215ccf832772dcbbc4c09`](https://github.com/as14725836/wine/commit/176004ea80b793f7270215ccf832772dcbbc4c09)

涉及 ntdll/server/protocol/configure/TEB/shared-memory 的耦合实现。应先和目标 Proton 的既有等价实现比较，不能把这组全部当成目标新增功能；不随本批重复引入。

## 7. 补充 13 提交：标题、独立函数引入与本批依赖

以下 13 条均已读取实际补丁，而非仅根据标题分类。它们全部不是本批 WinMM + D3D11 getter + EVR sample 转发的源码或运行时依赖。

| 提交及原始标题 | 文件/规模 | 为什么属于或不属于独立函数引入 | 是否本批依赖 |
| --- | --- | --- | --- |
| [`35993b4eee7d930300865e3948fb7f353bb2407d`](https://github.com/as14725836/wine/commit/35993b4eee7d930300865e3948fb7f353bb2407d) — `opengl32: Preserve draw-buffer selections during default framebuffer resolve.` | `dlls/opengl32/unix_wgl.c`、`tests/opengl.c`；202 增、3 删 | 既有 `resolve_default_fbo` 的 MRT 状态保存/恢复与测试；仅在 resolve 目的本来就是当前 DRAW FBO 时保存完整选择，并防护缺少 glDrawBuffers/最大槽数。属于上游行为修复/适配，不是独立新能力。 | 否。仅是 d6 resolver 提交的历史父节点，与 WinMM 无源码关联。 |
| [`00457b3f9d85d7770880929ee7c47740e7c755b1`](https://github.com/as14725836/wine/commit/00457b3f9d85d7770880929ee7c47740e7c755b1) — `wined3d: Mark the buffer location valid after clearing a buffer UAV.` | `dlls/wined3d/view.c`；1 增 | 在现有 UAV clear 后补 `wined3d_buffer_validate_location(buffer, WINED3D_LOCATION_BUFFER)`，修复 location 状态；无新 API。 | 否。与下条 buffer-texture unsupported 路径相关，非本批依赖。 |
| [`3c0d1ae844812f94ec9f74a072e958b93136391c`](https://github.com/as14725836/wine/commit/3c0d1ae844812f94ec9f74a072e958b93136391c) — `wined3d: Don't add buffer views to the buffer object users list when buffer textures are unsupported.` | `dlls/wined3d/view.c`；25 增、13 删 | 把既有 `create_buffer_texture`/`create_buffer_view` helper 改为 bool，只在创建成功后链接 users，避免 NULL buffer object。内部合约修复，不是独立功能。 | 否。 |
| [`cf62ec3b56e5f9b9ece847c0bb815cd10afeac58`](https://github.com/as14725836/wine/commit/cf62ec3b56e5f9b9ece847c0bb815cd10afeac58) — `wined3d: Clip Vulkan clears to attachment bounds.` | `dlls/wined3d/texture_vk.c`、`dlls/d3d9/tests/visual.c`；42 增、5 删 | 既有 Vulkan clear 的 framebuffer/rectangle 边界裁剪和 oversized-viewport 测试；不是新接口或独立能力。 | 否。 |
| [`edac32d2be2e21660285fed04b898e1c6d1d0736`](https://github.com/as14725836/wine/commit/edac32d2be2e21660285fed04b898e1c6d1d0736) — `win32u: Always call window_surface_set_clip with a rect if there's a region.` | `dlls/win32u/dce.c`；3 增、1 删 | 非 NULL region 但零矩形时传 `&empty, 1`，修正既有 clip callback 的空区语义。 | 否。 |
| [`7f8e1348a9075f814ad46b35cb8acb8e5c902753`](https://github.com/as14725836/wine/commit/7f8e1348a9075f814ad46b35cb8acb8e5c902753) — `dwrite: Fix a leak on error path when creating EUDC collections.` | `dlls/dwrite/font.c`；3 增、1 删 | 分配失败路径补 `IDWriteFontFileStream_Release(stream)`，纯所有权泄漏修复。 | 否。 |
| [`64a124578125261d1bd724d96b3567101cb5bb6a`](https://github.com/as14725836/wine/commit/64a124578125261d1bd724d96b3567101cb5bb6a) — `dwrite/layout: Fix possible use-after-free on failure.` | `dlls/dwrite/layout.c`；2 增 | 失败释放后把 clustermetrics/clusters 置 NULL，生命周期修复。 | 否。 |
| [`94847fd9416933d94c371befde87a8971fc19a98`](https://github.com/as14725836/wine/commit/94847fd9416933d94c371befde87a8971fc19a98) — `winex11: Stop forcing a window background pixel color.` | `dlls/winex11.drv/window.c`；1 增、2 删 | 删除 background_pixel/CWBackPixel 以避免闪烁，保留分支透明输入处理；行为回退，不是新增函数能力。 | 否。 |
| [`b090bfb70a93c935bf03d9176ae44a6c38902cd6`](https://github.com/as14725836/wine/commit/b090bfb70a93c935bf03d9176ae44a6c38902cd6) — `win32u: Don't wait for the window's thread in FlashWindowEx().` | `dlls/win32u/window.c`、`dlls/user32/tests/win.c`；73 增、1 删 | 最小化窗口移除 RDW_UPDATENOW，增加跨线程测试；修复既有 API 阻塞。 | 否。 |
| [`2aa396ad124bb05c9da48fb6f6f88465d1d91e4b`](https://github.com/as14725836/wine/commit/2aa396ad124bb05c9da48fb6f6f88465d1d91e4b) — `ci: Keep D3D8, D3D9 and D3D11 regression executables.` | `.github/workflows/build.yml`；4 增、1 删 | 仅检查/上传 i386、x86_64 测试程序，编译但不运行 suites；不引入 Wine 运行时函数。 | 否。可独立借鉴 D3D11 artifact 保留，但不是 getter 的源码或运行依赖。 |
| [`710f15c8375b9858881108ef78b7ab5b694ef1fd`](https://github.com/as14725836/wine/commit/710f15c8375b9858881108ef78b7ab5b694ef1fd) — `d3d9/tests: Exercise shader reuse across device resets.` | `dlls/d3d9/tests/visual.c`；128 增、2 删 | 仅 shader-reset 回归覆盖，含 backbuffer release/reacquire 失败处理；无生产功能。 | 否。与下条 Reset 修复相关。 |
| [`05fd3dfb755b80a49622dccdf5bdebbaf67ad138`](https://github.com/as14725836/wine/commit/05fd3dfb755b80a49622dccdf5bdebbaf67ad138) — `wined3d: Don't tear down 3D state on device reset.` | `dlls/wined3d/device.c`；1 增、20 删 | Reset 改为 invalidate state，避免卸载资源/销毁仍使用的 shader backend；既有生命周期修复。 | 否。 |
| [`e1c00841a18e04ca8deb269355b863fdcdf0246f`](https://github.com/as14725836/wine/commit/e1c00841a18e04ca8deb269355b863fdcdf0246f) — `wined3d: Remove cached Vulkan graphics pipelines when destroying shader modules.` | `dlls/wined3d/context_vk.c`、`shader_spirv.c`、`wined3d_vk.h`；39 增 | 确实新增内部 `wined3d_graphics_pipeline_vk_uses_module` 与 `wined3d_context_vk_remove_graphics_pipelines`，但仅为销毁 shader module 时失效 pipeline 缓存，防止句柄复用命中旧 pipeline。属于普通缓存生命周期修复，不是独立 API 能力。 | 否。 |

## 8. 其余普通修复、同步和测试排除项

已筛查但未作为独立函数引入纳入的例子：

| 类别 | 提交/结论 |
| --- | --- |
| ddraw 普通修复/同步 | [`f2fdca818ccae0c3a0288808289423dd03637c06`](https://github.com/as14725836/wine/commit/f2fdca818ccae0c3a0288808289423dd03637c06)。 |
| wineps 普通修复/同步 | [`d9f35238c9357df642494d40c04972dcfe3356aa`](https://github.com/as14725836/wine/commit/d9f35238c9357df642494d40c04972dcfe3356aa)。 |
| dbghelp 普通修复/同步 | [`b55f34f7776625b1bf6eb9ec8b70f448cf2471b5`](https://github.com/as14725836/wine/commit/b55f34f7776625b1bf6eb9ec8b70f448cf2471b5)。 |
| MF topology、intsafe/build 伴随 | [`3a2f68d609620759e1cbc327bd88f7ae7c9c1351`](https://github.com/as14725836/wine/commit/3a2f68d609620759e1cbc327bd88f7ae7c9c1351) 等，既有路径修复/构建配合。 |
| MF 测试和 request 修复 | 已筛查的 `0028359...`、`1cd8c502...` 测试及 `befbf3f...` request 修复；此处保留元数据中的短识别前缀，不补造完整 SHA。 |
| 诊断、bounded waits、回退实验 | bounded waits、诊断输出、已回退 GL tracker/glFinish/EVR deferral 等；不是在审计 pin 上可单独交付的新增函数能力。 |

本节不是把其余所有提交逐条安全审计通过的声明。391 条的数字描述元数据筛查范围；需要逐行验证的大型系列已经明确留出。

## 9. 固定证据索引

### 9.1 来源提交与补丁

上文来源提交的完整 SHA 均链接到源仓库的不可变 commit 页面，可查看文件列表和 diff。原始审计入口为 [`8160abdb31761c904e8ecaefa39f06765952f970`](https://github.com/as14725836/wine/commit/8160abdb31761c904e8ecaefa39f06765952f970)；后续 MCI 修正为 [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30)。原记录仅保留前缀的 `0028359...`、`1cd8c502...`、`befbf3f...` 仅用于识别候选，未补造完整哈希，也不作为本批纳入依据。

六个来源提交映射到三份补丁的边界见第 1 节；实际交付文件、顺序、校验值及维护方式见 [补丁集 README](../patches/dwproton-functions/README.md)、[series](../patches/dwproton-functions/series) 和 [SHA256SUMS](../patches/dwproton-functions/SHA256SUMS)。补丁适配后的代码以仓库产物为准，不能把原始源 pin 与整合后的 WinMM 清理实现混为一谈。

### 9.2 原始源 pin 的定点证据

以下链接固定到原始审计 pin，故 MCI 项展示的是需要后续修正的原实现：

| 证据 | 固定源位置 |
| --- | --- |
| callback 数据结构、`mmDrvInstall`、两个排除的 callback 入口 | [driver.c 500–649](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/driver.c#L500-L649)；其中 `mmDrvInstall` 位于 545–553、`NotifyCallbackData` 位于 565–573、`WOW32DriverCallback` 位于 583–614。 |
| resolver、原 AppExit、legacy message 入口 | [winmm.c 195–285](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/winmm.c#L195-L285)；resolver 位于 195–205、原 AppExit 位于 210–225。 |
| timer task 清理及 kill | [time.c 293–339](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/time.c#L293-L339)；creator 字段和创建赋值分别见 [44 附近](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/time.c#L38-L49)、[275 附近](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/time.c#L266-L280)。 |
| 原 MCI task 清理 | [mci.c 83–119](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/mci.c#L83-L119)。 |
| MCI 卸载、creator 记录和 dispatcher 检查 | [mci.c 770–795](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/mci.c#L770-L795)、[829–842](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/mci.c#L829-L842)、[893–905](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/mci.c#L893-L905)。 |
| 原公开 MCI_Close 检查 | [mci.c 1836–1875](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/mci.c#L1836-L1875)。 |
| 原 WinMM 回归覆盖边界 | [tests/winmm.c 27–178](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/tests/winmm.c#L27-L178)（resolver、legacy message、`mmDrvInstall`、worker timer）；[208–311](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/winmm/tests/winmm.c#L208-L311)（原 AppExit 测试）。 |
| MFPlay 公开接口与被拒绝的非标准插槽 | [mfplay.idl 270–364](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/include/mfplay.idl#L270-L364)、[player.c 1837–1855](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/mfplay/player.c#L1837-L1855)。 |
| HTTP factory 与 GUID 使用点 | [network.c 1925 附近](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/mfplat/network.c#L1920-L1940)、[1225 附近](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/dlls/mfplat/network.c#L1218-L1232)、[mfidl.idl 1631 附近](https://github.com/as14725836/wine/blob/8160abdb31761c904e8ecaefa39f06765952f970/include/mfidl.idl#L1626-L1636)。 |

上述 MCI creator 记录链接固定到同一原始 pin；已发布修正请单独查看 [`df3e063cd10d98a007c33312acf4dda684a6be30`](https://github.com/as14725836/wine/commit/df3e063cd10d98a007c33312acf4dda684a6be30) 的 `dlls/winmm/mci.c` 与 `dlls/winmm/tests/winmm.c` diff。修正加入的内部 helper 和 worker-MCI 用例不得反向归入原始 pin。

目标基线的定点源码链接见第 4.2 节。第 6 节大型功能系列的状态只代表已识别的组件及审计边界，不是所有实现和目标等价性的完整证明。

## 10. 顺序应用验证与工作流边界

### 10.1 已完成的整合检查

在由目标 `proton_11.0` 固定提交 [`e6a370ff7db61c230df94996f00131e22f9165cf`](https://github.com/WinNative-Emu/proton-wine/commit/e6a370ff7db61c230df94996f00131e22f9165cf) 文件组成的全新独立工作树中，按 [series](../patches/dwproton-functions/series) 顺序逐份执行 `git apply --check --verbose --whitespace=error-all`，随后实际执行 `git apply`，再检查下一份补丁。三份补丁均完成检查和实际应用，最终 `git diff --check` 通过，没有冲突。

D3D11 补丁的实现 hunk 出现 `-1` 行偏移，测试 hunk 出现 `+8` 行偏移；二者均成功定位并应用。偏移是该固定基线的已观察结果，不能推广到其他目标提交。

补丁、`series` 的 SHA256 校验，以及工作流、文档和清单的 `git diff --check` 均已通过；补丁应用后的源码空白检查见上文。工作流静态检查使用 actionlint v1.7.12 并通过，因未安装 shellcheck/pyflakes，相关外部检查未启用。当前补丁集标识 `SHA256(SHA256SUMS)` 为 `e533e370def996b7cc61604018387df6790c6a7f6c9f5c7f63f89984ae8b1496`。

这次检查证明补丁能按指定顺序应用到该文件基线，并通过相应空白检查。它不证明编译、链接、ABI 的动态行为、测试断言、设备兼容性或远程构建成功。没有进行本地编译、语法编译、Wine 运行或测试。远程 CI 状态仍待对应 GitHub Actions run、日志和产物确认。

### 10.2 工作流中的复现和身份记录

[Wine 工作流](../.github/workflows/wine.yml)仅在 `wine_branch=proton` 时应用该补丁集；其他源码类型记录为 `not-applicable`。源码获取后、子模块及 `autogen.sh` 前：

1. 通过 `sha256sum --check --strict SHA256SUMS` 校验三份补丁和 `series`；补丁集标识为 `SHA256(SHA256SUMS)`。
2. 按 `series` 逐份执行 `git apply --check --whitespace=error-all`，再执行实际 `git apply --whitespace=error-all`。
3. 执行 `git diff --check`。任一步失败即终止，不跳过冲突，也不把“似乎已应用”当成成功。
4. 为产物和 Release 名追加 `-fn<补丁集 SHA256 前 12 位>`，并记录完整补丁集标识、源码提交、审查基线和应用状态。

`proton_commit` 留空会跟随移动 HEAD；填写固定目标 pin 才能复现本次目标选择。目标提交不同会警告，且仍须通过全部应用检查。维护时修改补丁须更新校验值；修改顺序须同步更新 `series` 及其校验值。本报告的文本应用检查不是一次真实 GitHub Actions 构建通过记录。

## 11. 最终限制声明

本报告为源码审阅、窄范围补丁选取及固定基线文本应用记录。纳入补丁携带的测试尚未执行；跨线程清理、视频解码、EVR 实际播放及不同架构仍需真实构建和运行时验证。

原始五个入选提交与后续 MCI 修正共六个来源提交，整理为三份补丁。排除、延期和待审计项保留在此，供后续维护按明确边界继续核对，不能因列出名称或存在 diff 就解释为支持或验证完成。
