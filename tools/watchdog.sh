#!/bin/bash
# Watchdog for the autonomous build (tmux session "flwatch"). docs/plan/AUTONOMY.md §5–§6.
# - STOP file: tell the orchestrator to stop (AUTONOMY §5.0), wait up to 20 min for BUILD_STATUS: STOPPED,
#   then kill lane wine processes itself, restore the display, and exit.
# - Ledger COMPLETE / HALTED / STOPPED: exit.
# - Orchestrator gone (pane shell idle): relaunch it with the resume prompt.
# - Orchestrator running but heartbeat stale: Escape (dismiss any menu), then type a shell-safe nudge.
set -u
R=/home/user/freelancer/carrier-mod
CLAUDE=${FLBUILD_CLAUDE:-/home/user/.local/bin/claude}
S=${FLBUILD_SESSION:-flbuild}
RELAUNCH_GAP_MIN=${RELAUNCH_GAP_MIN:-5}
STALE_MIN=${STALE_MIN:-75}
NUDGE_GAP_MIN=${NUDGE_GAP_MIN:-60}
CHECK_SEC=${CHECK_SEC:-300}
LOG="$R/local/watchdog.log"
mkdir -p "$R/local"
log(){ echo "$(date -Is) $*" >> "$LOG"; }
FLAGS=$(cat "$R/local/claude_flags" 2>/dev/null || echo "--dangerously-skip-permissions --model opus --effort xhigh")
ENVX=$(cat "$R/local/session_env" 2>/dev/null || echo "export CLAUDE_ENV_FILE=$R/tools/env.sh PATH=$R/tools/bin:\$PATH WINEPREFIX=/home/user/freelancer/prefix-UNSET")
running(){ local pp; pp=$(tmux display-message -p -t "$S" '#{pane_pid}' 2>/dev/null) && [ -n "$pp" ] && pgrep -P "$pp" >/dev/null 2>&1; }
type_line(){ tmux send-keys -t "$S" Escape; sleep 1; tmux send-keys -t "$S" -l "$1"; sleep 1; tmux send-keys -t "$S" Enter; }
launch(){ tmux send-keys -t "$S" "$ENVX; cd $R && $CLAUDE $FLAGS \"\$(cat tools/RESUME_PROMPT.txt)\"" Enter; date -Is > "$R/local/heartbeat"; }
kill_lanes(){ for p in /home/user/freelancer/prefix-lane* /home/user/freelancer/prefix-dev*; do [ -d "$p" ] && WINEPREFIX="$p" /usr/lib/wine-proton-11.0.1/bin/wineserver -k 2>/dev/null; done; }
last_action=$(date +%s)   # grace period after start
log "watchdog started (stale=${STALE_MIN}m gap=${NUDGE_GAP_MIN}m check=${CHECK_SEC}s)"
while true; do
  st=$(head -1 "$R/state/BUILD_STATE.md" 2>/dev/null)
  if [ -e "$R/STOP" ]; then
    case "$st" in
      *STOPPED*) ;;
      *) if tmux has-session -t "$S" 2>/dev/null && running; then
           log "STOP present — asking orchestrator to stop"
           type_line "STOP file present. Follow AUTONOMY section 5 step 0 now: stop all agents and lanes, restore the display, set BUILD_STATUS STOPPED, commit, and end."
           for i in $(seq ${STOP_WAIT_ITERS:-40}); do sleep ${STOP_WAIT_SEC:-30}; head -1 "$R/state/BUILD_STATE.md" | grep -q STOPPED && break; done
         fi ;;
    esac
    log "STOP — killing lane wine processes, restoring display, exiting"
    kill_lanes; "$R/tools/display-awake.sh" stop >> "$LOG" 2>&1
    exit 0
  fi
  case "$st" in *COMPLETE*|*HALTED*|*STOPPED*) log "ledger says '$st' — exiting"; exit 0;; esac
  now=$(date +%s)
  hb=$(stat -c %Y "$R/local/heartbeat" 2>/dev/null || echo 0)
  age=$(( (now - hb) / 60 )); since=$(( (now - last_action) / 60 ))
  if ! tmux has-session -t "$S" 2>/dev/null; then
    log "session $S missing — creating it and launching the orchestrator (resume)"
    tmux new-session -d -s "$S" -c "$R" -x 220 -y 60; launch; last_action=$now
  elif ! running; then
    if [ $since -ge $RELAUNCH_GAP_MIN ]; then log "orchestrator not running in $S — relaunching (resume)"; launch; last_action=$now; fi
  elif [ $age -ge $STALE_MIN ] && [ $since -ge $NUDGE_GAP_MIN ]; then
    log "heartbeat stale (${age}m) — nudging"; type_line "$(cat "$R/tools/NUDGE.txt")"; last_action=$now
  fi
  sleep "$CHECK_SEC"
done
