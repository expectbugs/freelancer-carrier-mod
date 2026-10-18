#!/bin/bash
# Exit 0 (and list them) if any process is using Adam's PLAY prefix; exit 1 if it is idle.
# Detects WINEPREFIX in the environment or a cwd inside the prefix (play.sh does `cd EXE; exec wine-proton Freelancer.exe`,
# where wine's default prefix is NOT used, so we check both). Read-only.
P=/home/user/freelancer/prefix
found=0
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  cwd=$(readlink "$d/cwd" 2>/dev/null) || continue
  envp=$(tr '\0' '\n' 2>/dev/null < "$d/environ" | grep -m1 '^WINEPREFIX=' | cut -d= -f2-)
  # normalise like the wine guards do (realpath -m), so //, /./ and x/.. spellings can't hide a user
  [ -n "$envp" ] && envp=$(realpath -m -- "$envp" 2>/dev/null)
  case "$cwd/" in "$P"/*) ;; *) [ "$envp" = "$P" ] || continue;; esac
  echo "busy: pid $pid $(tr '\0' ' ' 2>/dev/null < "$d/cmdline" | cut -c1-120)"; found=1
done
[ $found = 1 ] && exit 0 || { echo "play prefix idle"; exit 1; }
