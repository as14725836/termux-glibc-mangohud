# 致谢 / Credits

本仓库（`as14725836/termux-glibc-mangohud`）的构建脚本、补丁与产物，建立在下面这些上游项目之上。
代码与补丁的著作权归各原作者所有；本仓库只做 Termux/glibc + ARM64(EC)/WoW64 场景的适配与集成。

## Wine / Proton 及其分支

| 项目 | 用途 | 许可 |
|---|---|---|
| [WineHQ/wine](https://github.com/wine-mirror/wine) | Wine 上游（`wine.yml` 的 staging / winearm64ec 源、各类补丁基线）| LGPL-2.1-or-later |
| [Valve 的 Proton](https://github.com/ValveSoftware/Proton) | Proton 源码血统 | LGPL-2.1-or-later |
| [WinNative-Emu/proton-wine](https://github.com/WinNative-Emu/proton-wine) | `proton_repo` 默认源（`proton_10.0` / `proton_11.0`）| LGPL-2.1-or-later |
| [GameNative/proton-wine](https://github.com/GameNative/proton-wine) | `proton_repo` 可选源（`proton_11.0-2`、`bleeding-edge` 等）| LGPL-2.1-or-later |
| [Pipetto-crypto/wine](https://github.com/Pipetto-crypto/wine) | `proton_repo` 可选源（`proton-9.0-arm64ec` 等 ARM64EC 分支）| LGPL-2.1-or-later |
| [The412Banner/proton-wine](https://github.com/The412Banner/proton-wine) | `wine_branch=proton-10.34-GE` 源 | LGPL-2.1-or-later |
| [brunodev85/wine-10.10-custom](https://github.com/brunodev85/wine-10.10-custom) | `proton_repo` 可选源；其**通用优化补丁**被抽取进 `patches/brunodev/` | LGPL-2.1-or-later |
| [brunodev85 / Winlator](https://github.com/brunodev85/winlator) | 上述 wine 定制的上游项目（Android 端 Wine 容器方案）| GPL-3.0 / 见项目 |

## 模拟器与工具链

| 项目 | 用途 | 许可 |
|---|---|---|
| [ptitSeb/box64](https://github.com/ptitSeb/box64) | `wowbox64.dll`、`box64ec.dll` 与 box64 兼容补丁（`wine-box64-compat.patch`、`wine-box64-noexec.patch`）| MIT |
| [FEX-Emu/FEX](https://github.com/FEX-Emu/FEX) | `libarm64ecfex.dll` / `libwow64fex.dll`（`fex.yml`）| MIT |
| [AndreRH/Hangover](https://github.com/AndreRH/hangover) | ARM64EC/WoW64 思路与 `fex.yml` 参考 | 见项目 |
| [mstorsjo/llvm-mingw](https://github.com/mstorsjo/llvm-mingw) · [bylaws/llvm-mingw](https://github.com/bylaws/llvm-mingw) | 交叉工具链（含 arm64ec 支持）| Apache-2.0 WITH LLVM-exception |
| [Termux](https://github.com/termux) | glibc 运行环境与打包约定 | 见项目 |

## 本仓库自行维护的部分

| 内容 | 说明 |
|---|---|
| `wine.yml` 的 39-bit VA 适配 | `enable_39bit_va`：收窄地址上限与高地址区，适配仅 39 位 VA 的 ARM64 设备 |
| `wine.yml` 的 noexec 兜底 | `enable_noexec_fallback`：只读可执行映射遇 noexec 分区时回退 `read()` |
| `wine-box64-compat.patch` | 识别 box64/box86/FEX/qemu 环境并收敛地址空间 limit |
| `wine-box64-noexec.patch` | noexec 分区下的映射放宽（仅模拟器环境、仅只读映射）|
| `patches/brunodev/` | 从 `brunodev85/wine-10.10-custom` 抽取的非 Winlator 专属通用优化补丁（22 个，附来源 sha 与说明）|
| `patches/brunodev/apply.py` | 补丁应用器：strict/auto 模式、冲突标记回滚、`present` 检测 |
| `fex.yml` 的 wowbox64.dll 集成 | 打包时把 box64 的 `wowbox64.dll` 与 FEX 两个 dll 并入同一目录 |

## 免责与说明

- 本仓库产出的包仅供**个人测试**使用；各上游项目的授权条款以其仓库为准，转载/再分发请遵循对应许可。
- 若你是上述任一项目的作者并希望调整署名方式或移除某些内容，提 issue 即可，我会配合修改。
