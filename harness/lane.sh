#!/bin/bash
# Lanes: exclusive disposable prefixes + window slots (REQ-P0-HARNESS-7, CONVENTIONS §7, TESTING §Lanes).
#
#   lane.sh acquire [--track A|B] [--input] [--perf] [--lane N] [--owner ID] [--owner-pid P] [--wait S] [--ttl S] [--keep-prefix]
#                   [--display x11|vdesk] [--renderer auto|dxvk|wined3d|wined3d-sw]
#       -> prints `export ...` lines (LANE, WINEPREFIX, HDE, FL_SAVEDIR, FL_DEVBRIDGE_DIR, LANE_X, LANE_Y,
#          FLCOPILOT_PORT, LANE_TRACK, LANE_INPUT, LANE_HEADLESS, LANE_DISPLAY, LANE_RENDERER, LANE_TOKEN).
#          Use: eval "$(harness/lane.sh acquire ...)"
#       Without --lane it picks a free lane among 1..LANES, or 1..min(LANES, LANES_SW) when the renderer (--renderer,
#       else $FLMOD_RENDERER, else auto) resolves to wined3d-sw (NOTES.md N11). run.sh uses LANE_RENDERER by default.
#       --display x11|vdesk (default: DISPLAY_MODE_A / DISPLAY_MODE_B in config.sh). x11 = the game window directly
#       on :0; vdesk = a per-lane Wine virtual desktop window "lane<N> - Wine Desktop" (1280x720) on :0, needed by
#       Track A because FLUF sizes the game to the desktop (NOTES.md N2). gamescope (nested/headless) is banned on this
#       host (D103, NOTES.md N8); --headless is refused.
#   lane.sh release <token>      scoped wineserver -k/-w for that lane, then frees its locks
#   lane.sh env <N>              re-print the export lines of a held lane
#   lane.sh status               list lanes, owners, holders
#   lane.sh reap                 free locks whose holder or owner process is dead (and kill that lane's wineserver)
#
# Locks live in $FLMOD_LOCKS (absolute), so every worktree contends on the same files. The lock is held by a
# setsid-detached `sleep` (lib/lock_holder.sh) and expires by itself after --ttl seconds (default LOCK_TTL_S = 4 h).
# Pass a longer --ttl for long soaks: run.sh aborts a run (verdict FAIL lane_lost) the moment the holder is gone,
# because another acquirer could then recreate the prefix under the running game.
# Renderer classes never mix (NOTES.md N14/N17): while any lane runs wined3d-sw (CPU), no DXVK/GPU lane is handed
# out, and vice versa; the acquirer waits (render.gate + render-<class>.lock, lib/lock_holder.sh).
source /home/user/freelancer/carrier-mod/tools/env.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/common.sh"
set -u
mkdir -p "$FLMOD_LOCKS"

owner_pid_guess() { # nearest ancestor that is a Claude Code process, else our parent
  local p=$PPID c
  while [ -n "$p" ] && [ "$p" -gt 1 ]; do
    c=$(cat "/proc/$p/comm" 2>/dev/null) || break
    [ "$c" = claude ] && { echo "$p"; return; }
    p=$(awk '/^PPid:/{print $2}' "/proc/$p/status" 2>/dev/null)
  done
  echo "$PPID"
}

kv() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1; }
alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
holder_is_ours() { # <pid> [start]: the pid is still the `sleep <ttl>` lock_holder exec'd (guards pid reuse)
  [ "$(cat "/proc/$1/comm" 2>/dev/null)" = sleep ] || return 1
  tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -qE '^sleep [0-9]+ ?$' || return 1
  [ -z "${2:-}" ] || [ "$(proc_start "$1")" = "$2" ]
}

print_env() { # <N>
  cat "$FLMOD_LOCKS/lane-$1.env"
}

