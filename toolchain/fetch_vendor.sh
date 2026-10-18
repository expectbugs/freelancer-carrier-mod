#!/usr/bin/env bash
# toolchain/fetch_vendor.sh: fetch/extract every pinned third-party build input into $FLMOD_VENDOR.
#
# Usage: toolchain/fetch_vendor.sh [--offline] [--force] [--verify] [--list] [name...]
#   (no names)  process every input
#   --offline   never touch the network; use $FLMOD_VENDOR/.cache and /home/user/freelancer/refs only
#   --force     re-extract even when the destination's pin stamp already matches
#   --verify    read-only and offline: re-hash every available source (local file, cache), check every stamp,
#               and re-hash every installed tree against the manifest written at install time. Writes nothing.
#   --list      print the pin table and exit
#
# Idempotent: each destination gets a `.flmod-pin` stamp (and trees a `.flmod-manifest` of every file's sha256);
# a matching stamp means "already done". Extraction goes to a temp dir next to the destination and is renamed
# into place, so a crash never leaves a half-written tree behind a valid stamp.
#
# $FLMOD_VENDOR is shared by every worktree. P0-TOOLCHAIN is its only writer (CONVENTIONS §1).
# Pins are documented in toolchain/PINS.md; keep the two in sync.
set -euo pipefail

FLMOD_VENDOR=${FLMOD_VENDOR:-/home/user/freelancer/carrier-mod/vendor}
FLMOD_REFS=${FLMOD_REFS:-/home/user/freelancer/refs}
CACHE="$FLMOD_VENDOR/.cache/dl"

# name | kind | source (url or local path) | sha256 or commit | dest (relative to FLMOD_VENDOR) | pin label
# kind: tarxz-local  = local .tar.xz, sha256 checked, extracted as-is; FALLBACK_URL_<name> if the file is missing
#       tgz-url      = downloaded .tar.gz (cached), sha256 checked, single top dir flattened
#       file-url     = downloaded single file (cached), sha256 checked, placed at dest
#       vsix-url     = downloaded .vsix/.zip (cached), sha256 checked, VSIX_SUBDIR_<name> extracted flat
#       git-local    = `git archive <commit>` of a local clone; falls back to FALLBACK_URL_<name>
PINS=(
  "FLUF|tarxz-local|$FLMOD_REFS/FLUF-release-nightly-2026-10-16/FLUF.tar.xz|74a8147de6a957de67f910cc16b951e9047e68a8a848087168bd515f7ecd3a65|FLUF|nightly-2026-10-16-03-03 (FLUF 627ea2c)"
  "FLUF-stable|tarxz-local|$FLMOD_REFS/FLUF-release-stable-2026-03-28/FLUF.tar.xz|bd5635f2bcaa625258d9a0f7867c3151c6f29017491d3c83524d7841d830b390|FLUF-stable|stable-2026-03-28-18-16"
  "FLSDK|git-local|$FLMOD_REFS/FLUF/vendor/FLSDK|ae8c85781e06dfe3b23546822d67bb07767670cd|FLSDK|commit ae8c857"
  "reflect-cpp|tgz-url|https://github.com/getml/reflect-cpp/archive/6bba1e2c4fa8de704c88d3f1712c157bbb6edc23.tar.gz|b8310d97a85ff8d6edb1de81350562d5bb20ad6fc29836d342cd77f7b57d0056|reflect-cpp|commit 6bba1e2c4fa8de704c88d3f1712c157bbb6edc23"
  "magic_enum|tgz-url|https://github.com/Neargye/magic_enum/releases/download/v0.9.8/magic_enum-v0.9.8.tar.gz|88709dc8a9697168a75e039470d73ed0cffbc17567976eb5e096f946a2c0d521|magic_enum|v0.9.8"
  "imgui|tgz-url|https://github.com/ocornut/imgui/archive/b48d1afbe8ee8b238e2961dc363a949dd7304e23.tar.gz|747c5a465a05c4ef5b4a09e2e0e3d0ce2bc76b31420f0f5af33df470907cf893|imgui|v1.92.9b-docking (b48d1af)"
  "minhook|tgz-url|https://github.com/TsudaKageyu/minhook/archive/c3fcafdc10146beb5919319d0683e44e3c30d537.tar.gz|31757833475be039c16359d4e276e718db6ba2ba61a6b870053a112106015822|minhook|v1.3.4 (c3fcafd)"
  "doctest|tgz-url|https://github.com/doctest/doctest/archive/2d0a9359a60c51affe2a9bebb1be1dca47868151.tar.gz|e64542c4ea68e9f381ccf6eae924cfdd652567c87c142d76fe92644fb4608149|doctest|v2.5.3 (2d0a935)"
  "nlohmann_json|file-url|https://github.com/nlohmann/json/releases/download/v3.11.3/json.hpp|9bea4c8066ef4a1c206b2be5a36302f8926f7fdc6087af5d20b417d0cf103ea6|nlohmann_json/include/nlohmann/json.hpp|v3.11.3"
  "nlohmann_json_fwd|file-url|https://github.com/nlohmann/json/releases/download/v3.11.3/json_fwd.hpp|5cefbba751baf5243033fd894c70be9b37103d64b3d3a959e4173197d71137b9|nlohmann_json/include/nlohmann/json_fwd.hpp|v3.11.3"
  "msvc-redist-x86|vsix-url|https://download.visualstudio.microsoft.com/download/pr/3984a6ef-2ffc-4c07-962e-bf9e9b862819/f13add6a0613d85b1ae6fbb52d9592dc1df6b43791ea375f2c32dda605e7aaec/Microsoft.VC.14.51.CRT.Redist.X86.base.vsix|f13add6a0613d85b1ae6fbb52d9592dc1df6b43791ea375f2c32dda605e7aaec|msvc-redist/x86|MSVC CRT redist 14.51.36231 x86 (package 14.51.36247)"
)
FALLBACK_URL_FLSDK="https://codeberg.org/TheStarport/FLSDK"
FALLBACK_URL_FLUF="https://codeberg.org/TheStarport/FLUF/releases/download/nightly-2026-10-16-03-03/FLUF.tar.xz"
FALLBACK_URL_FLUF_stable="https://codeberg.org/TheStarport/FLUF/releases/download/stable-2026-03-28-18-16/FLUF.tar.xz"
VSIX_SUBDIR_msvc_redist_x86="Contents/VC/Redist/MSVC/14.51.36231/x86/Microsoft.VC145.CRT"

