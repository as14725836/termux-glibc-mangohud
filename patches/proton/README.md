# Valve Proton Wine source support

The [termux-glibc Wine workflow](../../.github/workflows/termux-glibc-wine.yml)
can build the Wine component pinned by
[ValveSoftware/Proton](https://github.com/ValveSoftware/Proton/tree/experimental_11.0).
It retains the existing Termux x86_64 Unix / i386 + x86_64 Windows WoW64 build,
patches, multimedia dependencies and packaging. On ARM devices, this x86_64
package uses the existing box64 runtime setup.

## Run a build

Open Actions → **termux-glibc Wine and Proton** → **Run workflow** and select:

| Input | Value |
| --- | --- |
| `build_type` | `proton` |
| `proton_repo` | `ValveSoftware/Proton` |
| `proton_branch` | `experimental_11.0` |

Other inputs retain their existing defaults. The default source repository
remains `WinNative-Emu/proton-wine`; its build path and other direct Wine source
repositories remain available.

## Source preparation

[prepare_valve_wine.sh](prepare_valve_wine.sh) shallow-clones the selected
Proton branch, then initializes only its `wine` submodule. It checks that the
Wine checkout matches the superproject's recorded gitlink. It does not select
a separately moving branch from `ValveSoftware/wine`.

The build runs from that nested Wine directory. Wine's own `autogen.sh`
regenerates `configure`, `include/config.h.in`, request/spec files and Vulkan
sources using Wine's tracked registry XML files. The remaining compilation,
Termux compatibility patches and packaging use the existing workflow. The old
DWProton workaround that disables `inproc_sync` is skipped for Valve sources,
where that code also implements the fsync fallback.

Valve builds have separate artifact/archive and Release names:

- Archive/artifact: `Proton-valve-experimental_11.0-WoW64`
- Release tag: `proton-valve-experimental_11.0-wow64`

The package's `BUILD_INFO.txt`, job summary and Release description record the
Proton repository/branch/commit, actual Wine commit, and workflow run. Branches
can move between runs; these full commit IDs identify each build's inputs.

## Scope

This produces the Wine component with Termux patches. A complete Steam Proton
distribution also builds the launcher, Steam Runtime integration, DXVK,
vkd3d-proton and other components; those are outside this workflow's build
scope. Remote CI validates compilation and packaging. Device runtime and game
compatibility still require testing on the intended Termux setup.
