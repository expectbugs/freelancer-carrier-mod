#!/bin/bash
# Start (or resume) the autonomous build: orchestrator in tmux "flbuild", watchdog in tmux "flwatch".
# Usage: tools/start-build.sh [--no-remote-control]
set -eu
R=/home/user/freelancer/carrier-mod
CLAUDE=${FLBUILD_CLAUDE:-/home/user/.local/bin/claude}
S=${FLBUILD_SESSION:-flbuild}
W=${FLWATCH_SESSION:-flwatch}
RC=1; [ "${1:-}" = "--no-remote-control" ] && RC=0
cd "$R"; mkdir -p "$R/local"
rm -f "$R/STOP"
# Resume after STOP/HALT: reset the ledger status line (line 1 only)
first=$(head -1 state/BUILD_STATE.md)
case "$first" in
  *COMPLETE*) echo "Ledger says COMPLETE — nothing to do."; exit 0 ;;
  *STOPPED*|*HALTED*) sed -i '1s/.*/BUILD_STATUS: IN_PROGRESS/' state/BUILD_STATE.md; echo "Ledger status reset to IN_PROGRESS (was: $first)" ;;
esac
# Reuse an existing orchestrator session only if claude is actually running in it; otherwise replace it
if tmux has-session -t "$S" 2>/dev/null; then
  pp=$(tmux display-message -p -t "$S" '#{pane_pid}')
  if pgrep -P "$pp" >/dev/null 2>&1; then echo "Orchestrator already running — attach: tmux attach -t $S"; exit 1; fi
  tmux kill-session -t "$S"
fi
RCFLAG=""; [ $RC = 1 ] && RCFLAG="--remote-control 'FL carrier build'"
echo "--dangerously-skip-permissions --model opus --effort xhigh $RCFLAG" > "$R/local/claude_flags"
date -Is > "$R/local/heartbeat"
# Environment every Bash call in the session inherits (CONVENTIONS §15): wine guards first on PATH, sentinel prefix, env file
ENVX="export CLAUDE_ENV_FILE=$R/tools/env.sh PATH=$R/tools/bin:/usr/lib/llvm/22/bin:\$PATH WINEPREFIX=/home/user/freelancer/prefix-UNSET DISPLAY=\${DISPLAY:-:0}"
tmux new-session -d -s "$S" -c "$R" -x 220 -y 60
# A build already under way (IN_PROGRESS, or reset from STOPPED/HALTED above) resumes; only a fresh ledger kicks off
PROMPT=tools/KICKOFF_PROMPT.txt
case "$first" in *IN_PROGRESS*|*STOPPED*|*HALTED*) PROMPT=tools/RESUME_PROMPT.txt ;; esac
tmux send-keys -t "$S" "$ENVX; cd $R && $CLAUDE $(cat "$R/local/claude_flags") \"\$(cat $PROMPT)\"" Enter
echo "$ENVX" > "$R/local/session_env"
tmux has-session -t "$W" 2>/dev/null || tmux new-session -d -s "$W" -c "$R" "$R/tools/watchdog.sh"
echo "Started. Watch:      tmux attach -t $S        (detach: Ctrl-b d)"
echo "Watchdog log:        $R/local/watchdog.log"
echo "Stop everything:     touch $R/STOP"
