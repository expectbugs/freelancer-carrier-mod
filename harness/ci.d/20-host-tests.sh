#!/usr/bin/env bash
# CI stage 20 (host-tests), owned by P0-TOOLCHAIN. Protocol: harness/ci.d/README.md (P0-REPO).
#   in:  CI_MODE=quick|default|full  CI_LANES=N  CI_RUNDIR=<run dir>
#   out: "CI host-tests: PASS|FAIL|SKIP (<reason>)", exit 0 | 1 | 77
# ctest over the `host` preset (doctest suites from tests/host/** and src/**/tests/, the src/logic
# standalone-header check and the negative include probes). CI_MODE=full also runs `host-asan`.
set -uo pipefail

NAME=host-tests
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
RUNDIR=${CI_RUNDIR:-$(mktemp -d)}
mkdir -p "$RUNDIR"
LLVM=/usr/lib/llvm/22/bin
FLMOD_VENDOR=${FLMOD_VENDOR:-/home/user/freelancer/carrier-mod/vendor}
export FLMOD_VENDOR

skip() { echo "CI $NAME: SKIP ($*)"; exit 77; }
[[ -f $REPO/CMakePresets.json ]] || skip "no CMakePresets.json"
command -v cmake >/dev/null && command -v ctest >/dev/null && command -v ninja >/dev/null || skip "cmake/ctest/ninja not installed"
[[ -x $LLVM/clang++ ]] || skip "$LLVM/clang++ missing"
[[ -f $FLMOD_VENDOR/doctest/.flmod-pin ]] || skip "vendor tree missing (run toolchain/fetch_vendor.sh)"

presets=(host)
[[ ${CI_MODE:-default} == full ]] && presets+=(host-asan)

fail=()
summary=()
for p in "${presets[@]}"; do
  log="$RUNDIR/20-host-tests-$p.log"
  if (cd "$REPO" && cmake --preset "$p" && cmake --build --preset "$p" && ctest --preset "$p") >"$log" 2>&1; then
    summary+=("$p: $(grep -Eo '[0-9]+% tests passed, [0-9]+ tests failed out of [0-9]+' "$log" | tail -n 1)")
  else
    echo "  $p: FAILED ($log)"; tail -n 30 "$log" | sed 's/^/    /'
    fail+=("$p")
  fi
done

if [[ ${#fail[@]} -gt 0 ]]; then
  echo "CI $NAME: FAIL (${fail[*]})"; exit 1
fi
echo "CI $NAME: PASS (${summary[*]})"
exit 0