write_env() { # <N> <track> <input> <headless> <token> <display> <renderer>
  local n=$1 p hde xy
  p=$(lane_prefix "$n"); hde=$(hde_of "$p"); xy=($(lane_slot "$n"))
  {
    echo "export LANE=$n"
    echo "export WINEPREFIX='$p'"
    echo "export HDE='$hde'"
    echo "export FL_SAVEDIR='$hde/SAVE/Accts/SinglePlayer'"
    echo "export FL_DEVBRIDGE_DIR='$hde/SAVE/devbridge'"
    echo "export LANE_X=${xy[0]}"
    echo "export LANE_Y=${xy[1]}"
    echo "export FLCOPILOT_PORT=$((FLCOPILOT_PORT_BASE + n))"
    echo "export FLCOPILOT_FORCE_TEST_PROFILE=1"   # sidecar refuses its live profile on lanes (P0-SIDECAR)
    echo "export LANE_TRACK=$2"
    echo "export LANE_INPUT=$3"
    echo "export LANE_HEADLESS=$4"
    echo "export LANE_DISPLAY=$6"
    echo "export LANE_RENDERER=$7"
    echo "export LANE_TOKEN=$5"
  } > "$FLMOD_LOCKS/lane-$n.env"
}

recreate_prefix() { # <N> <track>
  local n=$1 track=$2 p base pid
  p=$(lane_prefix "$n"); base=$(base_prefix "$track")
  assert_owned_prefix "$p"
  [ -f "$base/BASELINE.json" ] || hdie "baseline $track missing ($base); run harness/baseline.sh create $track"
  if [ -e "$p" ]; then
    lane_wineserver_kill "$p"
    for pid in $(prefix_pids "$p"); do   # only Wine processes of this lane prefix (never e.g. a shell with the env)
      is_wine_pid "$pid" && kill -9 "$pid" 2>/dev/null
    done
    rm -rf --one-file-system -- "$p" || hdie "could not remove $p"
  fi
  with_baseline_lock -s "$track" cp -a --reflink=always "$base" "$p" || hdie "reflink clone $base -> $p failed"
  mkdir -p "$(hde_of "$p")/SAVE/Accts/SinglePlayer" "$(hde_of "$p")/SAVE/devbridge"
}

