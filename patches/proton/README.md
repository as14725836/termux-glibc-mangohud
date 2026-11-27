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

### Optional DWProton Termux integration

The workflow input `apply_dwproton_termux` defaults to `false`. Enable it only
with `proton_repo=ValveSoftware/Proton`; the workflow rejects this integration
for every other source repository. For example:

| Input | Value |
| --- | --- |
| `build_type` | `proton` |
| `proton_repo` | `ValveSoftware/Proton` |
| `proton_branch` | `experimental_11.0` |
| `apply_dwproton_termux` | `true` |

The workflow uses [the DWProton helper](../dwproton/apply.sh) to apply the generic
Termux patches in this order:

1. `03-tgmux-shm-path.patch` is required.
2. `02-fsync.patch` is optional: both server and client fsync source files must
   be present and the complete patch must fit. Missing or incompatible sources
   produce an explicit skip, leaving the existing fsync files unchanged and
   without this Termux fsync path adaptation. A skip does not verify that the
   original client/server implementations are compatible; a detected partial
   application is an error.
3. `05-tgmux-integration.patch` is required.

The helper skips `01-esync.patch` and `04-esync-integration.patch`. It preserves
native Valve fsync/ntsync implementations, adapting fsync paths only when
compatible. No esync backport is applied, and this integration does not
establish esync runtime support. Required patch failures stop the workflow
before packaging or publication. See [the DWProton patch notes](../dwproton/README.md)
for the full application policy and limitations.

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
where that code also implements the fsync fallback. This preserves Valve's
native fsync/ntsync implementation whether the optional integration is enabled
or disabled.

Valve builds use separate names from other source repositories. For
`experimental_11.0`, the stable names remain unchanged when
`apply_dwproton_termux=false`; enabled builds use an isolated `-dwtermux` suffix:

| Output | Default (`false`) | Enabled (`true`) |
| --- | --- | --- |
| Artifact / package directory | `Proton-valve-experimental_11.0-WoW64` | `Proton-valve-experimental_11.0-WoW64-dwtermux` |
| Archive | `Proton-valve-experimental_11.0-WoW64.tar.xz` | `Proton-valve-experimental_11.0-WoW64-dwtermux.tar.xz` |
| Release tag | `proton-valve-experimental_11.0-wow64` | `proton-valve-experimental_11.0-wow64-dwtermux` |

The Release title also uses the artifact/package name, so enabled builds remain
separate from the stable Release.

The package's `BUILD_INFO.txt`, GitHub Actions job summary and Release
description record the Proton repository/branch/commit and actual Wine commit,
plus the Termux integration status, fsync and esync status, and patchset SHA256.
The hash covers the helper, final-source verifier, patches `02/03/05`, and the
WoW64 host guard used by the workflow. An esync status of `skipped` records that
`01/04` were not applied; it is not evidence of runtime esync support.
`BUILD_INFO.txt` also identifies the workflow commit and run. Branches can move
between runs; the full source commit IDs and patchset hash identify each build's
inputs.

After all source injectors and before configure, enabled builds verify that the
required edits, shared headers and complete one-argument loader host guard remain
present, and reject the legacy ntsync-disabling marker. This static text check
allows the workflow's normal path substitutions and insertions; it does not
replace compilation or runtime validation. The package includes
`DWPROTON_SOURCE_SHA256SUMS` for the checked source files, including the loader.
Build information, the job summary and Release description also record the final
verification status and that manifest's SHA256.

## Scope

The workflow builds the Wine component with Termux patches. A complete Steam
Proton distribution also builds the launcher, Steam Runtime integration, DXVK,
vkd3d-proton and other components; those are outside this workflow's build
scope. The documented integration still requires a remote CI run to validate
compilation and packaging, followed by device runtime and game compatibility
testing on the intended Termux setup.
