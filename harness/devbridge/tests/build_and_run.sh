#!/usr/bin/env bash
# Builds the devbridge host tests (doctest) and host_sim natively, then runs the doctest binary.
#
#   build_and_run.sh [--build-only] [-- <doctest args...>]
#
# Output: <worktree>/build/devbridge_host/{test_devbridge_core,host_sim}
# Env: CXX (default /usr/lib/llvm/22/bin/clang++), FLMOD_VENDOR, DEVBRIDGE_SANITIZE=0|1 (default:
# use ASan+UBSan for the doctest binary if the toolchain supports it).
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
src=$(cd "$here/.." && pwd)
wt=$(cd "$src/../.." && pwd)
out="$wt/build/devbridge_host"
CXX=${CXX:-/usr/lib/llvm/22/bin/clang++}
vendor=${FLMOD_VENDOR:-/home/user/freelancer/carrier-mod/vendor}
cache=/home/user/freelancer/carrier-mod/local/cache/doctest-2.4.11
doctest_url=https://raw.githubusercontent.com/doctest/doctest/v2.4.11/doctest/doctest.h

build_only=0
doctest_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --build-only) build_only=1 ;;
    --) shift; doctest_args=("$@"); break ;;
    *) echo "usage: $0 [--build-only] [-- <doctest args>]" >&2; exit 64 ;;
  esac
  shift
done

command -v "$CXX" >/dev/null 2>&1 || { echo "SKIP: compiler $CXX not found" >&2; exit 3; }

# doctest: vendored copy (P0-TOOLCHAIN) or a pinned single header cached once.
doctest_inc=""
for cand in "$vendor/doctest" "$vendor/doctest/doctest"; do
  if [ -f "$cand/doctest.h" ]; then doctest_inc=$cand; break; fi
done
if [ -z "$doctest_inc" ]; then
  if [ ! -s "$cache/doctest.h" ]; then
    mkdir -p "$cache"
    echo "fetching doctest v2.4.11 -> $cache/doctest.h" >&2
    curl -fsSL --retry 3 -o "$cache/doctest.h.part" "$doctest_url"
    mv "$cache/doctest.h.part" "$cache/doctest.h"
  fi
  doctest_inc=$cache
fi

mkdir -p "$out"
common=(-std=c++20 -g -O1 -Wall -Wextra -Wpedantic -pthread)

san=()
if [ "${DEVBRIDGE_SANITIZE:-auto}" != 0 ]; then
  probe="$out/.sanprobe"
  if echo 'int main(){return 0;}' | "$CXX" -x c++ -fsanitize=address,undefined - -o "$probe" >/dev/null 2>&1 \
     && "$probe" >/dev/null 2>&1; then
    san=(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=undefined)
  elif [ "${DEVBRIDGE_SANITIZE:-auto}" = 1 ]; then
    echo "sanitizers requested but unsupported by $CXX" >&2; exit 1
  fi
  rm -f "$probe"
fi

# The core must compile warning-free (it is also built with clang-cl for the game).
"$CXX" "${common[@]}" -Werror -c "$src/devbridge_core.cpp" -o "$out/devbridge_core.o"
"$CXX" "${common[@]}" "${san[@]}" -I"$doctest_inc" "$here/test_devbridge_core.cpp" "$src/devbridge_core.cpp" \
  -o "$out/test_devbridge_core"
"$CXX" "${common[@]}" "$here/host_sim.cpp" "$out/devbridge_core.o" -o "$out/host_sim"
echo "built: $out/test_devbridge_core $out/host_sim (doctest from $doctest_inc${san:+, sanitizers on})" >&2

[ "$build_only" = 1 ] && exit 0
exec "$out/test_devbridge_core" "${doctest_args[@]}"
