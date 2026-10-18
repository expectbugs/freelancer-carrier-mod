#!/bin/bash
# CI stage 30 "pytest" (owner P0-DATATOOLS; harness root added by P0-HARNESS per D113; CONVENTIONS §5,
# P0-REPO drop-in protocol).
#
# One pytest process per test root, each with its own cwd, config and interpreter, so the
# roots' conftest modules and pytest configs never collide:
#   tests-py   cwd <repo>          $FLMOD_VENV          pytest tests/py
#   sidecar    cwd <repo>/sidecar  $FLMOD_SIDECAR_VENV  pytest tests     (else $FLMOD_VENV;
#                                                                      its audio tests skip)
#   gen-tests  cwd <repo>          $FLMOD_VENV          pytest gen/tests
#   harness    cwd <repo>          $FLMOD_VENV          pytest harness/tests  (D113; tests that need lanes, X, Wine or
#                                                                      the GPU skip with a reason; lane suites run
#                                                                      only with ci.sh --lanes N, CI_LANES)
# A missing root (or one without pytest) is SKIP. Logs: $CI_RUNDIR/30-pytest/<root>.log.
# Prints "CI pytest: PASS|FAIL|SKIP (<reason>)"; exits 0 / 1 / 77. Inputs: CI_MODE, CI_LANES,
# CI_RUNDIR. CI_REPO_ROOT overrides the repo root (tests only).
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${CI_REPO_ROOT:-$(cd "$here/../.." && pwd)}"
venv="${FLMOD_VENV:-/home/user/freelancer/carrier-mod/.venv}"
sidecar_venv="${FLMOD_SIDECAR_VENV:-/home/user/freelancer/carrier-mod/local/sidecar-venv}"

rundir="${CI_RUNDIR:-}"
if [ -z "$rundir" ]; then
  rundir="$(mktemp -d "${TMPDIR:-/tmp}/ci-pytest.XXXXXX")"
fi
logdir="$rundir/30-pytest"
mkdir -p "$logdir"

has_pytest() { [ -x "$1/bin/python" ] && "$1/bin/python" -I -c 'import pytest' >/dev/null 2>&1; }

passed=(); failed=(); skipped=()

# run_root <name> <cwd> <venv> <test path relative to cwd>
run_root() {
  local name="$1" cwd="$2" env="$3" path="$4" log="$logdir/$1.log" rc summary
  if [ ! -d "$cwd/$path" ]; then
    skipped+=("$name: absent"); return
  fi
  if ! has_pytest "$env"; then
    skipped+=("$name: no pytest in $env"); return
  fi
  ( cd "$cwd" && "$env/bin/python" -I -m pytest -q -p no:cacheprovider -rfEs "$path" ) \
    >"$log" 2>&1
  rc=$?
  summary="$(grep -E '[0-9]+ (passed|failed|skipped|error)' "$log" | tail -n 1 | sed 's/=//g; s/^ *//; s/ *$//')"
  case $rc in
    0) passed+=("$name: ${summary:-ok}") ;;
    5) skipped+=("$name: no tests collected") ;;
    *) failed+=("$name: rc=$rc ${summary:-see log}") ;;
  esac
}

run_root tests-py "$repo" "$venv" tests/py
sc_env="$venv"
if has_pytest "$sidecar_venv"; then sc_env="$sidecar_venv"; fi
run_root sidecar "$repo/sidecar" "$sc_env" tests
run_root gen-tests "$repo" "$venv" gen/tests
run_root harness "$repo" "$venv" harness/tests

join() { local out; out="$(printf '%s; ' "$@")"; echo "${out%; }"; }
if [ ${#failed[@]} -gt 0 ]; then
  echo "CI pytest: FAIL ($(join "${failed[@]}"); logs $logdir)"
  for f in "$logdir"/*.log; do
    grep -E '^(FAILED|ERROR) ' "$f" 2>/dev/null | head -n 10 | sed "s|^|  $(basename "$f" .log): |"
  done
  exit 1
fi
if [ ${#passed[@]} -eq 0 ]; then
  echo "CI pytest: SKIP ($(join "${skipped[@]}"))"
  exit 77
fi
extra=""
[ ${#skipped[@]} -gt 0 ] && extra="; skipped $(join "${skipped[@]}")"
echo "CI pytest: PASS ($(join "${passed[@]}")$extra; logs $logdir)"
exit 0
