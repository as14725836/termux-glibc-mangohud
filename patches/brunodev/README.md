# brunodev85/wine-10.10-custom 通用优化补丁

本目录把 `brunodev85/wine-10.10-custom`（基于 wine-10.10 的 Winlator 定制版）里
**不属于 Winlator 路径专属**的优化/修复补丁抽出来，供 termux-glibc-wine.yml 在构建时套用。

## 收录（22 个）

| commit | 内容 | 类别 |
|---|---|---|
| `960ce2e9` | ntdll: apply Syscall_Emulation patch (signal_x86_64.c) | 优化/兼容 |
| `0ccee81f` | ntdll: esync + server 对象存在时强制 STATUS_SUCCESS | 稳定性 |
| `251b32d2` | ntdll: 新增 WINEVMEMMAXSIZE 环境变量（限制虚拟内存分配） | ARM64/VA |
| `e800c38a` | ntdll: 新增 WINEOVERRIDEAFFINITYMASK（覆盖进程亲和性） | 性能 |
| `53e19a40` | ntdll: 新增 WINEENV（给目标程序追加环境变量） | 启动器友好 |
| `31d5181b` | ntdll: 新增 WINEARGS（给目标程序追加参数） | 启动器友好 |
| `9450b936` | loader: 新增 WINPREEXEC（启动前执行） | 启动器友好 |
| `e5733cea` | ntdll: 新增 WINVERSION（改 Windows 版本） | 启动器友好 |
| `dcad80e8` | mfplat: 新增 WINE_DO_NOT_CREATE_DXGI_DEVICE_MANAGER | 稳定性 |
| `edaebb86` | winex11: 线程数据 NULL 检查 | 稳定性 |
| `f7c7cecd` | mf: audio client NULL 检查 | 稳定性 |
| `61fe8ba9` | dbghelp: 校验进程句柄 | 稳定性 |
| `08c8029e` | explorer: 修复 nogui 选项 | 无桌面/Android |
| `7005b80d` | explorer: 新增 nogui 选项 | 无桌面/Android |
| `14b3e568` | win32u: 不重复启动 explorer | 无桌面/Android |
| `0ac5265d` | win32u: 显示模式切换强制 CDS_FULLSCREEN | 全屏 |
| `a2c3753b` | mscoree: Mono 未装时弹安装器 | 体验 |
| `e304bb7e` | appwiz: Mono/Gecko 安装地址回退 | 体验 |
| `82efd39c` | winemenubuilder: 等待父进程加超时 | 稳定性 |
| `fa63d539` | winebrowser: 始终用 win32 程序打开 | Android/无桌面 |
| `82078144` | winex11: 默认不启用附加扩展 | 性能 |
| `2b9afc38` | winex11: 实现鼠标 Raw Button 事件 | 输入 |

## 排除（Winlator 专属或有风险）

| commit | 原因 |
|---|---|
| `aa9e6c2c` | Winlator 专属：改成 winlator rootfs 路径 |
| `b508ec51` | Winlator 专属：从文件读网卡地址（含 winlator 路径） |
| `59b6143d` | Winlator 专属：MIDI 走 socket（配 Winlator 客户端） |
| `c507e3fa` | Winlator 专属：winebus 的 Winlator 总线 |
| `7463c7fa` | 补丁内含垃圾文件（output.0/output.1/requests 等），3.3MB |
| `494cf8f4` | 上游补丁为空（9 字节） |
| `a8559d70` | 移除默认 32 位 loader，对 WoW64 构建有风险 |
| `2942ddeb` | 移除 XKeyboard 扩展，可能影响键盘布局 |
| `252b6cdc` | 为启动器加窗口属性（Winlator 侧读取），非必要 |
| `133e418d` | 为启动器加 GPU 信息窗口属性，非必要 |

## 应用方式
workflow 在克隆 wine 源码后调用 `apply.py <源码目录>`：
先用 `git apply -p1 --3way`，失败再试 `patch -p1 --forward`，都不行则跳过并打日志；
不会因个别补丁不适用而中断构建（结果见构建日志 + `/tmp/brunodev-patch-report.txt`）。
