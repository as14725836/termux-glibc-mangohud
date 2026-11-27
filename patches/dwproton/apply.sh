#!/usr/bin/env bash
# Apply Termux integration while preserving the source tree's sync backends.
set -euo pipefail

usage() {
    echo "Usage: bash $0 [--check] <wine-source-directory>"
    echo "Preserves existing synchronization; never applies 01/04 esync backports."
}

check_only=0
if [ "${1:-}" = "--check" ]; then
    check_only=1
    shift
fi
if [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi
if [ "$#" -ne 1 ]; then
    usage >&2
    exit 1
fi

patch_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source_dir="$(cd -- "$1" && pwd -P)"
if [ ! -d "$source_dir/server" ] || [ ! -d "$source_dir/dlls/ntdll/unix" ]; then
    echo "ERROR: not a Wine source directory: $source_dir" >&2
    exit 1
fi
if [ "$(git -C "$source_dir" rev-parse --show-toplevel)" != "$source_dir" ]; then
    echo "ERROR: source directory must be the root of its Git working tree" >&2
    exit 1
fi

pending=()
applied_count=0
already_count=0

# Queue a complete patch or recognize it as already applied. A failed required
# preflight returns before ANY patch is written. Never reset user changes.
queue_patch() {
    local name="$1" optional="${2:-0}"
    local patch="$patch_dir/$name"
    if [ ! -f "$patch" ]; then
        echo "ERROR: missing patch: $patch" >&2
        return 1
    fi
    if git -C "$source_dir" apply --reverse --check "$patch" >/dev/null 2>&1; then
        echo "ALREADY: $name"
        already_count=$((already_count + 1))
    elif git -C "$source_dir" apply --check --whitespace=error-all "$patch" >/dev/null 2>&1; then
        pending+=("$patch")
        echo "READY: $name"
    elif [ "$optional" = 1 ]; then
        echo "SKIP: $name is incompatible; both fsync files unchanged (existing pairing not verified)"
    else
        echo "ERROR: $name is incompatible or partially applied; source unchanged" >&2
        git -C "$source_dir" apply --check --whitespace=error-all "$patch" >&2
        return 1
    fi
}

echo "SKIP: 01-esync.patch / 04-esync-integration.patch; preserving existing sync backends"
# Headers must precede their consumers. The fsync patch changes the backing-file
# name and location on BOTH sides and is always checked/applied as one unit.
queue_patch 03-tgmux-shm-path.patch
fsync_patch="$patch_dir/02-fsync.patch"
if [ ! -f "$fsync_patch" ]; then
    echo "ERROR: missing patch: $fsync_patch" >&2
    exit 1
fi
# A known half-applied backing-file policy is not an ordinary optional mismatch:
# it can leave client and server opening different files. Refuse before writes.
fsync_applied_sides=0
for path in server/fsync.c dlls/ntdll/unix/fsync.c; do
    if [ -f "$source_dir/$path" ] && git -C "$source_dir" apply --reverse --check --include="$path" "$fsync_patch" >/dev/null 2>&1; then
        fsync_applied_sides=$((fsync_applied_sides + 1))
    fi
done
if [ "$fsync_applied_sides" -eq 1 ]; then
    echo "ERROR: 02-fsync.patch is applied on only one side; source unchanged" >&2
    exit 1
fi
fsync_status=skipped-missing
if [ -f "$source_dir/server/fsync.c" ] && [ -f "$source_dir/dlls/ntdll/unix/fsync.c" ]; then
    fsync_pending_before=${#pending[@]}
    queue_patch 02-fsync.patch 1
    if [ "$fsync_applied_sides" -eq 2 ]; then
        fsync_status=already-applied
    elif [ "${#pending[@]}" -gt "$fsync_pending_before" ]; then
        fsync_status=applied
    else
        fsync_status=skipped-incompatible
    fi
else
    echo "SKIP: 02-fsync.patch; fsync sources are not present on both sides"
fi
# Keep server/request.c and the client server.c directory policy together, too.
queue_patch 05-tgmux-integration.patch

if [ "${#pending[@]}" -gt 0 ]; then
    git -C "$source_dir" apply --check --whitespace=error-all "${pending[@]}"
    if [ "$check_only" -eq 0 ]; then
        git -C "$source_dir" apply --whitespace=error-all "${pending[@]}"
        applied_count=${#pending[@]}
    fi
fi

if [ "$check_only" -eq 1 ]; then
    echo "CHECK OK: ${#pending[@]} ready, $already_count already applied; source unchanged"
else
    echo "APPLIED: $applied_count patch(es), $already_count already applied; no esync backport"
    if [ -n "${GITHUB_ENV:-}" ]; then
        {
            echo "DWPROTON_TERMUX_STATUS=applied"
            echo "DWPROTON_FSYNC_STATUS=$fsync_status"
            echo "DWPROTON_ESYNC_STATUS=skipped"
        } >> "$GITHUB_ENV"
    fi
fi
