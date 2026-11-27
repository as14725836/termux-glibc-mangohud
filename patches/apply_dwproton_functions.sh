#!/usr/bin/env bash
# 应用已审查的 DWProton winmm 函数补丁集（0001）。
# 用法: apply_dwproton_functions.sh <源码目录>
# 特性:
#   - 校验 SHA256SUMS（--strict）
#   - 按 series 顺序 git apply --check 后再 git apply
#   - 仅当补丁能干净应用（git apply --check 通过）时才实际应用
#   - 不兼容的源码分支自动 SKIP，不中断构建
#   - 成功后执行 git diff --check
set -uo pipefail
SRC="${1:-.}"
P_DIR="${GITHUB_WORKSPACE}/patches/dwproton-functions"
BASE_EXPECTED="e6a370ff7db61c230df94996f00131e22f9165cf"

echo "=== DWProton function patches ==="
echo "source: ${SRC}"
if [ ! -d "$P_DIR" ]; then
  echo "SKIP: ${P_DIR} 不存在"; exit 0
fi
if [ ! -d "${SRC}/.git" ] && [ ! -f "${SRC}/.git" ]; then
  echo "SKIP: ${SRC} 不是 git 仓库，无法应用补丁"; exit 0
fi

# 1) 校验补丁集完整性
(
  cd "$P_DIR" || exit 1
  sha256sum --check --strict SHA256SUMS
) || { echo "SKIP: SHA256SUMS 校验失败"; exit 0; }
PSHA="$(sha256sum "${P_DIR}/SHA256SUMS" | cut -d' ' -f1)"

# 2) 兼容性预检：series 中每个补丁都必须能在目标源码上干净应用
cd "$SRC" || exit 0
BASE_ACTUAL="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
if [ "$BASE_ACTUAL" != "$BASE_EXPECTED" ]; then
  echo "NOTE: 基线 ${BASE_ACTUAL:0:12} != 审查基线 ${BASE_EXPECTED:0:12}；仍以 apply --check 为准"
fi
compat=1
check_only=0
while IFS= read -r patch || [ -n "$patch" ]; do
  case "$patch" in
    ''|\#*) continue ;;
    */*|*[!a-zA-Z0-9._-]*) echo "SKIP: 非法补丁名 $patch"; exit 0 ;;
    *.patch) ;;
    *) echo "SKIP: 非补丁条目 $patch"; exit 0 ;;
  esac
  if ! git apply --check --whitespace=error-all "${P_DIR}/${patch}" >/dev/null 2>&1; then
    compat=0
    echo "SKIP: ${patch} 与当前源码不兼容（apply --check 失败）"
  fi
done < "${P_DIR}/series"

if [ "$compat" -ne 1 ]; then
  echo "SKIP: 补丁集与当前源码不兼容，保持源码原样（不中断构建）"
  exit 0
fi

# 3) 实际应用
applied=0
while IFS= read -r patch || [ -n "$patch" ]; do
  case "$patch" in ''|\#*) continue ;; esac
  echo "=== Applying ${patch} ==="
  git apply --whitespace=error-all "${P_DIR}/${patch}" || {
    echo "WARN: ${patch} 应用失败，回滚已应用补丁"
    git checkout -- . 2>/dev/null || true
    git clean -fd -- dlls/winmm 2>/dev/null || true
    exit 0
  }
  applied=$((applied+1))
done < "${P_DIR}/series"

git diff --check || { echo "WARN: git diff --check 失败，回滚"; git checkout -- . 2>/dev/null || true; exit 0; }

echo "APPLIED: ${applied} patch(es); patchset ${PSHA:0:12}"
echo "BASE_COMMIT=${BASE_ACTUAL}" >> "${GITHUB_ENV}"
echo "FUNCTION_PATCHSET_STATUS=applied" >> "${GITHUB_ENV}"
echo "FUNCTION_PATCHSET_SHA256=${PSHA}" >> "${GITHUB_ENV}"