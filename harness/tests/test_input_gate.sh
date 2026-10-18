#!/bin/bash
# Input-gate regression test (review r1 m1): a window whose _NET_WM_PID is forged to the lane's "game" pid must be
# refused because the X server's record of its creator (X-Resource) disagrees; --prefix mode needs the input lock held
# by the caller or an ancestor and accepts only the baseline prefixes. Uses lane 6 (never 1-4), a fake process
# named Freelancer.exe (a copy of `sleep`) and one short-lived xmessage window. No key is ever sent: only `check`.
source /home/user/freelancer/carrier-mod/tools/env.sh
set -u
H="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="$FLMOD_VENV/bin/python"
TMP=$(mktemp -d)
pass=0; fail=0
ok()  { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; fail=$((fail+1)); }
cleanup() {
  [ -n "${XM:-}" ] && kill "$XM" 2>/dev/null
  [ -n "${FAKE:-}" ] && kill "$FAKE" 2>/dev/null
  [ -n "${TOK:-}" ] && "$H/lane.sh" release "$TOK" >/dev/null 2>&1
  rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

# never wait for (or stall) another agent: skip when input.lock is busy or a foreign renderer class runs, and treat
# an acquire lost to another agent's lock as a skip too (exit 77 = skipped, see test_shell_suites.py; review b-r1)
ACQ_ERR="$TMP/acq.err"
source "$H/tests/lib_contention.sh"
if ! flock -n "$FLMOD_LOCKS/input.lock" true; then echo "SKIP input.lock is held by another agent right now"; exit 77; fi
if foreign_sw; then echo "SKIP a wined3d-sw lane is held by another agent (default-class acquire would wait)"; exit 77; fi
out=$("$H/lane.sh" acquire --track B --lane 6 --keep-prefix --input --owner test_input_gate --wait 20 2>"$ACQ_ERR")
TOK=$(sed -n 's/^export LANE_TOKEN=//p' <<<"$out")
if [ -z "$TOK" ]; then
  contention && { echo "SKIP lane 6 --input lost to another agent's lock: $(tail -1 "$ACQ_ERR")"; exit 77; }
  echo "FAIL could not acquire lane 6 with --input: $(tail -1 "$ACQ_ERR")"; exit 1
fi
LP=$(sed -n "s/^export WINEPREFIX='\(.*\)'$/\1/p" <<<"$out")

cp /usr/bin/sleep "$TMP/Freelancer.exe"
env WINEPREFIX="$LP" "$TMP/Freelancer.exe" 300 & FAKE=$!
before=" $(xdotool search --class Xmessage 2>/dev/null | tr '\n' ' ') "
xmessage -geometry 200x60+0+0 "harness input-gate test (closes itself)" 2>/dev/null & XM=$!
W=""
for _ in $(seq 1 50); do
  for w in $(xdotool search --onlyvisible --class Xmessage 2>/dev/null); do
    case "$before" in *" $w "*) ;; *) W=$w ;; esac   # xmessage sets no _NET_WM_PID: the new Xmessage window
  done
  [ -n "$W" ] && break; sleep 0.1
done
[ -n "$W" ] || { echo "FAIL no xmessage window"; exit 1; }
xprop -id "$W" -f _NET_WM_PID 32c -set _NET_WM_PID "$FAKE"
xdotool set_window --name Freelancer "$W"
[ "$(xdotool getwindowpid "$W")" = "$FAKE" ] && ok "forged _NET_WM_PID=$FAKE on window $W" || bad "could not forge the pid"

r=$("$PY" -I "$H/lib/xinput.py" --lane 6 --wid "$W" check 2>&1)
case "$r" in
  *"target_creator_mismatch net_wm_pid=$FAKE xres_pid=$XM"*) ok "forged window refused: $r" ;;
  *) bad "forged window not refused by X-Resource: $r" ;;
esac
r=$("$PY" -I "$H/lib/xinput.py" --lane 6 check 2>&1)   # no --wid: the gate's own search must not pick it either
case "$r" in *input_refused*) ok "gate's own window search refuses: $r" ;; *) bad "gate accepted without --wid: $r" ;; esac

# the runner's own window search (find / validity / place / windowquit) applies the same X-Resource check (review r2)
r=$("$PY" -I -c "import sys; sys.path.insert(0, '$H/lib'); import runner; print(runner.Run.pid_windows({$FAKE}, '^Freelancer\$'))" 2>&1)
[ "$r" = "[]" ] && ok "runner.pid_windows ignores the forged window" || bad "runner.pid_windows returned $r for the forged window"

# --prefix mode
r=$("$PY" -I "$H/lib/xinput.py" --prefix /home/user/freelancer/prefix-lane-6 check 2>&1)
case "$r" in *prefix_not_a_baseline_prefix*) ok "--prefix refuses a lane prefix" ;; *) bad "--prefix lane: $r" ;; esac
"$H/lane.sh" release "$TOK" >/dev/null 2>&1; TOK=""   # frees input.lock
r=$("$PY" -I "$H/lib/xinput.py" --prefix /home/user/freelancer/prefix-dev-base-B check 2>&1)
case "$r" in *input_lock_not_held_by_caller*) ok "--prefix without input.lock refused" ;; *) bad "--prefix no lock: $r" ;; esac
r=$(flock -w 60 "$FLMOD_LOCKS/input.lock" "$PY" -I "$H/lib/xinput.py" --prefix /home/user/freelancer/prefix-dev-base-B check 2>&1)
case "$r" in *no_game_process*) ok "--prefix with input.lock held by an ancestor passes the lock check (then: no game)" ;;
  *) bad "--prefix with lock: $r" ;; esac

echo "test_input_gate: pass=$pass fail=$fail"
[ $fail -eq 0 ]
