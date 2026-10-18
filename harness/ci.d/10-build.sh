#!/usr/bin/env bash
# CI stage 10 (build), owned by P0-TOOLCHAIN. Protocol: harness/ci.d/README.md (P0-REPO).
#   in:  CI_MODE  CI_LANES  CI_RUNDIR  CI_REPO_ROOT (the work tree under test)  [FLMOD_TRACK=A|B]
#   out: logs in $CI_RUNDIR/10-build/; verdict line "CI build: PASS|FAIL|SKIP (<reason>)"; exit 0 | 1 | 77
# Configures and builds the `host` preset and the win32 preset(s) in CI_REPO_ROOT/build/<preset>:
# FLMOD_TRACK=A|B picks one track; unset (before Gate 0a decides) builds every track whose inputs exist
# (toolchain/ci_tracks.sh, shared with stage 50).
# After each win32 build, toolchain/check_flags.py asserts on compile_commands.json that every clang-cl TU has
# /clang:-mstackrealign, /MD and _ITERATOR_DEBUG_LEVEL=0, and every C++ TU /EHa (toolchain/ABI.md §6). No Wine.
set -uo pipefail

NAME=build
STAGE_DIR=10-build
REPO=${CI_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
TESTRUNS=${FLMOD_TESTRUNS:-/home/user/freelancer/carrier-mod/local/testruns}
RUNDIR=${CI_RUNDIR:-$TESTRUNS/$(date -u +%Y%m%dT%H%M%SZ)-ci-$NAME}
OUT="$RUNDIR/$STAGE_DIR"
mkdir -p "$OUT"
LLVM=/usr/lib/llvm/22/bin
XWIN_ROOT=${XWIN_ROOT:-/home/user/opt/xwin}
FLMOD_VENDOR=${FLMOD_VENDOR:-/home/user/freelancer/carrier-mod/vendor}
export XWIN_ROOT FLMOD_VENDOR
PY=${FLMOD_VENV:-/home/user/freelancer/carrier-mod/.venv}/bin/python
[[ -x $PY ]] || PY=python3

skip() { echo "CI $NAME: SKIP ($*)"; exit 77; }
[[ -f $REPO/CMakePresets.json ]] || skip "no CMakePresets.json in $REPO"
command -v cmake >/dev/null && command -v ninja >/dev/null || skip "cmake/ninja not installed"
[[ -x $LLVM/clang++ ]] || skip "$LLVM/clang++ missing"
[[ -f $FLMOD_VENDOR/doctest/.flmod-pin ]] || skip "vendor tree missing (run toolchain/fetch_vendor.sh)"
[[ -f $REPO/toolchain/ci_tracks.sh ]] || skip "no toolchain/ci_tracks.sh in $REPO"

# shellcheck source=../../toolchain/ci_tracks.sh
. "$REPO/toolchain/ci_tracks.sh"
if ! flmod_ci_win32_tracks; then
  echo "CI $NAME: FAIL (${FLMOD_CI_NOTES[*]})"; exit 1
fi
presets=(host)
for t in "${FLMOD_CI_TRACKS[@]}"; do presets+=("win32-track$t"); done
notes=("${FLMOD_CI_NOTES[@]}")

fail=()
for p in "${presets[@]}"; do
  log="$OUT/$p.log"
  if (cd "$REPO" && cmake --preset "$p" && cmake --build --preset "$p") >"$log" 2>&1; then
    echo "  $p: ok ($log)"
  else
    echo "  $p: FAILED ($log)"; tail -n 20 "$log" | sed 's/^/    /'
    fail+=("$p")
    continue
  fi
  if [[ $p == win32-* ]]; then
    flog="$OUT/$p-flags.log"
    if "$PY" -I "$REPO/toolchain/check_flags.py" "$REPO/build/$p/compile_commands.json" \
         --json "$OUT/$p-flags.json" >"$flog" 2>&1; then
      echo "  $p: compile flags ok ($(grep -o '[0-9]* clang-cl TUs[^,]*' "$flog" | head -n 1))"
    else
      echo "  $p: compile flags FAILED ($flog)"; tail -n 20 "$flog" | sed 's/^/    /'
      fail+=("$p:flags")
    fi
  fi
done

extra=""
[[ ${#notes[@]} -gt 0 ]] && extra="; ${notes[*]}"
if [[ ${#fail[@]} -gt 0 ]]; then
  echo "CI $NAME: FAIL (${fail[*]}$extra)"; exit 1
fi
echo "CI $NAME: PASS (${presets[*]}; win32 flags checked$extra)"
exit 0
