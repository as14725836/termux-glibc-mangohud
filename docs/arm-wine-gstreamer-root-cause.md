# ARM wine 解码失败 (hr 0x8007000e) 根因与修复记录

> 适用仓库：`as14725836/termux-glibc-mangohud`（构建 ARM64 WOW64 Wine / Termux glibc 版）

## 症状

- 游戏内 quartz / MF 解码全部失败：

  ```
  err:quartz:autoplug Failed to create filter for L"Wave Parser", hr 0x8007000e
  fixme:ole:CoCreateInstanceEx no instance created for ...
  fixme:mfplat:MFInitMediaTypeFromAMMediaType Unsupported major type {e436eb83-...}
  ```

- 即使打开 `GST_DEBUG`，**GStreamer 一行日志都没有**
- 所有失败的 CLSID 最终都指向 `winegstreamer`
  （`{f9d8d64e}`= decodebin parser、`{a8edbf98}`= MPEG-I splitter、`{272bfbfb}`= AVI splitter …）

## 根因（已实测确认）

1. `lib/wine/aarch64-unix/winegstreamer.so` 的 NEEDED 里多了一个 **`libgstgl-1.0.so.0`**
   —— Proton / pipetto 树带 GstGL 互操作（`gl_display`、`glupload`、GL context）；
   `AndreRH/wine@3ea3a14` 那份**没有**，所以它能在同样的设备上正常解码。
2. `libgstgl` 自身还要解析 `libEGL` / `libGL` / `libwayland` / `libX11`，
   在 Termux(Android) 上极易断链 → **`dlopen(winegstreamer.so)` 失败**。
   （`gst-inspect` 不会加载 `libgstopengl.so`，所以查“gst 库是否缺”时看不到这条断链。）
3. unix 侧于是**一行都不执行**（这就是 `GST_DEBUG` 无输出的原因）；
   而 PE 侧 `dlls/winegstreamer/main.c` 的 `init_gstreamer()` **永远 `return TRUE`**，
   把真实错误彻底吞掉。
4. 最终 quartz / MF 全部报 `hr 0x8007000e`（E_OUTOFMEMORY），
   把真正的 `.so` 加载失败掩盖了。

## 修复

workflow 步骤 **“去掉 winegstreamer 的 GstGL 依赖 (对齐 AndreRH)”**：

- `configure.ac`：GSTREAMER pkg 列表去掉 `gstreamer-gl-1.0`
- `unixlib.c` / `wg_parser.c`：把 `#include <gst/gl/gl.h>` 换成**宏垫片**

  ```c
  typedef struct _GstGLDisplay GstGLDisplay;
  typedef struct _GstGLContext GstGLContext;
  #define gst_gl_display_new() (NULL)
  #define gst_gl_display_create_context(d, c, o, e) (0)
  #define gst_gl_display_add_context(d, c) ((void)0)
  #define GST_GL_DISPLAY_CONTEXT_TYPE "gst.gl.GLDisplay"
  #define gst_context_set_gl_display(c, d) ((void)0)
  ```

  → 源码内**零 libgstgl 符号引用**，`use_opengl` 恒为 FALSE
  （不再需要 `glupload` / `glcolorconvert` 元素）。
  CI 里还带一道自检：所有 `gst_gl_*` 符号与 `GstGL*` 类型必须被垫片覆盖，否则直接失败。

修复后 `winegstreamer.so` 的依赖面与 `AndreRH/wine@3ea3a14` 一致：

```
NEEDED: ntdll.so libgstvideo libgstaudio libgstbase libgsttag
        libgstreamer libgobject libglib libc.so.6      # 无 libgstgl
RUNPATH: /data/data/com.termux/files/usr/glibc/lib
```

## 验证结果

- CI 断言：`OK: winegstreamer.so 已无 libgstgl 依赖`
- 设备实测：**ARM wine 解码恢复正常**（pipetto-proton9 与 proton11 两个包均已通过）

## 同一轮的附带修复

| 项 | 说明 |
|---|---|
| **PE 侧打点** | `unix_wg_init_gstreamer FAILED rc=0x…` / `unix_wg_parser_create FAILED rc=0x…`，绕开 `init_gstreamer()` 的吞错，出错时直接给出真实返回码（`0xc0000135` = `.so` 没加载到） |
| **gnutls / schannel** | 安装 `libgnutls28-dev:arm64` + `libgcrypt20-dev:arm64`；断言改为查**内嵌 soname**（bcrypt / secur32 都是运行时 `dlopen` 加载 gnutls，NEEDED 里本来就没有它，用 `strings -a … > 临时文件` 再 grep，避开 `pipefail` + SIGPIPE 的假失败） |
| **wg_task_pool 兜底** | `wg_task_pool_new()` 失败时退回 `gst_task_pool_new()`（宿主 GStreamer/GLib 与构建头文件版本不一致时 GType 注册可能失败） |
| **RUNTIME_DEPS.txt** | 随包发布：列出每个 `aarch64-unix/*.so` 的 NEEDED，以及**通过 dlopen 加载的宿主库**（如 bcrypt 需要 `libgnutls.so.30`），方便设备端核对 |
