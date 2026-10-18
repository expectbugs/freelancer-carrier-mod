#!/usr/bin/env bash
# toolchain/ehprobe.sh: exception-handling regression probe under Wine (toolchain/ABI.md §6, NOTES.md "Bug 2").
#
#   toolchain/ehprobe.sh --build <win32 build dir> (--prefix <prefix-dev-*> | --clone <prefix-dev-name> [--from <src>])
#                        [--crt builtin|native|both] [--run-dir <dir>]
#
#   --build    a win32 build dir with out/loadtest.exe and out/ehprobe.dll (either track)
#   --prefix   an existing throwaway prefix /home/user/freelancer/prefix-dev-* (never a prefix-dev-base-* baseline,
#              never a lane: lanes may be running the game). Files go to a scratch dir drive_c/flmod_ehprobe/ inside
#              it and are removed afterwards; its wineserver is not killed.
#   --clone    reflink-clone <src> to /home/user/freelancer/<name> (name prefix-dev*, not prefix-dev-base*), run,
#              then `wineserver -k` that clone only and delete it.
#   --from     clone source: prefix-dev-base-B (default), prefix-dev-base-A, or `play` (the play prefix, only while
#              idle). The source must exist and not be in use (toolchain/prefix_clone.sh).
#   --crt      builtin (default): Wine's vcruntime140/msvcp140. native: MSVC's 14.51 DLLs from
#              $FLMOD_VENDOR/msvc-redist/x86 app-local with WINEDLLOVERRIDES=vcruntime140,msvcp140=n,b. both.
#   --run-dir  where to write results (default $FLMOD_TESTRUNS/<UTC stamp>-ehprobe/)
#
# Each case of toolchain/ehprobe_cases.tsv runs in its own `wine loadtest.exe ehprobe.dll <case>` process. Cases
# that need the game's Common.dll get its directory through FLMOD_EHPROBE_GAME_EXE; a case returns -77 (SKIP)
# when a prerequisite is missing. Output, one line per case (also in results.tsv / results.json):
#   EHPROBE crt=<crt> case=<case> group=<group> status=PASS|KNOWN-BROKEN|FAIL|SKIP expect=<pass|broken> want=<n> got=<n|none> rc=<n>
#   EHPROBE summary crt=<crt> pass=<n> known_broken=<n> fail=<n> skip=<n> unexpected_pass=<n>
# Exit: 0 no FAIL and every requested runtime ran; 1 a FAIL; 2 usage error; 3 the clone source is in use; 77
# prerequisites missing, a requested runtime could not run, or no case produced a result (never PASS with zero
# cases). Arguments are validated before any run dir or clone is created.
set -uo pipefail

REPO=/home/user/freelancer/carrier-mod
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASES_FILE="$HERE/ehprobe_cases.tsv"
usage() { echo "ehprobe: $*" >&2; exit 2; }
BUILD="" PREFIX="" CLONE_NAME="" FROM="" CRT=builtin RUN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build|--prefix|--clone|--from|--crt|--run-dir) [[ $# -ge 2 ]] || usage "$1 needs a value" ;;
  esac
  case "$1" in
    --build) BUILD=$2; shift 2 ;;
    --prefix) PREFIX=$2; shift 2 ;;
    --clone) CLONE_NAME=$2; shift 2 ;;
    --from) FROM=$2; shift 2 ;;
    --crt) CRT=$2; shift 2 ;;
    --run-dir) RUN=$2; shift 2 ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    *) usage "unknown argument $1" ;;
  esac
done
[[ -n $BUILD ]] || usage "--build is required"
[[ -n $PREFIX && -n $CLONE_NAME ]] && usage "--prefix and --clone are exclusive"
[[ -z $PREFIX && -z $CLONE_NAME ]] && usage "give --prefix or --clone"
[[ -n $FROM && -z $CLONE_NAME ]] && usage "--from only goes with --clone"
case "$CRT" in builtin) crts=(builtin) ;; native) crts=(native) ;; both) crts=(builtin native) ;;
  *) usage "--crt must be builtin, native or both" ;; esac

