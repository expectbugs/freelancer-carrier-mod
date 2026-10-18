#!/usr/bin/env bash
# toolchain/setup_xwin.sh: install xwin and splat the pinned x86 MSVC CRT/STL + Windows SDK into
# $XWIN_ROOT (/winsysroot layout) for toolchain/clang-cl-i686.cmake. Idempotent.
#
# Usage: toolchain/setup_xwin.sh [--force] [--offline] [--verify]
#   --force    re-splat even if $XWIN_ROOT/.flmod-pin matches
#   --offline  fail instead of touching the network (uses the download cache only)
#   --verify   check the cached packages' sha256 and the splat's key files, change nothing
#
# Running it accepts the Microsoft license for the CRT/SDK (xwin --accept-license); pre-authorized for
# this build (docs/plan/AUTONOMY.md §1). Pins and hashes: toolchain/PINS.md.
set -euo pipefail

XWIN_VERSION=0.10.0
MANIFEST_VERSION=18           # Visual Studio 2026 channel ("VisualStudio.18.Release/18.11.0+12306.390")
CRT_VERSION=14.51             # MSVC CRT/STL 14.51.36231 (_MSVC_STL_VERSION 145, _MSVC_STL_UPDATE 202604)
SDK_VERSION=10.0.28000        # Windows 11 SDK
XWIN_ROOT=${XWIN_ROOT:-/home/user/opt/xwin}
CACHE=${XWIN_CACHE:-/home/user/opt/xwin-cache-18}
PINNED_MANIFEST="$CACHE/pinned/manifest_18.json"
PINNED_MANIFEST_SHA=b526439707f8c93c8a59636849a9cf995d74bce9e75a9fe9845fd13baade4437
XWIN=${XWIN:-$HOME/.cargo/bin/xwin}

# sha256 of every package xwin downloads for this pin (cache dir dl/).
PKG_SHA=(
  "Microsoft.VC.14.51.CRT.Headers.base.vsix e6d9cc5f0750cbc40a6b2468991c57ed0044fa2e242295a6d51bc02d72502b05"
  "Microsoft.VC.14.51.CRT.x86.Desktop.base.vsix 89c26aad297f1fbf57094c29c33cb56cdf72e13a038db7ec88b63ceb751f9f05"
  "Microsoft.VC.14.51.CRT.x86.Store.base.vsix 263a156aaf004505f44006ff161d96e16349ff53f5f295b5f7de7852ec4e2d6f"
  "ucrt.msi 3b67e52e49a0ddd12536f04482cc0b6fb80672ee434532c16b2702b65e519a1a"
  "Win11SDK_10.0.28000_headers.msi db9eb6aaef919be38fa032b12d3bd00ebc8cd84988a1e28d3fd1a2990b64826d"
  "Win11SDK_10.0.28000_libs_x86.msi 9b2270b048348d6c2a0cd838ff7010c029a26c0c4c17fcd6e4f2efbb501eeb5f"
  "Win11SDK_10.0.28000_store_headers.msi e24134999699e536b37f698223c5098c62497bd99ff996e53cb357010091fed9"
  "Win11SDK_10.0.28000_store_headers_onecoreuap.msi 440fff00ece41c9ce126d4dc6f2be3970ea485aeec85896753682bd5b9647cbe"
  "Win11SDK_10.0.28000_store_libs.msi 5b09fb2cce1a589edb0cabadc8b48bfb276b6be411cdec383015377dc08d6a25"
  "Win11SDK_10.0.28000_uap_headers.msi 397a727ee6551a1e6b8e4a12922ca0a470c02e30ca05b5614063979741ee9092"
)
# Files the toolchain relies on (relative to XWIN_ROOT).
KEY_FILES=(
  "VC/Tools/MSVC/14.51/include/vcruntime.h"
  "VC/Tools/MSVC/14.51/lib/x86/msvcrt.lib"
  "VC/Tools/MSVC/14.51/lib/x86/msvcprt.lib"
  "VC/Tools/MSVC/14.51/lib/x86/vcruntime.lib"
  "Windows Kits/10/Include/10.0.28000/um/windows.h"
  "Windows Kits/10/Include/10.0.28000/um/Windows.h"
  "Windows Kits/10/Include/10.0.28000/shared/d3d9.h"
  "Windows Kits/10/Lib/10.0.28000/ucrt/x86/ucrt.lib"
  "Windows Kits/10/Lib/10.0.28000/um/x86/kernel32.lib"
  "Windows Kits/10/Lib/10.0.28000/um/x86/d3d9.lib"
  "Windows Kits/10/Lib/10.0.28000/um/x86/dsound.lib"
)
STAMP_TEXT="xwin=$XWIN_VERSION manifest=$MANIFEST_VERSION crt=$CRT_VERSION sdk=$SDK_VERSION arch=x86 layout=winsysroot"

