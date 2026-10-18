#!/usr/bin/env bash
# toolchain/ehprobe.sh: exception-handling regression probe under Wine (toolchain/ABI.md §6, NOTES.md "Bug 2").
#
#   toolchain/ehprobe.sh --build <win32 build dir> (--prefix <wine prefix> | --clone <prefix-dev-name>)
#                        [--crt builtin|native|both] [--run-dir <dir>]
#
#   --build    a win32 build dir with out/loadtest.exe and out/ehprobe.dll (either track)
#   --prefix   an existing build prefix (prefix-dev*, prefix-lane*, prefix-carrier*); files go to a scratch dir
#              drive_c/flmod_ehprobe/ inside it and are removed afterwards. Nothing else in it is touched, and its
#              wineserver is not killed (a lane may be running the game).
#   --clone    reflink-clone the play prefix to /home/user/freelancer/<name> (must match prefix-dev*), run, then
#              `wineserver -k` it and delete it. Refuses if the play prefix is busy or <name> exists.
#   --crt      builtin (default): Wine's vcruntime140/msvcp140. native: MSVC's 14.51 DLLs from
#              $FLMOD_VENDOR/msvc-redist/x86 app-local with WINEDLLOVERRIDES=vcruntime140,msvcp140=n,b. both.
#   --run-dir  where to write results (default $FLMOD_TESTRUNS/<UTC stamp>-ehprobe/)
#
# Each case of toolchain/ehprobe_cases.tsv runs in its own `wine loadtest.exe ehprobe.dll <case>` process.
# Output, one line per case (also in results.tsv / results.json):
#   EHPROBE crt=<crt> case=<case> group=<a|b|c|parse|base|lib> status=PASS|KNOWN-BROKEN|FAIL expect=<pass|broken> want=<n> got=<n|none> rc=<n>
#   EHPROBE summary crt=<crt> pass=<n> known_broken=<n> fail=<n> unexpected_pass=<n>
# Exit: 0 no FAIL, 1 a FAIL, 2 usage error, 77 prerequisites missing (CI SKIP).
set -uo pipefail

REPO=/home/user/freelancer/carrier-mod
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASES_FILE="$HERE/ehprobe_cases.tsv"
BUILD="" PREFIX="" CLONE_NAME="" CRT=builtin RUN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=$2; shift 2 ;;
    --prefix) PREFIX=$2; shift 2 ;;
    --clone) CLONE_NAME=$2; shift 2 ;;
    --crt) CRT=$2; shift 2 ;;
    --run-dir) RUN=$2; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "ehprobe: unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -n $BUILD ]] || { echo "ehprobe: --build is required" >&2; exit 2; }
[[ -n $PREFIX && -n $CLONE_NAME ]] && { echo "ehprobe: --prefix and --clone are exclusive" >&2; exit 2; }
[[ -z $PREFIX && -z $CLONE_NAME ]] && { echo "ehprobe: give --prefix or --clone" >&2; exit 2; }
case "$CRT" in builtin) crts=(builtin) ;; native) crts=(native) ;; both) crts=(builtin native) ;;
  *) echo "ehprobe: --crt must be builtin, native or both" >&2; exit 2 ;; esac

# shellcheck disable=SC1091
. "$REPO/tools/env.sh"   # guards first on PATH, FLMOD_* paths, sentinel WINEPREFIX
[[ $(type -P wine) == "$REPO/tools/bin/wine" ]] || { echo "ehprobe: wine does not resolve to the guard" >&2; exit 2; }

BUILD=$(realpath "$BUILD")
for f in loadtest.exe ehprobe.dll; do
  [[ -f $BUILD/out/$f ]] || { echo "EHPROBE skip: missing $BUILD/out/$f"; exit 77; }
done
NATIVE_DIR="$FLMOD_VENDOR/msvc-redist/x86"

RUN=${RUN:-"$FLMOD_TESTRUNS/$(date -u +%Y%m%dT%H%M%SZ)-ehprobe"}
mkdir -p "$RUN"

