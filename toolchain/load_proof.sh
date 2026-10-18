#!/usr/bin/env bash
# toolchain/load_proof.sh: REQ-P0-TOOLCHAIN-10, runtime load proof without running the game, plus the
# exception-handling regression probe (toolchain/ehprobe.sh).
#
#   toolchain/load_proof.sh <win32-trackB build dir> [--clone <prefix-dev-name>] [--keep] [--crt builtin|native|both]
#
#   --clone  name of the throwaway clone under /home/user/freelancer/ (default prefix-dev-toolchain; must
#            start with prefix-dev; use a unique name for concurrent runs)
#   --keep   keep the clone afterwards (default: wineserver -k it and delete it)
#   --crt    runtime(s) for the EH probe (default both; native needs $FLMOD_VENDOR/msvc-redist/x86)
#
# 1. Refuses unless the play prefix is idle (tools/play_prefix_busy.sh exits 1) and the clone name is free.
# 2. Reflink-clones the play prefix to /home/user/freelancer/<clone>.
# 3. Copies loadtest.exe + hello_b.dll into the clone's HDE EXE dir and runs, with cwd = that dir,
#    `wine loadtest.exe hello_b.dll FlmodSelfTest` through the wine guards.
#    Expects "CreateID(li02)=2745692751" on stdout and in hello_b.log.
# 4. Runs toolchain/ehprobe.sh against the same clone (out/ehprobe.dll): every case PASS or KNOWN-BROKEN.
# 5. `wineserver -k` for that prefix only, then deletes the clone (unless --keep).
# Output: $FLMOD_TESTRUNS/<UTC stamp>-toolchain-loadproof/{console.txt,hello_b.log,result.txt,ehprobe/}
set -euo pipefail

BUILD=${1:?usage: load_proof.sh <build dir> [--clone <prefix-dev-name>] [--keep] [--crt builtin|native|both]}
shift
KEEP=0 CLONE_NAME=prefix-dev-toolchain CRT=both
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) KEEP=1; shift ;;
    --clone) CLONE_NAME=$2; shift 2 ;;
    --crt) CRT=$2; shift 2 ;;
    *) echo "load_proof: unknown argument $1" >&2; exit 2 ;;
  esac
done
case "$CLONE_NAME" in prefix-dev*) ;; *) echo "load_proof: --clone must start with prefix-dev" >&2; exit 2 ;; esac
[[ $CLONE_NAME == */* ]] && { echo "load_proof: --clone takes a name, not a path" >&2; exit 2; }

REPO=/home/user/freelancer/carrier-mod
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$REPO/tools/env.sh"   # guards first on PATH, FLMOD_* paths, sentinel WINEPREFIX

PLAY=/home/user/freelancer/prefix
CLONE=/home/user/freelancer/$CLONE_NAME
EXE_REL="drive_c/Games/Freelancer HD Edition/EXE"
EXPECT="CreateID(li02)=2745692751"

BUILD=$(realpath "$BUILD")
for f in loadtest.exe hello_b.dll ehprobe.dll; do
  [[ -f $BUILD/out/$f ]] || { echo "load_proof: missing $BUILD/out/$f (build the win32-trackB preset)" >&2; exit 2; }
done
[[ $(type -P wine) == "$REPO/tools/bin/wine" ]] || { echo "load_proof: wine does not resolve to the guard" >&2; exit 2; }

RUN="$FLMOD_TESTRUNS/$(date -u +%Y%m%dT%H%M%SZ)-toolchain-loadproof"
mkdir -p "$RUN"
log() { printf '%s\n' "$*" | tee -a "$RUN/result.txt"; }

cleanup() {
  if [[ -d $CLONE ]]; then
    WINEPREFIX=$CLONE wineserver -k 2>/dev/null || true
    if [[ $KEEP == 0 ]]; then rm -rf --one-file-system "$CLONE"; log "clone deleted: $CLONE"; fi
  fi
}

if [[ -e $CLONE ]]; then
  echo "load_proof: $CLONE already exists; pick another --clone name or delete it (it is a throwaway clone)" >&2
  exit 2
fi
if "$REPO/tools/play_prefix_busy.sh" >"$RUN/play_prefix_busy.txt"; then
  echo "load_proof: play prefix is busy, refusing to clone (see $RUN/play_prefix_busy.txt)" >&2
  exit 3
fi
trap cleanup EXIT

log "clone: cp -a --reflink=always $PLAY $CLONE"
cp -a --reflink=always "$PLAY" "$CLONE"
EXE_DIR="$CLONE/$EXE_REL"
cp -f "$BUILD/out/loadtest.exe" "$BUILD/out/hello_b.dll" "$EXE_DIR/"
log "copied loadtest.exe + hello_b.dll -> $EXE_DIR"

set +e
# Pipe, don't redirect: wine-proton 11 drops a console app's stdout when the Unix stdout is a regular
# file (pipes and ptys work; toolchain/NOTES.md "Bug 1").
( cd "$EXE_DIR" && WINEPREFIX=$CLONE WINEDEBUG=-all timeout 180 wine loadtest.exe hello_b.dll FlmodSelfTest ) \
  2>"$RUN/stderr.txt" | cat >"$RUN/console.txt"
rc=${PIPESTATUS[0]}
set -e
cp -f "$EXE_DIR/hello_b.log" "$RUN/hello_b.log" 2>/dev/null || true

log "wine exit code: $rc"
log "--- console.txt"
tr -d '\r' <"$RUN/console.txt" | tee -a "$RUN/result.txt"
log "--- hello_b.log"
tr -d '\r' <"$RUN/hello_b.log" 2>/dev/null | tee -a "$RUN/result.txt" || log "(missing)"

load_ok=0
if [[ $rc == 0 ]] && grep -q "$EXPECT" "$RUN/console.txt" && grep -q "$EXPECT" "$RUN/hello_b.log" 2>/dev/null; then
  load_ok=1
  log "LOAD: PASS ($EXPECT)"
else
  log "LOAD: FAIL (expected $EXPECT in console and hello_b.log)"
fi

log "--- EH probe (toolchain/ehprobe.sh --crt $CRT)"
set +e
"$HERE/ehprobe.sh" --build "$BUILD" --prefix "$CLONE" --crt "$CRT" --run-dir "$RUN/ehprobe" | tee -a "$RUN/result.txt"
eh_rc=${PIPESTATUS[0]}
set -e
if [[ $eh_rc == 0 ]]; then log "EHPROBE: PASS (no FAIL; KNOWN-BROKEN cases are documented in toolchain/ABI.md §6)"
else log "EHPROBE: FAIL (exit $eh_rc)"; fi

log "run dir: $RUN"
if [[ $load_ok == 1 && $eh_rc == 0 ]]; then log "RESULT: PASS"; exit 0; fi
log "RESULT: FAIL"
exit 1