# shellcheck disable=SC1091
. "$REPO/tools/env.sh"   # guards first on PATH, FLMOD_* paths, sentinel WINEPREFIX
# shellcheck source=prefix_clone.sh
. "$HERE/prefix_clone.sh"
[[ $(type -P wine) == "$REPO/tools/bin/wine" ]] || usage "wine does not resolve to the guard"

BUILD=$(realpath -m "$BUILD")
for f in loadtest.exe ehprobe.dll; do
  [[ -f $BUILD/out/$f ]] || { echo "EHPROBE skip: missing $BUILD/out/$f"; exit 77; }
done
[[ -f $CASES_FILE ]] || { echo "EHPROBE skip: missing $CASES_FILE"; exit 77; }

# --- validate the prefix (or the clone name and source) before anything is created ---------------------------
SRC=""
if [[ -n $CLONE_NAME ]]; then
  PREFIX=$(flmod_check_clone_name "$CLONE_NAME") || exit 2
  SRC=$(flmod_check_clone_source "${FROM:-$FLMOD_DEFAULT_CLONE_SOURCE}"); src_rc=$?
  [[ $src_rc == 0 ]] || exit "$src_rc"
  GAME_SRC=$SRC
else
  PREFIX=$(realpath -m "$PREFIX")
  case "$PREFIX" in
    "$FLMOD_FL_ROOT"/prefix-dev-base*) usage "--prefix must not be a baseline (prefix-dev-base*); use --clone --from" ;;
    "$FLMOD_FL_ROOT"/prefix-dev*) ;;
    *) usage "--prefix must be a throwaway $FLMOD_FL_ROOT/prefix-dev-* prefix (lanes: use a clone instead)" ;;
  esac
  [[ $PREFIX == */* && ${PREFIX#"$FLMOD_FL_ROOT"/} != */* ]] || usage "--prefix must be directly under $FLMOD_FL_ROOT"
  [[ -d $PREFIX/drive_c ]] || { echo "EHPROBE skip: $PREFIX is not a wine prefix"; exit 77; }
  GAME_SRC=$PREFIX
fi
NATIVE_DIR=${FLMOD_EHPROBE_NATIVE_DIR:-$FLMOD_VENDOR/msvc-redist/x86}   # override: tests of the SKIP path
native_ok=1
[[ -f $NATIVE_DIR/vcruntime140.dll && -f $NATIVE_DIR/msvcp140.dll ]] || native_ok=0
if [[ $CRT == native && $native_ok == 0 ]]; then
  echo "EHPROBE skip: --crt native needs $NATIVE_DIR (toolchain/fetch_vendor.sh msvc-redist-x86)"; exit 77
fi
game_exe=$(flmod_game_exe_dir "$GAME_SRC") || game_exe=""