made_clone=""
if [[ -n $CLONE_NAME ]]; then
  case "$CLONE_NAME" in prefix-dev*) ;; *) echo "ehprobe: --clone name must start with prefix-dev" >&2; exit 2 ;; esac
  [[ $CLONE_NAME == */* ]] && { echo "ehprobe: --clone takes a name, not a path" >&2; exit 2; }
  PREFIX=/home/user/freelancer/$CLONE_NAME
  [[ -e $PREFIX ]] && { echo "ehprobe: $PREFIX already exists" >&2; exit 2; }
  if "$REPO/tools/play_prefix_busy.sh" >"$RUN/play_prefix_busy.txt"; then
    echo "ehprobe: play prefix busy, refusing to clone" >&2; exit 3
  fi
  cp -a --reflink=always /home/user/freelancer/prefix "$PREFIX"
  made_clone=$PREFIX
fi
PREFIX=$(realpath -m "$PREFIX")
case "$PREFIX" in
  /home/user/freelancer/prefix-dev*|/home/user/freelancer/prefix-lane*|/home/user/freelancer/prefix-carrier*) ;;
  *) echo "ehprobe: $PREFIX is not a build prefix" >&2; exit 2 ;;
esac
[[ -d $PREFIX/drive_c ]] || { echo "EHPROBE skip: $PREFIX is not a wine prefix"; exit 77; }
WORK="$PREFIX/drive_c/flmod_ehprobe"

cleanup() {
  rm -rf --one-file-system "$WORK"
  # Only a clone we made is ours to kill; an existing (lane) prefix may be running the game.
  if [[ -n $made_clone ]]; then
    WINEPREFIX=$made_clone wineserver -k 2>/dev/null || true
    rm -rf --one-file-system "$made_clone"
  fi
}
trap cleanup EXIT

total_fail=0
: >"$RUN/results.tsv"
for crt in "${crts[@]}"; do
  dir="$WORK/$crt"
  mkdir -p "$dir"
  cp -f "$BUILD/out/loadtest.exe" "$BUILD/out/ehprobe.dll" "$dir/"
  overrides=""
  if [[ $crt == native ]]; then
    if [[ ! -f $NATIVE_DIR/vcruntime140.dll || ! -f $NATIVE_DIR/msvcp140.dll ]]; then
      echo "EHPROBE summary crt=native skipped=1 reason=\"no $NATIVE_DIR (toolchain/fetch_vendor.sh msvc-redist-x86)\""
      continue
    fi
    cp -f "$NATIVE_DIR"/*.dll "$dir/"
    overrides="vcruntime140,msvcp140=n,b"
  fi
  pass=0 kb=0 fail=0 unexpected=0
  while IFS=$'\t' read -r case group want exp_builtin exp_native note; do
    [[ -z $case || $case == \#* ]] && continue
    expect=$exp_builtin; [[ $crt == native ]] && expect=$exp_native
    out=$(cd "$dir" && { WINEPREFIX=$PREFIX WINEDEBUG=-all WINEDLLOVERRIDES=$overrides \
            timeout 60 wine loadtest.exe ehprobe.dll "$case" 2>/dev/null | tr -d '\r'; exit "${PIPESTATUS[0]}"; })
    rc=$?
    printf '%s\n' "$out" >"$RUN/$crt-$case.txt"
    got=$(printf '%s\n' "$out" | sed -n "s/^loadtest: $case() returned \(-\{0,1\}[0-9]*\) .*/\1/p" | tail -n 1)
    works=0; [[ $rc == 0 && $got == "$want" ]] && works=1
    if [[ $expect == pass ]]; then
      if [[ $works == 1 ]]; then status=PASS; pass=$((pass+1)); else status=FAIL; fail=$((fail+1)); fi
    else
      if [[ $works == 1 ]]; then status=PASS; pass=$((pass+1)); unexpected=$((unexpected+1)); else status=KNOWN-BROKEN; kb=$((kb+1)); fi
    fi
    line="EHPROBE crt=$crt case=${case#ehp_} group=$group status=$status expect=$expect want=$want got=${got:-none} rc=$rc"
    echo "$line"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$crt" "${case#ehp_}" "$group" "$status" "$expect" "$want" "${got:-none}" "$rc" >>"$RUN/results.tsv"
  done <"$CASES_FILE"
  echo "EHPROBE summary crt=$crt pass=$pass known_broken=$kb fail=$fail unexpected_pass=$unexpected"
  [[ $fail -gt 0 ]] && total_fail=1
done

python3 -I - "$RUN/results.tsv" "$RUN/results.json" <<'EOF'
import json, sys
rows = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
keys = ["crt", "case", "group", "status", "expect", "want", "got", "rc"]
json.dump([dict(zip(keys, r)) for r in rows], open(sys.argv[2], "w"), indent=1)
EOF
echo "EHPROBE run_dir=$RUN result=$([[ $total_fail == 0 ]] && echo PASS || echo FAIL)"
exit $total_fail
