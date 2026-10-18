#!/usr/bin/env bash
# toolchain/load_proof.sh: REQ-P0-TOOLCHAIN-10, runtime load proof without running the game.
#
#   toolchain/load_proof.sh <build dir with out/loadtest.exe and out/hello_b.dll> [--keep]
#
# 1. Refuses unless the play prefix is idle (tools/play_prefix_busy.sh exits 1).
# 2. Reflink-clones it to /home/user/freelancer/prefix-dev-toolchain (allowed prefix-dev* pattern).
# 3. Copies loadtest.exe + hello_b.dll into the clone's HDE EXE dir and runs, with cwd = that dir,
#    `wine loadtest.exe hello_b.dll FlmodSelfTest` through the wine guards.
# 4. Expects "CreateID(li02)=2745692751" on stdout and in hello_b.log.
# 5. `wineserver -k` for that prefix only, then deletes the clone (unless --keep).
# Output: $FLMOD_TESTRUNS/<UTC stamp>-toolchain-loadproof/{console.txt,hello_b.log,result.txt}
set -euo pipefail

BUILD=${1:?usage: load_proof.sh <build dir> [--keep]}
KEEP=0
[[ ${2:-} == --keep ]] && KEEP=1

REPO=/home/user/freelancer/carrier-mod
# shellcheck disable=SC1091
. "$REPO/tools/env.sh"   # guards first on PATH, FLMOD_* paths, sentinel WINEPREFIX

PLAY=/home/user/freelancer/prefix
CLONE=/home/user/freelancer/prefix-dev-toolchain
EXE_REL="drive_c/Games/Freelancer HD Edition/EXE"
EXPECT="CreateID(li02)=2745692751"

BUILD=$(realpath "$BUILD")
for f in loadtest.exe hello_b.dll; do
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
  echo "load_proof: $CLONE already exists; delete it first (it is this script's throwaway clone)" >&2
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

if [[ $rc == 0 ]] && grep -q "$EXPECT" "$RUN/console.txt" && grep -q "$EXPECT" "$RUN/hello_b.log" 2>/dev/null; then
  log "RESULT: PASS ($EXPECT)"
  log "run dir: $RUN"
  exit 0
fi
log "RESULT: FAIL (expected $EXPECT in console and hello_b.log)"
log "run dir: $RUN"
exit 1
