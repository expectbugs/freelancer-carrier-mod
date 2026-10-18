#!/bin/bash
# Dev baselines (REQ-P0-HARNESS-3..6).
#   baseline.sh create A|B [--recreate]   clone the play prefix (only while idle) + idempotent tweaks + BASELINE.json
#   baseline.sh fluf-init                 Track A: first launch in a scratch clone to generate FLUF.yml, then edit it
#   baseline.sh verify A|B                re-check every tweak, file hash, and that the play prefix is unchanged
#   baseline.sh show A|B                  print BASELINE.json
# The play prefix is a clone source only; nothing here ever writes to it.
# create/fluf-init hold $FLMOD_LOCKS/baseline-<T>.lock exclusively; lane.sh and deploy.sh clone under it shared.
source /home/user/freelancer/carrier-mod/tools/env.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/common.sh"
set -u

FLUF_TREE=${FLUF_TREE:-/home/user/freelancer/refs/FLUF-release-nightly-2026-10-16/extracted}
TW="$HARNESS_DIR/lib/baseline_tweaks.py"

clone_play() { # <dest>
  local dest="$1" tmp="$1.cloning"
  assert_owned_prefix "$dest"
  [ -e "$tmp" ] && { rm -rf --one-file-system -- "$tmp"; }
  wait_play_prefix_idle
  hlog "cloning $PLAY_PREFIX -> $dest (cp -a --reflink=always)"
  cp -a --reflink=always "$PLAY_PREFIX" "$tmp" || hdie "reflink clone failed"
  # The play prefix must have stayed idle during the copy, otherwise the clone may be inconsistent.
  if "$FLMOD_REPO/tools/play_prefix_busy.sh" >/dev/null 2>&1; then
    rm -rf --one-file-system -- "$tmp"; hdie "play prefix became busy during the clone; discarded; retry later"
  fi
  mv -- "$tmp" "$dest"
}

cmd_create() {
  local track="$1" recreate="${2:-}" dest
  dest=$(base_prefix "$track")
  assert_owned_prefix "$dest"
  if [ -d "$dest" ] && [ "$recreate" = --recreate ]; then
    lane_wineserver_kill "$dest"
    rm -rf --one-file-system -- "$dest"
  fi
  if [ ! -d "$dest" ]; then
    clone_play "$dest"
    hpy "$TW" play-hashes --track "$track" --prefix "$dest" || hdie "play-hashes failed"
  else
    hlog "$dest exists; re-applying tweaks idempotently (use --recreate for a fresh clone)"
  fi
  hpy "$TW" apply --track "$track" --prefix "$dest" --fluf-tree "$FLUF_TREE" || hdie "tweaks failed"
  [ "$track" = A ] && hlog "Track A: run 'baseline.sh fluf-init' to generate and edit FLUF.yml"
}

# Track A first launch: in a scratch clone of base A (prefix-dev-base-A-init), never in the baseline itself,
# so the baseline carries no runtime state. Waits for EXE/fluf/FLUF.yml, kills that prefix, edits the copy into A.
cmd_fluf_init() {
  local base="$BASE_PREFIX_A" init="$BASE_PREFIX_A-init"
  [ -d "$base" ] || hdie "create A first"
  case "$init" in /home/user/freelancer/prefix-dev-base-A-init) ;; *) hdie "bad init path";; esac
  if [ -d "$init" ]; then WINEPREFIX="$init" wineserver -k >/dev/null 2>&1; WINEPREFIX="$init" timeout 60 wineserver -w; rm -rf --one-file-system -- "$init"; fi
  cp -a --reflink=always "$base" "$init"
  local run="$FLMOD_TESTRUNS/$(utc_stamp)-baselineA-fluf-init"; mkdir -p "$run"
  local hde; hde=$(hde_of "$init")
  rm -rf "$hde/EXE/fluf/FLUF.yml" "$hde/EXE/fluf/config"
  # Launch 1: FLUF writes its default FLUF.yml, then asks (MessageBox "No ship classes") to generate
  # fluf/config/ship_classes.yml; we answer OK (real XTEST input under the global input lock).
  hlog "first launch of baseline A (scratch clone $init); run dir $run"
  fluf_launch "$init" "$run/launch1"; local rc=$?
  [ -s "$hde/EXE/fluf/FLUF.yml" ] || hdie "launch 1: FLUF.yml not generated (rc=$rc, see $run/launch1)"
  cp "$hde/EXE/fluf/FLUF.yml" "$run/FLUF.generated.yml"
  hpy "$TW" fluf-yml --prefix "$base" --generated "$run/FLUF.generated.yml" || hdie "FLUF.yml edit failed"
  # Launch 2: with the edited FLUF.yml (5 modules) so module first-run files are generated too; must reach the menu.
  cp "$(hde_of "$base")/EXE/fluf/FLUF.yml" "$hde/EXE/fluf/FLUF.yml"
  fluf_launch "$init" "$run/launch2"; rc=$?
  [ $rc -eq 0 ] || hdie "launch 2 with the edited FLUF.yml did not reach the main menu (rc=$rc, see $run/launch2)"
  hpy "$TW" fluf-config --prefix "$base" --src-hde "$hde" || hdie "copying FLUF first-run config failed"
  rm -rf --one-file-system -- "$init"
  hlog "FLUF first-run config generated and recorded; evidence in $run"
}