FORCE=0 OFFLINE=0 VERIFY=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;; --offline) OFFLINE=1 ;; --verify) VERIFY=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "setup_xwin: unknown option $a" >&2; exit 2 ;;
  esac
done
log() { printf '[setup_xwin] %s\n' "$*"; }
die() { printf '[setup_xwin] ERROR: %s\n' "$*" >&2; exit 1; }

check_cache() {
  local ok=0 line f want got
  for line in "${PKG_SHA[@]}"; do
    f=${line%% *}; want=${line##* }
    if [[ ! -f $CACHE/dl/$f ]]; then log "cache missing: $f"; ok=1; continue; fi
    got=$(sha256sum "$CACHE/dl/$f" | cut -d' ' -f1)
    [[ $got == "$want" ]] || { log "cache sha256 mismatch: $f ($got)"; ok=1; }
  done
  return $ok
}
check_splat() {
  local ok=0 k
  for k in "${KEY_FILES[@]}"; do [[ -e $XWIN_ROOT/$k ]] || { log "splat missing: $k"; ok=1; }; done
  return $ok
}

if [[ $VERIFY == 1 ]]; then
  rc=0
  check_cache && log "cache OK ($CACHE)" || rc=1
  check_splat && log "splat OK ($XWIN_ROOT)" || rc=1
  [[ -f $XWIN_ROOT/.flmod-pin && $(cat "$XWIN_ROOT/.flmod-pin") == "$STAMP_TEXT" ]] && log "stamp OK" || { log "stamp missing/stale"; rc=1; }
  exit $rc
fi

if [[ $FORCE == 0 && -f $XWIN_ROOT/.flmod-pin && $(cat "$XWIN_ROOT/.flmod-pin") == "$STAMP_TEXT" ]] && check_splat; then
  log "up to date: $XWIN_ROOT ($STAMP_TEXT)"
  exit 0
fi

# 1. xwin itself.
if ! [[ -x $XWIN ]] || [[ $("$XWIN" --version 2>/dev/null) != "xwin $XWIN_VERSION" ]]; then
  [[ $OFFLINE == 1 ]] && die "xwin $XWIN_VERSION not installed and --offline"
  log "cargo install xwin --locked --version $XWIN_VERSION"
  cargo install xwin --locked --version "$XWIN_VERSION"
fi

# 2. Pinned channel manifest (a saved copy, so later Microsoft channel updates don't move the pin).
manifest_args=(--manifest-version "$MANIFEST_VERSION")
if [[ -f $PINNED_MANIFEST ]]; then
  got=$(sha256sum "$PINNED_MANIFEST" | cut -d' ' -f1)
  [[ $got == "$PINNED_MANIFEST_SHA" ]] || die "pinned manifest sha256 mismatch ($got)"
  manifest_args=(--manifest "$PINNED_MANIFEST")
else
  [[ $OFFLINE == 1 ]] && die "no pinned manifest at $PINNED_MANIFEST and --offline"
  log "no pinned manifest yet; using the live VS $MANIFEST_VERSION channel (will be pinned after download)"
fi

common=(--accept-license --arch x86 --crt-version "$CRT_VERSION" --sdk-version "$SDK_VERSION"
        --cache-dir "$CACHE" --http-retry 5 "${manifest_args[@]}")
[[ $OFFLINE == 1 ]] && common+=(--https-proxy "http://127.0.0.1:9")   # any network access fails fast

# 3. Download (no-op when the cache is complete), verify hashes, splat into a temp dir, swap in.
"$XWIN" "${common[@]}" download
if [[ ! -f $PINNED_MANIFEST && -f $CACHE/dl/manifest_$MANIFEST_VERSION.json ]]; then
  mkdir -p "$(dirname "$PINNED_MANIFEST")"; cp "$CACHE/dl/manifest_$MANIFEST_VERSION.json" "$PINNED_MANIFEST"
fi
check_cache || die "downloaded packages do not match the pins in this script (see toolchain/PINS.md)"

tmp="$XWIN_ROOT.tmp.$$"
rm -rf "$tmp"
"$XWIN" "${common[@]}" splat --use-winsysroot-style --preserve-ms-arch-notation --copy --output "$tmp"
XWIN_ROOT_SAVED=$XWIN_ROOT; XWIN_ROOT=$tmp; check_splat || die "splat in $tmp is missing key files"; XWIN_ROOT=$XWIN_ROOT_SAVED
printf '%s' "$STAMP_TEXT" > "$tmp/.flmod-pin"
if [[ -e $XWIN_ROOT ]]; then mv "$XWIN_ROOT" "$XWIN_ROOT.old.$$"; fi
mv "$tmp" "$XWIN_ROOT"
rm -rf "$XWIN_ROOT.old.$$"
log "installed $XWIN_ROOT ($STAMP_TEXT)"
