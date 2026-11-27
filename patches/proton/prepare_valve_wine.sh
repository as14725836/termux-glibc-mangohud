#!/usr/bin/env bash
# Prepare Valve Proton's pinned Wine sources; do not configure or compile here.
# Usage: prepare_valve_wine.sh <Proton branch> <new absolute checkout directory>
set -euo pipefail

BRANCH="${1:?Usage: prepare_valve_wine.sh <branch> <checkout directory>}"
DEST="${2:?Usage: prepare_valve_wine.sh <branch> <checkout directory>}"

fail() { echo "[valve-wine] ERROR: $*" >&2; exit 1; }
git check-ref-format --branch "$BRANCH" >/dev/null || fail "Invalid branch: $BRANCH"
[[ "$DEST" = /* ]] || fail "Checkout directory must be absolute"
[[ ! -e "$DEST" && ! -L "$DEST" ]] || fail "Checkout directory already exists: $DEST"

# Proton is a superproject, not a Wine source tree. Fetch only its pinned
# Wine submodule, not DXVK, FEX or the Steam runtime.
git clone --depth 1 --filter=blob:none --sparse --branch "$BRANCH" \
    https://github.com/ValveSoftware/Proton.git "$DEST"
# wine is a gitlink rather than a regular directory in the superproject index.
git -C "$DEST" sparse-checkout set --skip-checks wine
git -C "$DEST" submodule update --init --depth 1 -- wine

# Do not follow Wine's moving branch: use exactly the gitlink recorded by
# the selected Proton commit and fail if the submodule checkout differs.
expected="$(git -C "$DEST" rev-parse HEAD:wine)"
actual="$(git -C "$DEST/wine" rev-parse HEAD)"
[[ "$actual" = "$expected" ]] || fail "Wine does not match Proton's gitlink"
echo "[valve-wine] Wine commit: $actual"

WINE_SOURCE="$DEST/wine"
[[ -f "$WINE_SOURCE/configure.ac" && -f "$WINE_SOURCE/server/Makefile.in" ]] \
    || fail "The pinned wine submodule is not a Wine source tree"
[[ -x "$WINE_SOURCE/autogen.sh" ]] || fail "The pinned Wine source lacks autogen.sh"

# Valve does not track configure or include/config.h.in. The caller must run
# this Wine tree's autogen.sh after its local patches. Wine already tracks the
# Vulkan registry XML inputs under dlls/winevulkan; no extra submodule is needed.

echo "[valve-wine] Proton branch: $BRANCH"
echo "[valve-wine] Proton commit: $(git -C "$DEST" rev-parse HEAD)"
echo "[valve-wine] Wine source: $WINE_SOURCE"
