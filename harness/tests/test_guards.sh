#!/bin/bash
# REQ-P0-HARNESS-1: regression test for the orchestrator-owned wine guards (tools/bin/_wineguard).
# Never modifies the guards. Asserts exit 97 for protected/invalid prefixes and success for an existing build prefix.
# Usage: harness/tests/test_guards.sh [existing-allowed-prefix]
source /home/user/freelancer/carrier-mod/tools/env.sh
set -u
G="$FLMOD_REPO/tools/bin"
pass=0; fail=0
ok()  { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; fail=$((fail+1)); }

expect97() { # <label> <tool> <WINEPREFIX value or __UNSET__> [args...]
  local label="$1" tool="$2" wp="$3"; shift 3
  local rc
  if [ "$wp" = __UNSET__ ]; then
    env -u WINEPREFIX "$G/$tool" "$@" >/dev/null 2>&1; rc=$?
  else
    WINEPREFIX="$wp" "$G/$tool" "$@" >/dev/null 2>&1; rc=$?
  fi
  [ $rc -eq 97 ] && ok "$label ($tool) -> 97" || bad "$label ($tool) -> rc=$rc (want 97)"
}

# PATH resolution: every guarded tool name must resolve to tools/bin first.
for t in wine wine64 wineserver winedbg wineboot winecfg wine-proton regedit msiexec; do
  [ "$(command -v "$t")" = "$G/$t" ] && ok "PATH $t -> guard" || bad "PATH $t -> $(command -v "$t")"
done

for tool in wine winedbg wineserver wineboot; do
  expect97 "unset"                 "$tool" __UNSET__ --version
  expect97 "empty"                 "$tool" "" --version
  expect97 "sentinel"              "$tool" /home/user/freelancer/prefix-UNSET --version
  expect97 "play prefix"           "$tool" /home/user/freelancer/prefix --version
  expect97 "play prefix/"          "$tool" /home/user/freelancer/prefix/ --version
  expect97 "~/.wine"               "$tool" /home/user/.wine --version
  expect97 "lane/../prefix"        "$tool" /home/user/freelancer/prefix-lane-1/../prefix --version
  expect97 "non-existent lane-99"  "$tool" /home/user/freelancer/prefix-lane-99 --version
done
# The 2026-10-17 incident command (R4 Incidents): winedbg --help with no prefix.
expect97 "incident winedbg --help" winedbg /home/user/freelancer/prefix-UNSET --help
# Relative path that resolves to the play prefix.
( cd /home/user/freelancer && WINEPREFIX=prefix "$G/wine" --version >/dev/null 2>&1; [ $? -eq 97 ] ) && ok "relative 'prefix' -> 97" || bad "relative 'prefix' not refused"
# Every guard symlink refuses the play prefix.
for t in "$G"/*; do
  n=$(basename "$t"); [ "$n" = _wineguard ] && continue
  WINEPREFIX=/home/user/freelancer/prefix "$t" --version >/dev/null 2>&1; rc=$?
  [ $rc -eq 97 ] && ok "symlink $n refuses play prefix" || bad "symlink $n rc=$rc"
done
# A symlink named like a lane but pointing at the play prefix must be refused (realpath resolves it).
SYM=/home/user/freelancer/prefix-lane-guardtest-symlink
rm -f "$SYM"; ln -s /home/user/freelancer/prefix "$SYM"
expect97 "lane-named symlink -> play prefix" wine "$SYM" --version
rm -f "$SYM"

# Success for an existing allowed prefix: wine --version exits before touching the prefix.
ALLOWED="${1:-}"
if [ -z "$ALLOWED" ]; then
  for c in /home/user/freelancer/prefix-lane-[0-9]* /home/user/freelancer/prefix-dev-base-B /home/user/freelancer/prefix-dev-base-A; do
    [ -d "$c/drive_c" ] && { ALLOWED="$c"; break; }
  done
fi
if [ -n "$ALLOWED" ]; then
  out=$(WINEPREFIX="$ALLOWED" wine --version 2>&1); rc=$?
  if [ $rc -eq 0 ] && echo "$out" | grep -q 'Proton-11.0'; then ok "allowed $ALLOWED: wine --version = $out"; else bad "allowed $ALLOWED: rc=$rc out=$out"; fi
else
  echo "SKIP allowed-prefix success case: no existing lane/baseline prefix yet"
fi

# Gap report (informational, not a failure of the guards themselves): wine launchers on PATH that are not guarded.
for t in notepad winefile winemine; do
  r=$(command -v "$t" 2>/dev/null) || continue
  case "$r" in "$G"/*) ;; *) echo "GAP $t resolves to $r (unguarded launcher; see harness/NOTES.md)";; esac
done

echo "test_guards: pass=$pass fail=$fail"
[ $fail -eq 0 ]
