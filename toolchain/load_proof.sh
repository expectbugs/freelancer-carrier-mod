#!/usr/bin/env bash
# toolchain/load_proof.sh: REQ-P0-TOOLCHAIN-10, runtime load proof without running the game, plus the
# exception-handling regression probe (toolchain/ehprobe.sh).
#
#   toolchain/load_proof.sh <win32-trackB build dir> [--clone <prefix-dev-name>] [--from <src>] [--keep]
#                           [--crt builtin|native|both]
#
#   --clone  name of the throwaway clone under /home/user/freelancer/ (default prefix-dev-toolchain; must start
#            with prefix-dev, must not be prefix-dev-base*; use a unique name for concurrent runs)
#   --from   clone source: prefix-dev-base-B (default; P0-HARNESS's Track B baseline, HDE intact),
#            prefix-dev-base-A, or `play` (the play prefix, only while idle). It is only read, never written, and
#            must not be in use (toolchain/prefix_clone.sh).
#   --keep   keep the clone afterwards (default: wineserver -k it and delete it)
#   --crt    runtime(s) for the EH probe (default both; native needs $FLMOD_VENDOR/msvc-redist/x86)
#
# 1. Validates everything first (build outputs, clone name free, source exists and is idle); nothing is created
#    before that.
# 2. Reflink-clones the source to /home/user/freelancer/<clone>.
# 3. Copies loadtest.exe + hello_b.dll into the clone's HDE EXE dir and runs, with cwd = that dir,
#    `wine loadtest.exe hello_b.dll FlmodSelfTest` through the wine guards.
#    Expects "CreateID(li02)=2745692751" on stdout and in hello_b.log.
# 4. Runs toolchain/ehprobe.sh --prefix <clone> (out/ehprobe.dll): every case PASS, KNOWN-BROKEN or SKIP.
# 5. `wineserver -k` for that clone only, then deletes it (unless --keep).
# Output: $FLMOD_TESTRUNS/<UTC stamp>-toolchain-loadproof/{console.txt,hello_b.log,result.txt,ehprobe/}
# Exit: 0 PASS; 1 FAIL; 2 usage; 3 source in use; 77 a prerequisite or a requested EH runtime missing.
set -euo pipefail

usage() { echo "load_proof: $*" >&2; exit 2; }
[[ $# -ge 1 && $1 != -* ]] || usage "usage: load_proof.sh <build dir> [--clone <prefix-dev-name>] [--from <src>] [--keep] [--crt builtin|native|both]"
BUILD=$1
shift
KEEP=0 CLONE_NAME=prefix-dev-toolchain CRT=both FROM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) KEEP=1; shift ;;
    --clone|--crt|--from)
      [[ $# -ge 2 ]] || usage "$1 needs a value"
      case "$1" in --clone) CLONE_NAME=$2 ;; --crt) CRT=$2 ;; --from) FROM=$2 ;; esac
      shift 2 ;;
    *) usage "unknown argument $1" ;;
  esac
done
case "$CRT" in builtin|native|both) ;; *) usage "--crt must be builtin, native or both" ;; esac

REPO=/home/user/freelancer/carrier-mod
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$REPO/tools/env.sh"   # guards first on PATH, FLMOD_* paths, sentinel WINEPREFIX
# shellcheck source=prefix_clone.sh
. "$HERE/prefix_clone.sh"
[[ $(type -P wine) == "$REPO/tools/bin/wine" ]] || usage "wine does not resolve to the guard"

EXE_REL="drive_c/Games/Freelancer HD Edition/EXE"
EXPECT="CreateID(li02)=2745692751"

BUILD=$(realpath -m "$BUILD")
for f in loadtest.exe hello_b.dll ehprobe.dll; do
  [[ -f $BUILD/out/$f ]] || { echo "load_proof: missing $BUILD/out/$f (build the win32-trackB preset)" >&2; exit 77; }
done
CLONE=$(flmod_check_clone_name "$CLONE_NAME") || exit 2
set +e
SRC=$(flmod_check_clone_source "${FROM:-$FLMOD_DEFAULT_CLONE_SOURCE}"); src_rc=$?
set -e
[[ $src_rc == 0 ]] || exit "$src_rc"
[[ -d "$SRC/$EXE_REL" ]] || { echo "load_proof: $SRC has no '$EXE_REL'" >&2; exit 77; }

RUN="$FLMOD_TESTRUNS/$(date -u +%Y%m%dT%H%M%SZ)-toolchain-loadproof"
mkdir -p "$RUN"
log() { printf '%s\n' "$*" | tee -a "$RUN/result.txt"; }

cleanup() {
  if [[ -d $CLONE ]]; then
    WINEPREFIX=$CLONE wineserver -k 2>/dev/null || true
    if [[ $KEEP == 0 ]]; then rm -rf --one-file-system "$CLONE"; log "clone deleted: $CLONE"; fi
  fi
}
trap cleanup EXIT

log "clone: cp -a --reflink=always $SRC $CLONE"
cp -a --reflink=always "$SRC" "$CLONE"
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
case $eh_rc in
  0) log "EHPROBE: PASS (no FAIL; KNOWN-BROKEN cases are documented in toolchain/ABI.md §6)" ;;
  77) log "EHPROBE: SKIP (a requested runtime or prerequisite was missing)" ;;
  *) log "EHPROBE: FAIL (exit $eh_rc)" ;;
esac

log "run dir: $RUN"
if [[ $load_ok == 1 && $eh_rc == 0 ]]; then log "RESULT: PASS"; exit 0; fi
if [[ $load_ok == 1 && $eh_rc == 77 ]]; then log "RESULT: SKIP (load PASS, EH probe incomplete)"; exit 77; fi
log "RESULT: FAIL"
exit 1
