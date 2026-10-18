#!/bin/bash
# Exit 0 (and list them) if any process is using Adam's PLAY prefix; exit 1 if it is idle.
# Detects WINEPREFIX in the environment or a cwd inside the prefix (play.sh does `cd EXE; exec wine-proton Freelancer.exe`,
# where wine's default prefix is NOT used, so we check both). Read-only.
P=/home/user/freelancer/prefix
found=0
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  cwd=$(readlink "$d/cwd" 2>/dev/null) || continue
  envp=$(tr '\0' '\n' < "$d/environ" 2>/dev/null | grep -m1 '^WINEPREFIX=' | cut -d= -f2-)
  case "$cwd/" in "$P"/*) ;; *) case "$envp" in "$P"|"$P/") ;; *) continue;; esac;; esac
  echo "busy: pid $pid $(tr '\0' ' ' < "$d/cmdline" 2>/dev/null | cut -c1-120)"; found=1
done
[ $found = 1 ] && exit 0 || { echo "play prefix idle"; exit 1; }