cmd_acquire() {
  local track=${FLMOD_TRACK:-B} input=0 perf=normal lane="" owner=${FLMOD_AGENT_ID:-unknown} wait_s=7200
  local ttl=$LOCK_TTL_S headless=0 keep=0 owner_pid="" display="" renderer=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --track) track=$2; shift ;;
      --input) input=1 ;;
      --perf) perf=perf ;;
      --lane) lane=$2; shift ;;
      --owner) owner=$2; shift ;;
      --owner-pid) owner_pid=$2; shift ;;
      --wait) wait_s=$2; shift ;;
      --ttl) ttl=$2; shift ;;
      --headless) display=headless ;;
      --display) display=$2; shift ;;
      --renderer) renderer=$2; shift ;;
      --keep-prefix) keep=1 ;;
      *) hdie "acquire: unknown option $1" 2 ;;
    esac; shift
  done
  case "$track" in A|B) ;; *) hdie "--track must be A or B" 2 ;; esac
  if [ -z "$display" ]; then
    if [ "$track" = A ]; then display=$DISPLAY_MODE_A; else display=$DISPLAY_MODE_B; fi
  fi
  case "$display" in
    x11|vdesk) ;;
    *) hdie "--display $display: only x11|vdesk (gamescope lanes are banned on this host, D103, NOTES.md N8)" 2 ;;
  esac
  renderer=$(resolve_renderer "$renderer") || exit $?
  local lanes
  if [ -n "$lane" ]; then
    [[ "$lane" =~ ^[0-9]+$ ]] && [ "$lane" -ge 1 ] && [ "$lane" -le "$LANES_MAX" ] || hdie "--lane must be 1..$LANES_MAX" 2
    lanes=$lane
  else
    lanes=$(seq -s ' ' 1 "$(effective_lanes "$renderer")")
  fi
  # status file: acquirer pid and wait budget in the name, so reap can tell a live acquisition from a stale one
  local st="$FLMOD_LOCKS/.acq-$$-$wait_s-$RANDOM.status" rclass=gpu
  [ "$renderer" = wined3d-sw ] && rclass=sw
  rm -f "$st"
  setsid -f bash "$HARNESS_DIR/lib/lock_holder.sh" "$st" "$FLMOD_LOCKS" "$perf" "$input" "$lanes" "$wait_s" "$ttl" \
    "$rclass" </dev/null >/dev/null 2>&1
  local t0; t0=$(date +%s)
  while [ ! -s "$st" ]; do
    [ $(( $(date +%s) - t0 )) -gt $(( wait_s + 30 )) ] && hdie "lock holder did not report within $((wait_s+30)) s"
    sleep 0.2
  done
  local res; res=$(cat "$st"); rm -f "$st"
  case "$res" in OK*) ;; *) hdie "acquire failed: $res" 3 ;; esac
  local n hpid
  n=$(sed -n 's/.*lane=\([0-9]*\).*/\1/p' <<<"$res"); hpid=$(sed -n 's/.*pid=\([0-9]*\).*/\1/p' <<<"$res")
  local token="lane$n-$hpid-$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  {
    echo "lane=$n"; echo "token=$token"; echo "owner=$owner"; echo "holder_pid=$hpid"; echo "holder_start=$(proc_start "$hpid")"
    echo "owner_pid=${owner_pid:-$(owner_pid_guess)}"; echo "caller_pid=$$"; echo "started=$(date -Is)"; echo "ttl_s=$ttl"
    echo "track=$track"; echo "input=$input"; echo "perf=$([ "$perf" = perf ] && echo 1 || echo 0)"; echo "headless=$headless"; echo "display=$display"; echo "renderer=$renderer"
    echo "cwd=$PWD"
  } > "$FLMOD_LOCKS/lane-$n.owner"
  if [ "$keep" = 1 ] && [ -f "$(lane_prefix "$n")/BASELINE.json" ] && \
     [ "$(sed -n 's/.*"track": "\([AB]\)".*/\1/p' "$(lane_prefix "$n")/BASELINE.json" | head -1)" = "$track" ]; then
    hlog "lane $n: keeping existing prefix (--keep-prefix)"
    lane_wineserver_kill "$(lane_prefix "$n")"
  else
    recreate_prefix "$n" "$track" || { kill "$hpid" 2>/dev/null; rm -f "$FLMOD_LOCKS/lane-$n.owner"; hdie "prefix recreate failed"; }
  fi
  write_env "$n" "$track" "$input" "$headless" "$token" "$display" "$renderer"
  hlog "acquired lane $n (track $track, display $display, renderer $renderer, input=$input, perf=$perf, holder pid $hpid, ttl ${ttl}s)"
  print_env "$n"
}

cleanup_lane() { # <N> [holder_pid] [holder_start]  (release: the caller owns the lane)
  local n=$1 hp=${2:-} hs=${3:-}
  lane_wineserver_kill "$(lane_prefix "$n")"
  if [ -n "$hp" ] && alive "$hp" && holder_is_ours "$hp" "$hs"; then kill "$hp" 2>/dev/null; fi
  rm -f "$FLMOD_LOCKS/lane-$n.owner" "$FLMOD_LOCKS/lane-$n.env"
}

# reap one lane: only while holding lane-N.lock ourselves (flock -n), so a concurrent acquirer that already took the
# lane (and is about to write its owner file) is never touched (review r1 M2). 0 = cleaned, 1 = left alone.
reap_lane() { # <N> [holder_pid_to_kill] [holder_start]
  local n=$1 hp=${2:-} hs=${3:-} fd i
  if [ -n "$hp" ] && alive "$hp" && holder_is_ours "$hp" "$hs"; then
    kill "$hp" 2>/dev/null
    for i in $(seq 1 50); do alive "$hp" || break; sleep 0.1; done
  fi
  exec {fd}>"$FLMOD_LOCKS/lane-$n.lock"
  if ! flock -n "$fd"; then exec {fd}>&-; return 1; fi
  lane_wineserver_kill "$(lane_prefix "$n")"
  rm -f "$FLMOD_LOCKS/lane-$n.owner" "$FLMOD_LOCKS/lane-$n.env"
  flock -u "$fd"; exec {fd}>&-
  return 0
}