# --- run ------------------------------------------------------------------------------------------------------
RUN=${RUN:-"$FLMOD_TESTRUNS/$(date -u +%Y%m%dT%H%M%SZ)-ehprobe"}
mkdir -p "$RUN"
made_clone=""
if [[ -n $CLONE_NAME ]]; then
  echo "clone: cp -a --reflink=always $SRC $PREFIX" >"$RUN/clone.txt"
  cp -a --reflink=always "$SRC" "$PREFIX" || { echo "ehprobe: clone failed" >&2; rm -rf --one-file-system "$PREFIX"; exit 1; }
  made_clone=$PREFIX
  [[ -n $game_exe ]] && game_exe=$PREFIX${game_exe#"$SRC"}
fi
WORK="$PREFIX/drive_c/flmod_ehprobe"
game_exe_win=""
[[ -n $game_exe ]] && game_exe_win=$(flmod_win_path "$PREFIX" "$game_exe")
echo "prefix=$PREFIX source=${SRC:-(existing)} game_exe=${game_exe_win:-(none: engine cases SKIP)}" >>"$RUN/clone.txt"

cleanup() {
  rm -rf --one-file-system "$WORK"
  # Only a clone we made is ours to kill.
  if [[ -n $made_clone ]]; then
    WINEPREFIX=$made_clone wineserver -k 2>/dev/null || true
    rm -rf --one-file-system "$made_clone"
  fi
}
trap cleanup EXIT

total_fail=0 incomplete=0
: >"$RUN/results.tsv"
for crt in "${crts[@]}"; do
  if [[ $crt == native && $native_ok == 0 ]]; then
    echo "EHPROBE summary crt=native skipped=1 reason=\"no $NATIVE_DIR (toolchain/fetch_vendor.sh msvc-redist-x86)\""
    incomplete=1
    continue
  fi
  dir="$WORK/$crt"
  mkdir -p "$dir"
  cp -f "$BUILD/out/loadtest.exe" "$BUILD/out/ehprobe.dll" "$dir/"
  overrides=""
  if [[ $crt == native ]]; then
    cp -f "$NATIVE_DIR"/*.dll "$dir/"
    overrides="vcruntime140,msvcp140=n,b"
  fi
  pass=0 kb=0 fail=0 skip=0 unexpected=0
  while IFS=$'\t' read -r case group want exp_builtin exp_native note; do
    [[ -z $case || $case == \#* ]] && continue
    expect=$exp_builtin; [[ $crt == native ]] && expect=$exp_native
    out=$(cd "$dir" && { WINEPREFIX=$PREFIX WINEDEBUG=-all WINEDLLOVERRIDES=$overrides \
            FLMOD_EHPROBE_GAME_EXE=$game_exe_win \
            timeout 60 wine loadtest.exe ehprobe.dll "$case" 2>/dev/null | tr -d '\r'; exit "${PIPESTATUS[0]}"; })
    rc=$?
    printf '%s\n' "$out" >"$RUN/$crt-$case.txt"
    got=$(printf '%s\n' "$out" | sed -n "s/^loadtest: $case() returned \(-\{0,1\}[0-9]*\) .*/\1/p" | tail -n 1)
    works=0; [[ $rc == 0 && $got == "$want" ]] && works=1
    if [[ $rc == 0 && $got == -77 ]]; then
      status=SKIP; skip=$((skip+1))
    elif [[ $expect == pass ]]; then
      if [[ $works == 1 ]]; then status=PASS; pass=$((pass+1)); else status=FAIL; fail=$((fail+1)); fi
    else
      if [[ $works == 1 ]]; then status=PASS; pass=$((pass+1)); unexpected=$((unexpected+1)); else status=KNOWN-BROKEN; kb=$((kb+1)); fi
    fi
    echo "EHPROBE crt=$crt case=${case#ehp_} group=$group status=$status expect=$expect want=$want got=${got:-none} rc=$rc"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$crt" "${case#ehp_}" "$group" "$status" "$expect" "$want" "${got:-none}" "$rc" >>"$RUN/results.tsv"
  done <"$CASES_FILE"
  echo "EHPROBE summary crt=$crt pass=$pass known_broken=$kb fail=$fail skip=$skip unexpected_pass=$unexpected"
  [[ $fail -gt 0 ]] && total_fail=1
  [[ $((pass + kb + fail)) -eq 0 ]] && incomplete=1
done

python3 -I - "$RUN/results.tsv" "$RUN/results.json" <<'EOF'
import json, sys
rows = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
keys = ["crt", "case", "group", "status", "expect", "want", "got", "rc"]
json.dump([dict(zip(keys, r)) for r in rows], open(sys.argv[2], "w"), indent=1)
EOF
if [[ $total_fail == 1 ]]; then result=FAIL; code=1
elif [[ $incomplete == 1 ]]; then result=SKIP; code=77
else result=PASS; code=0; fi
echo "EHPROBE run_dir=$RUN result=$result"
exit $code
