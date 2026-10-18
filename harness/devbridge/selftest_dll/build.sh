#!/usr/bin/env bash
# Builds the THROWAWAY devbridge selftest DLL: i686-pc-windows-msvc, MSVC ABI, /MD, clang-cl + lld-link
# against the xwin splat (/winsysroot layout). Never mingw.
#
#   build.sh            -> <worktree>/build/selftest_dll/devbridge_selftest.dll (+ .pdb)
# Exit 3 with "SKIP: xwin splat missing" when $XWIN_ROOT has no CRT/SDK.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
src=$(cd "$here/.." && pwd)
wt=$(cd "$src/../.." && pwd)
out="$wt/build/selftest_dll"
XWIN_ROOT=${XWIN_ROOT:-/home/user/opt/xwin}
LLVM=${FLMOD_LLVM_BIN:-/usr/lib/llvm/22/bin}

if [ ! -d "$XWIN_ROOT/VC/Tools/MSVC" ] || [ ! -d "$XWIN_ROOT/Windows Kits/10/Include" ] ||
   [ ! -d "$XWIN_ROOT/Windows Kits/10/Lib" ]; then
  echo "SKIP: xwin splat missing ($XWIN_ROOT)"
  exit 3
fi
for tool in clang-cl lld-link llvm-readobj; do
  [ -x "$LLVM/$tool" ] || { echo "SKIP: $LLVM/$tool missing"; exit 3; }
done

mkdir -p "$out/obj"
cflags=(
  --target=i686-pc-windows-msvc /winsysroot "$XWIN_ROOT"
  /MD /O2 /EHsc /std:c++20 /Zi /utf-8 /permissive- /W4
  -D_ITERATOR_DEBUG_LEVEL=0 -DWIN32_LEAN_AND_MEAN -DNOMINMAX
  -Wno-microsoft-cast -Wno-cast-function-type-mismatch
  /c
)
"$LLVM/clang-cl" "${cflags[@]}" "/Fo$out/obj/devbridge_core.obj" "$src/devbridge_core.cpp"
"$LLVM/clang-cl" "${cflags[@]}" "/Fo$out/obj/selftest.obj" "$here/selftest.cpp"
"$LLVM/lld-link" /nologo /DLL /machine:x86 /SAFESEH:NO /DEBUG /INCREMENTAL:NO /OPT:REF /OPT:ICF \
  "/winsysroot:$XWIN_ROOT" \
  "/OUT:$out/devbridge_selftest.dll" "/PDB:$out/devbridge_selftest.pdb" \
  "$out/obj/devbridge_core.obj" "$out/obj/selftest.obj" kernel32.lib

echo "built: $out/devbridge_selftest.dll"
"$LLVM/llvm-readobj" --file-headers "$out/devbridge_selftest.dll" | grep -E "^Format|^Arch|Machine:"
"$LLVM/llvm-readobj" --coff-imports "$out/devbridge_selftest.dll" | grep -E "^  Name:" | sort -u
