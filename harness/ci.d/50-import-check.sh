#!/usr/bin/env bash
# CI stage 50 (import-check), owned by P0-TOOLCHAIN. Protocol: harness/ci.d/README.md (P0-REPO).
#   in:  CI_MODE=quick|default|full  CI_LANES=N  CI_RUNDIR=<run dir>
#   out: "CI import-check: PASS|FAIL|SKIP (<reason>)", exit 0 | 1 | 77
# Runs toolchain/check_imports.py over every DLL/EXE in build/win32-track*/out/ (FLUF.dll allowed for
# Track A only). Reads the Wine builtins from FLMOD_IMPORT_CHECK_PREFIX (default: the play prefix,
# read-only; nothing is written to it).
set -uo pipefail

NAME=import-check
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
RUNDIR=${CI_RUNDIR:-$(mktemp -d)}
mkdir -p "$RUNDIR"
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
for dir in "$REPO"/build/win32-track*/out; do
  preset=$(basename "$(dirname "$dir")")
  bins=("$dir"/*.dll "$dir"/*.exe)
  [[ ${#bins[@]} -gt 0 ]] || continue
  args=()
  [[ $preset == win32-trackA ]] && args+=(--allow-fluf)
  log="$RUNDIR/50-import-check-$preset.log"
  if "$PY" -I "$REPO/toolchain/check_imports.py" "${bins[@]}" --prefix "$PREFIX" "${args[@]}" \
       --json "$RUNDIR/50-import-check-$preset.json" >"$log" 2>&1; then
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