cmd_release() {
  local token=${1:-${LANE_TOKEN:-}}
  [ -n "$token" ] || hdie "usage: lane.sh release <token>" 2
  local f
  for f in "$FLMOD_LOCKS"/lane-*.owner; do
    [ -f "$f" ] || continue
    if [ "$(kv "$f" token)" = "$token" ]; then
      local n; n=$(kv "$f" lane)
      cleanup_lane "$n" "$(kv "$f" holder_pid)" "$(kv "$f" holder_start)"
      hlog "released lane $n"
      return 0
    fi
  done
  hdie "release: no lane holds token $token" 4
}

cmd_status() {
  local n f any=0
  for n in $(seq 1 "$LANES_MAX"); do
    f="$FLMOD_LOCKS/lane-$n.owner"
    [ -f "$f" ] || continue
    any=1
    local hp; hp=$(kv "$f" holder_pid)
    printf 'lane %s: owner=%s track=%s input=%s perf=%s holder=%s(%s) owner_pid=%s(%s) since %s\n' \
      "$n" "$(kv "$f" owner)" "$(kv "$f" track)" "$(kv "$f" input)" "$(kv "$f" perf)" "$hp" \
      "$(alive "$hp" && echo alive || echo dead)" "$(kv "$f" owner_pid)" "$(alive "$(kv "$f" owner_pid)" && echo alive || echo dead)" \
      "$(kv "$f" started)"
  done
  [ $any = 0 ] && echo "no lanes held (LANES=$LANES, LANES_SW=$LANES_SW)"
  return 0
}

cmd_reap() {
  local f n hp hs op b pid wt now age
  for f in "$FLMOD_LOCKS"/lane-*.owner; do
    [ -f "$f" ] || continue
    n=$(kv "$f" lane); hp=$(kv "$f" holder_pid); hs=$(kv "$f" holder_start); op=$(kv "$f" owner_pid)
    if ! alive "$hp" || ! holder_is_ours "$hp" "$hs"; then
      if reap_lane "$n"; then hlog "reap lane $n: holder $hp dead (lease expired or killed)"
      else hlog "reap lane $n: stale owner file but the lane lock is held (an acquisition in progress): left alone"; fi
    elif [ -n "$op" ] && ! alive "$op"; then
      if reap_lane "$n" "$hp" "$hs"; then hlog "reap lane $n: owner process $op dead"
      else hlog "reap lane $n: owner $op dead but the lock is still held: left alone"; fi
    fi
  done
  # status files of acquisitions: .acq-<acquirer pid>-<wait_s>-<rand>.status[.tmp]; stale only if the acquirer is
  # dead or the file is older than its wait budget + 60 s
  now=$(date +%s)
  for f in "$FLMOD_LOCKS"/.acq-*.status "$FLMOD_LOCKS"/.acq-*.status.tmp; do
    [ -e "$f" ] || continue
    b=$(basename "$f"); pid=$(cut -d- -f2 <<<"$b"); wt=$(cut -d- -f3 <<<"$b")
    [[ "$wt" =~ ^[0-9]+$ ]] || wt=7200
    age=$(( now - $(stat -c %Y "$f" 2>/dev/null || echo "$now") ))
    if ! alive "$pid" || [ "$age" -gt $(( wt + 60 )) ]; then rm -f "$f"; fi
  done
  cmd_status
}

case "${1:-}" in
  acquire) shift; cmd_acquire "$@" ;;
  release) shift; cmd_release "$@" ;;
  env)     [ -f "$FLMOD_LOCKS/lane-${2:?N}.env" ] || hdie "lane $2 not held"; print_env "$2" ;;
  status)  cmd_status ;;
  reap)    cmd_reap ;;
  *) sed -n '2,17p' "$0" >&2; exit 2 ;;
esac
