#!/bin/bash
# Prove the build never modified Adam's PLAY install (read-only hashing).
#   capture -> local/play-prefix-manifest.sha256   (once, at build start, while the play prefix is idle)
#   verify  -> exit 0 unchanged | 1 changed (diff printed)
# Runtime-written files (logs, ReShade caches/state) are excluded; the save folder is reported for information only.
set -u
P=/home/user/freelancer/prefix
HDE="$P/drive_c/Games/Freelancer HD Edition"
SAVES="$P/drive_c/users/steamuser/Documents/My Games/Freelancer"
OUT=/home/user/freelancer/carrier-mod/local/play-prefix-manifest.sha256
mk() {
  ( cd "$HDE" && find EXE DATA -type f \
      ! -iname '*.log' ! -iname 'ReShade*.ini' ! -iname '*.ini.bak' ! -ipath '*reshade-shaders/Intermediate*' \
      ! -iname 'gls_workaround_temp.txt' -print0 | sort -z | xargs -0 sha256sum )
  sha256sum /home/user/freelancer/play.sh
}
case "${1:-}" in
  capture) mkdir -p "$(dirname "$OUT")"; mk > "$OUT"; echo "captured $(wc -l < "$OUT") entries -> $OUT" ;;
  verify)  [ -f "$OUT" ] || { echo "no manifest at $OUT"; exit 2; }
           d=$(diff <(mk) "$OUT"); rc=$?
           echo "save folder (informational): $(find "$SAVES" -type f 2>/dev/null | wc -l) files, newest: $(find "$SAVES" -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null | sort | tail -1)"
           if [ $rc -eq 0 ]; then echo "play prefix UNCHANGED"; exit 0; else echo "play prefix CHANGED:"; echo "$d" | head -50; exit 1; fi ;;
  *) echo "usage: $0 capture|verify"; exit 2 ;;
esac
