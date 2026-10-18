#!/usr/bin/env bash
# CI stage 50 (import-check), owned by P0-TOOLCHAIN. Protocol: harness/ci.d/README.md (P0-REPO).
#   in:  CI_MODE  CI_LANES  CI_RUNDIR  CI_REPO_ROOT (the work tree under test)
#   out: logs + JSON in $CI_RUNDIR/50-import-check/; verdict "CI import-check: PASS|FAIL|SKIP (<reason>)"; exit 0|1|77
# Runs toolchain/check_imports.py over the binaries the current build produces: the list comes from
# build/win32-track*/flmod_binaries.txt (written by CMake), so stale files left in out/ are ignored. FLUF.dll is
# allowed for Track A only. Wine builtins are read from FLMOD_IMPORT_CHECK_PREFIX (default: the play prefix,
# read-only; nothing is written to it).
set -uo pipefail

NAME=import-check
STAGE_DIR=50-import-check
REPO=${CI_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
TESTRUNS=${FLMOD_TESTRUNS:-/home/user/freelancer/carrier-mod/local/testruns}
RUNDIR=${CI_RUNDIR:-$TESTRUNS/$(date -u +%Y%m%dT%H%M%SZ)-ci-$NAME}
OUT="$RUNDIR/$STAGE_DIR"
mkdir -p "$OUT"
PREFIX=${FLMOD_IMPORT_CHECK_PREFIX:-/home/user/freelancer/prefix}
PY=${FLMOD_VENV:-/home/user/freelancer/carrier-mod/.venv}/bin/python
[[ -x $PY ]] || PY=python3

skip() { echo "CI $NAME: SKIP ($*)"; exit 77; }
[[ -f $REPO/toolchain/check_imports.py ]] || skip "no toolchain/check_imports.py"
[[ -x /usr/lib/llvm/22/bin/llvm-readobj ]] || skip "llvm-readobj missing"
[[ -d $PREFIX/drive_c/windows/syswow64 ]] || skip "no Wine prefix at $PREFIX"

shopt -s nullglob
checked=()
fail=()
for list in "$REPO"/build/win32-track*/flmod_binaries.txt; do
  bdir=$(dirname "$list")
  preset=$(basename "$bdir")
  bins=()
  while IFS= read -r b; do
    [[ -z $b ]] && continue
    if [[ -f $b ]]; then bins+=("$b"); else echo "  $preset: listed binary not built: $b"; fail+=("$preset:missing"); fi
  done <"$list"
  [[ ${#bins[@]} -gt 0 ]] || continue
  args=()
  [[ $preset == win32-trackA ]] && args+=(--allow-fluf)
  log="$OUT/$preset.log"
  if "$PY" -I "$REPO/toolchain/check_imports.py" "${bins[@]}" --prefix "$PREFIX" "${args[@]}" \
       --json "$OUT/$preset.json" >"$log" 2>&1; then
    checked+=("$preset:${#bins[@]}")
  else
    echo "  $preset: FAILED ($log)"; sed 's/^/    /' "$log" | tail -n 40
    fail+=("$preset")
  fi
done

[[ ${#checked[@]} -gt 0 || ${#fail[@]} -gt 0 ]] || skip "no win32 build output (run stage 10 first)"
if [[ ${#fail[@]} -gt 0 ]]; then
  echo "CI $NAME: FAIL (${fail[*]})"; exit 1
fi
echo "CI $NAME: PASS (${checked[*]} binaries clean)"
exit 0