# Launch FL in <prefix>, answer known FLUF first-run dialogs, wait for the main menu. rc 0 menu, 1 timeout, 2 unknown dialog.
fluf_launch() {
  local p="$1" out="$2" hde; hde=$(hde_of "$p"); mkdir -p "$out"; touch "$out/.start"
  # stale logs from the cloned play prefix would satisfy the menu marker before FL truncates them
  rm -f "$(spew_of "$p")" "$p/drive_c/users/steamuser/Documents/My Games/Freelancer/fluf.log"
  ( cd "$hde/EXE" && WINEPREFIX="$p" WINEDEBUG="$RUN_WINEDEBUG" DXVK_LOG_LEVEL=warn \
      DXVK_CONFIG="$RUN_DXVK_CONFIG" exec setsid wine Freelancer.exe -w ) >"$out/wine.log" 2>&1 &
  local t0; t0=$(date +%s); local rc=1 g w title n=0
  local flog="$p/drive_c/users/steamuser/Documents/My Games/Freelancer/fluf.log"
  while [ $(( $(date +%s) - t0 )) -lt 150 ]; do
    g=$(game_pid "$p")
    if [ -n "$g" ]; then
      for w in $(xdotool search --onlyvisible --pid "$g" 2>/dev/null); do
        # check the pid per window: xdotool search does not reliably filter by --pid (harness/NOTES.md N13)
        [ "$(xdotool getwindowpid "$w" 2>/dev/null)" = "$g" ] || continue
        title=$(xdotool getwindowname "$w" 2>/dev/null)
        case "$title" in
          Freelancer|"Default IME"|"") ;;
          "No ship classes")
            n=$((n+1)); timeout -s KILL 10 import -silent -window "$w" "$out/dialog$n.png" 2>/dev/null
            # gated XTEST Return (input lock; focus/workspace/pid checks in lib/xinput.py; refuses rather than guess)
            res=$(flock -w 900 "$FLMOD_LOCKS/input.lock" "$FLMOD_VENV/bin/python" -I "$HARNESS_DIR/lib/xinput.py" \
                  --prefix "$p" --wid "$w" key Return 2>&1)
            echo "$(date -Is) dialog '$title' (wid $w) -> Return: $res" >> "$out/dialogs.txt"
            case "$res" in *input_refused*) rc=3; break 2 ;; esac
            sleep 2 ;;
          *)
            n=$((n+1)); timeout -s KILL 10 import -silent -window "$w" "$out/dialog$n.png" 2>/dev/null
            echo "$(date -Is) UNKNOWN dialog '$title' (wid $w)" >> "$out/dialogs.txt"; rc=2; break 2 ;;
        esac
      done
    fi
    if grep -qs 'Starting single player game' "$flog" "$(spew_of "$p")"; then rc=0; sleep 5; break; fi
    sleep 1
  done
  g=$(game_pid "$p")
  if [ -n "$g" ]; then
    for w in $(xdotool search --onlyvisible --name '^Freelancer$' 2>/dev/null); do
      [ "$(xdotool getwindowpid "$w" 2>/dev/null)" = "$g" ] && { "$HARNESS_DIR/shot.sh" "$w" "$out/menu.png" >/dev/null 2>&1; break; }
    done
  fi
  cp "$(spew_of "$p")" "$out/FLSpew.txt" 2>/dev/null; cp "$flog" "$out/fluf.log" 2>/dev/null
  find "$p/drive_c" -newer "$out/.start" -type f 2>/dev/null | grep -v '/windows/\|/ReShade/' > "$out/new_files.txt"
  WINEPREFIX="$p" wineserver -k >/dev/null 2>&1; WINEPREFIX="$p" timeout 60 wineserver -w
  echo "rc=$rc" > "$out/result.txt"
  return $rc
}

cmd_verify() {
  local track="$1" dest; dest=$(base_prefix "$track")
  [ -d "$dest" ] || { echo "baseline verify $track: FAIL (no prefix $dest)"; return 1; }
  hpy "$TW" verify --track "$track" --prefix "$dest"
}

case "${1:-}" in
  create)    [ $# -ge 2 ] || hdie "usage: baseline.sh create A|B [--recreate]"
             base_prefix "$2" >/dev/null; with_baseline_lock -x "$2" cmd_create "$2" "${3:-}" ;;
  fluf-init) with_baseline_lock -x A cmd_fluf_init ;;
  verify)    [ $# -ge 2 ] || hdie "usage: baseline.sh verify A|B"
             base_prefix "$2" >/dev/null; with_baseline_lock -s "$2" cmd_verify "$2" ;;
  show)      cat "$(base_prefix "${2:?track}")/BASELINE.json" ;;
  *) echo "usage: baseline.sh create A|B [--recreate] | fluf-init | verify A|B | show A|B" >&2; exit 2 ;;
esac
