#!/usr/bin/env bash
# CI stage 10 (build), owned by P0-TOOLCHAIN. Protocol: harness/ci.d/README.md (P0-REPO).
#   in:  CI_MODE=quick|default|full  CI_LANES=N  CI_RUNDIR=<run dir>
#   out: "CI build: PASS|FAIL|SKIP (<reason>)", exit 0 | 1 | 77
# Configures and builds the `host` preset and the win32 preset(s): FLMOD_TRACK=A|B picks one track;
# unset (before Gate 0a decides) builds every track whose inputs are present.
set -uo pipefail

NAME=build
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
RUNDIR=${CI_RUNDIR:-$(mktemp -d)}
mkdir -p "$RUNDIR"
LLVM=/usr/lib/llvm/22/bin
XWIN_ROOT=${XWIN_ROOT:-/home/user/opt/xwin}
FLMOD_VENDOR=${FLMOD_VENDOR:-/home/user/freelancer/carrier-mod/vendor}
export XWIN_ROOT FLMOD_VENDOR

skip() { echo "CI $NAME: SKIP ($*)"; exit 77; }
[[ -f $REPO/CMakePresets.json ]] || skip "no CMakePresets.json"
command -v cmake >/dev/null && command -v ninja >/dev/null || skip "cmake/ninja not installed"
[[ -x $LLVM/clang++ ]] || skip "$LLVM/clang++ missing"
[[ -f $FLMOD_VENDOR/doctest/.flmod-pin ]] || skip "vendor tree missing (run toolchain/fetch_vendor.sh)"

presets=(host)
notes=()
if [[ -x $LLVM/clang-cl && -d "$XWIN_ROOT/VC/Tools/MSVC" ]]; then
  case "${FLMOD_TRACK:-}" in
    A) tracks=(A) ;;
    B) tracks=(B) ;;
    *) tracks=(A B) ;;
  esac
  for t in "${tracks[@]}"; do
    if [[ $t == A && ! -f $FLMOD_VENDOR/FLUF/.flmod-pin ]]; then notes+=("trackA skipped: no FLUF vendor"); continue; fi
    presets+=("win32-track$t")
  done
else
  notes+=("win32 skipped: no clang-cl or XWIN_ROOT splat")
fi

fail=()
for p in "${presets[@]}"; do
  log="$RUNDIR/10-build-$p.log"
  if (cd "$REPO" && cmake --preset "$p" && cmake --build --preset "$p") >"$log" 2>&1; then
    echo "  $p: ok ($log)"
  else
    echo "  $p: FAILED ($log)"; tail -n 20 "$log" | sed 's/^/    /'
    fail+=("$p")
  fi
done

extra=""
[[ ${#notes[@]} -gt 0 ]] && extra="; ${notes[*]}"
if [[ ${#fail[@]} -gt 0 ]]; then
  echo "CI $NAME: FAIL (${fail[*]}$extra)"; exit 1
fi
echo "CI $NAME: PASS (${presets[*]}$extra)"
exit 0