OFFLINE=0 FORCE=0 VERIFY=0 LIST=0
WANT=()
for a in "$@"; do
  case "$a" in
    --offline) OFFLINE=1 ;;
    --force) FORCE=1 ;;
    --verify) VERIFY=1 ;;
    --list) LIST=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    -*) echo "fetch_vendor: unknown option $a" >&2; exit 2 ;;
    *) WANT+=("$a") ;;
  esac
done

log() { printf '[fetch_vendor] %s\n' "$*"; }
die() { printf '[fetch_vendor] ERROR: %s\n' "$*" >&2; exit 1; }

if [[ $LIST == 1 ]]; then
  printf '| %-18s | %-11s | %-44s | %s\n' name kind pin source
  for p in "${PINS[@]}"; do
    IFS='|' read -r name kind src hash dest label <<<"$p"
    printf '| %-18s | %-11s | %-44s | %s\n' "$name" "$kind" "$label" "$src"
  done
  exit 0
fi

wanted() {
  [[ ${#WANT[@]} == 0 ]] && return 0
  local w; for w in "${WANT[@]}"; do [[ $w == "$1" ]] && return 0; done; return 1
}

sha_of() { sha256sum "$1" | cut -d' ' -f1; }
stamp_text() { printf '%s|%s|%s\n' "$1" "$2" "$3"; }   # name|hash|label
var_suffix() { local v=${1//-/_}; printf '%s' "${v//./_}"; }

# cache_path <url> -> the cache file name used for that URL
cache_path() {
  local url=$1 base
  base=$(basename "$url")
  # GitHub archive names are bare <sha>.tar.gz: prefix with the repo name for readability.
  case "$url" in
    https://github.com/*/archive/*) base="$(echo "$url" | cut -d/ -f5)-$base" ;;
    https://github.com/nlohmann/json/releases/download/*) base="nlohmann-json-$(echo "$url" | cut -d/ -f8)-$base" ;;
    https://codeberg.org/TheStarport/FLUF/releases/download/*) base="FLUF-$(echo "$url" | cut -d/ -f8)-$base" ;;
  esac
  printf '%s\n' "$CACHE/$base"
}

# fetch_cached <url> <sha256> -> prints the cached path (downloads unless --offline)
fetch_cached() {
  local url=$1 sha=$2 f
  f=$(cache_path "$url")
  if [[ -f $f ]] && [[ $(sha_of "$f") == "$sha" ]]; then
    printf '%s\n' "$f"; return 0
  fi
  [[ $OFFLINE == 1 ]] && die "offline and $f is missing or has the wrong sha256"
  mkdir -p "$CACHE"
  log "downloading $url" >&2
  curl -sSfL --retry 3 -o "$f.part" "$url" || die "download failed: $url"
  local got; got=$(sha_of "$f.part")
  [[ $got == "$sha" ]] || { rm -f "$f.part"; die "sha256 mismatch for $url: got $got want $sha"; }
  mv -f "$f.part" "$f"
  printf '%s\n' "$f"
}

# write_manifest <dir>: sha256 of every file (relative paths, sorted), excluding the stamp and manifest
write_manifest() {
  ( cd "$1" && find . -type f ! -name .flmod-pin ! -name .flmod-manifest -print0 | LC_ALL=C sort -z \
      | xargs -0 -r sha256sum ) >"$1/.flmod-manifest"
}
check_manifest() {   # check_manifest <dir> -> 0 if the tree matches its manifest exactly
  local d=$1
  [[ -f $d/.flmod-manifest ]] || { log "VERIFY FAIL: $d has no .flmod-manifest (re-extract with --force)"; return 1; }
  local now
  now=$( cd "$d" && find . -type f ! -name .flmod-pin ! -name .flmod-manifest -print0 | LC_ALL=C sort -z \
           | xargs -0 -r sha256sum )
  if [[ $now != "$(cat "$d/.flmod-manifest")" ]]; then
    log "VERIFY FAIL: $d differs from its manifest:"
    diff <(cat "$d/.flmod-manifest") <(printf '%s\n' "$now") | head -n 10 | sed 's/^/    /'
    return 1
  fi
  return 0
}

install_tree() {   # install_tree <tmpdir> <destdir>: atomically replace dest with tmp
  local tmp=$1 dest=$2
  if [[ -e $dest ]]; then
    local old="$dest.old.$$"
    mv "$dest" "$old"
    mv "$tmp" "$dest"
    rm -rf "$old"
  else
    mkdir -p "$(dirname "$dest")"
    mv "$tmp" "$dest"
  fi
}

flatten_single_dir() {   # if dir holds exactly one entry and it is a directory, hoist its contents
  local d=$1 entries
  mapfile -t entries < <(find "$d" -mindepth 1 -maxdepth 1)
  if [[ ${#entries[@]} == 1 && -d ${entries[0]} ]]; then
    local inner="${entries[0]}" hold="$d.inner.$$"
    mv "$inner" "$hold"
    rmdir "$d"
    mv "$hold" "$d"
  fi
}

verify_one() {
  local name=$1 kind=$2 src=$3 hash=$4 dest=$5 label=$6 stampfile=$7 want_stamp=$8
  local ok=1 fb sfx
  sfx=$(var_suffix "$name")
  case "$kind" in
    tarxz-local)
      if [[ -f $src ]]; then
        [[ $(sha_of "$src") == "$hash" ]] || { log "VERIFY FAIL $name: $src sha256 mismatch"; ok=0; }
      else
        fb="FALLBACK_URL_$sfx"; fb=${!fb:-}
        local c=""; [[ -n $fb ]] && c=$(cache_path "$fb")
        if [[ -n $c && -f $c ]]; then
          [[ $(sha_of "$c") == "$hash" ]] || { log "VERIFY FAIL $name: cache $c sha256 mismatch"; ok=0; }
        else
          log "VERIFY WARN $name: source $src not present (offline verify cannot re-hash it)"
        fi
      fi ;;
    tgz-url|file-url|vsix-url)
      local c; c=$(cache_path "$src")
      if [[ -f $c ]]; then
        [[ $(sha_of "$c") == "$hash" ]] || { log "VERIFY FAIL $name: cache $c sha256 mismatch"; ok=0; }
      else
        log "VERIFY WARN $name: cache file $c missing (offline verify cannot re-hash the download)"
      fi ;;
    git-local)
      if [[ -e $src/.git ]] && git -C "$src" cat-file -e "$hash^{commit}" 2>/dev/null; then :; else
        log "VERIFY WARN $name: commit $hash not available in $src"
      fi ;;
  esac
  if [[ -f $stampfile && $(cat "$stampfile") == "$want_stamp" ]]; then :; else
    log "VERIFY FAIL $name: stamp missing or stale ($stampfile)"; ok=0
  fi
  if [[ $kind == file-url ]]; then
    [[ -f $dest && $(sha_of "$dest") == "$hash" ]] || { log "VERIFY FAIL $name: installed file missing or modified"; ok=0; }
  elif [[ -d $dest ]]; then
    check_manifest "$dest" || ok=0
  else
    log "VERIFY FAIL $name: $dest missing"; ok=0
  fi
  [[ $ok == 1 ]] && log "VERIFY OK   $name ($label)"
  return $(( ok == 1 ? 0 : 1 ))
}

process() {
  local name=$1 kind=$2 src=$3 hash=$4 dest_rel=$5 label=$6
  local dest="$FLMOD_VENDOR/$dest_rel" sfx
  sfx=$(var_suffix "$name")
  local stampfile want_stamp
  if [[ $kind == file-url ]]; then stampfile="$dest.flmod-pin"; else stampfile="$dest/.flmod-pin"; fi
  want_stamp=$(stamp_text "$name" "$hash" "$label")

  if [[ $VERIFY == 1 ]]; then
    verify_one "$name" "$kind" "$src" "$hash" "$dest" "$label" "$stampfile" "$want_stamp"
    return
  fi

  if [[ $FORCE == 0 && -f $stampfile && $(cat "$stampfile") == "$want_stamp" ]]; then
    if [[ $kind == file-url || -f $dest/.flmod-manifest ]]; then
      log "up to date: $name ($label)"
      return 0
    fi
    log "$name: stamp ok but no manifest yet; re-extracting"
  fi

  local tmp="$FLMOD_VENDOR/.tmp-$name.$$"
  rm -rf "$tmp"; mkdir -p "$tmp"
  case "$kind" in
    tarxz-local)
      local tarball=$src
      if [[ ! -f $tarball ]]; then
        local fb="FALLBACK_URL_$sfx"; fb=${!fb:-}
        [[ -n $fb ]] || die "$name: missing $src and no fallback URL"
        tarball=$(fetch_cached "$fb" "$hash")
      fi
      local got; got=$(sha_of "$tarball")
      [[ $got == "$hash" ]] || die "$name: sha256 mismatch for $tarball: got $got want $hash"
      log "extracting $name from $tarball"
      tar -xJf "$tarball" -C "$tmp"
      ;;
    tgz-url)
      local f; f=$(fetch_cached "$src" "$hash")
      log "extracting $name from $(basename "$f")"
      tar -xzf "$f" -C "$tmp"
      flatten_single_dir "$tmp"
      ;;
    vsix-url)
      local f sub; f=$(fetch_cached "$src" "$hash")
      sub="VSIX_SUBDIR_$sfx"; sub=${!sub:-}
      [[ -n $sub ]] || die "$name: no VSIX_SUBDIR_$sfx"
      log "extracting $name ($sub) from $(basename "$f")"
      unzip -q -j "$f" "$sub/*" -d "$tmp"
      ;;
    file-url)
      local f; f=$(fetch_cached "$src" "$hash")
      rm -rf "$tmp"
      mkdir -p "$(dirname "$dest")"
      [[ -e $dest ]] && chmod u+w "$dest" 2>/dev/null || true
      cp -f "$f" "$dest.part.$$"
      mv -f "$dest.part.$$" "$dest"
      printf '%s' "$want_stamp" > "$stampfile"
      log "installed $name -> $dest_rel ($label)"
      return 0
      ;;
    git-local)
      local done=0
      if [[ -e $src/.git ]] && git -C "$src" cat-file -e "$hash^{commit}" 2>/dev/null; then
        log "git archive $name @ $hash from $src"
        git -C "$src" archive --format=tar "$hash" | tar -xf - -C "$tmp"
        done=1
      fi
      if [[ $done == 0 ]]; then
        local fb="FALLBACK_URL_$sfx"; fb=${!fb:-}
        [[ -n $fb ]] || die "$name: commit $hash not in $src and no fallback"
        [[ $OFFLINE == 1 ]] && die "$name: commit $hash not in $src and --offline"
        local clone="$FLMOD_VENDOR/.cache/git-$name"
        rm -rf "$clone"
        log "cloning $fb for $name @ $hash"
        git clone -q "$fb" "$clone"
        git -C "$clone" cat-file -e "$hash^{commit}" || die "$name: $hash not found in $fb"
        git -C "$clone" archive --format=tar "$hash" | tar -xf - -C "$tmp"
      fi
      ;;
    *) die "$name: unknown kind $kind" ;;
  esac
  printf '%s' "$want_stamp" > "$tmp/.flmod-pin"
  write_manifest "$tmp"
  # Vendor trees are read-only inputs for every worktree.
  chmod -R a-w "$tmp" 2>/dev/null || true
  chmod u+w "$tmp"
  if [[ -e $dest ]]; then chmod -R u+w "$dest"; fi
  install_tree "$tmp" "$dest"
  chmod u-w "$dest" 2>/dev/null || true
  log "installed $name -> $dest_rel ($label)"
}

[[ $VERIFY == 1 ]] || mkdir -p "$FLMOD_VENDOR"
rc=0
for p in "${PINS[@]}"; do
  IFS='|' read -r name kind src hash dest label <<<"$p"
  wanted "$name" || continue
  process "$name" "$kind" "$src" "$hash" "$dest" "$label" || rc=1
done
exit $rc
