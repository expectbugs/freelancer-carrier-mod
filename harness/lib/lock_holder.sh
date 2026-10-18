#!/bin/bash
# Long-lived lock holder for harness/lane.sh (CONVENTIONS §7). Started with `setsid -f`, so it survives the tool call
# that ran `lane.sh acquire`. It takes the flocks on its own fds, reports through a status file, then execs `sleep`,
# which inherits the fds and so keeps the locks until it is killed (release/reap) or its lease (TTL) runs out.
#
#   lock_holder.sh <status-file> <locks-dir> <mode:normal|perf> <input:0|1> <lanes:"1 2 3"> <wait_s> <ttl_s>
#                  [<renderer class: gpu|sw>]
#
# Lock files (all absolute under $FLMOD_LOCKS so every worktree shares them):
#   lane-<N>.lock  exclusive per lane
#   perf.gate      writer-preference gate: a --perf requester holds it exclusively while waiting and running;
#                  normal acquirers pass through it (shared, briefly) so they queue behind a waiting --perf
#   perf.lock      shared by every normal lane holder; exclusive for --perf (waits until no other lane is held)
#   input.lock     exclusive; synthetic input / window focus
#   render.gate, render-gpu.lock, render-sw.lock   renderer classes never mix: a lane takes render-<class>.lock
#                  shared, but only after checking (under render.gate) that nobody holds the other class
status="$1"; locks="$2"; mode="$3"; want_input="$4"; lanes="$5"; wait_s="$6"; ttl="$7"; rclass="${8:-gpu}"
deadline=$(( $(date +%s) + wait_s ))
fail() { echo "FAIL $*" > "$status.tmp"; mv -f "$status.tmp" "$status"; exit 1; }
remaining() { local r=$(( deadline - $(date +%s) )); [ $r -lt 1 ] && r=1; echo $r; }

got=""
while :; do
  for n in $lanes; do
    exec 9>"$locks/lane-$n.lock"
    if flock -n 9; then got=$n; break; fi
    exec 9>&-
  done
  [ -n "$got" ] && break
  [ "$(date +%s)" -ge "$deadline" ] && fail "timeout waiting for a free lane among: $lanes"
  sleep 2
done

exec 7>"$locks/perf.gate"
exec 8>"$locks/perf.lock"
if [ "$mode" = perf ]; then
  flock -x -w "$(remaining)" 7 || fail "timeout on perf.gate"
  flock -x -w "$(remaining)" 8 || fail "timeout waiting for other lanes to finish (perf.lock)"
else
  flock -s -w "$(remaining)" 7 || fail "timeout: a --perf run holds/awaits the perf gate"
  flock -s -w "$(remaining)" 8 || fail "timeout on perf.lock"
  flock -u 7; exec 7>&-
fi

case "$rclass" in gpu) other=sw ;; sw) other=gpu ;; *) fail "bad renderer class $rclass" ;; esac
exec 4>"$locks/render-$rclass.lock"
while :; do
  exec 5>"$locks/render.gate"
  flock -x -w "$(remaining)" 5 || fail "timeout on render.gate"
  exec 3>"$locks/render-$other.lock"
  if flock -x -n 3; then             # nobody runs the other class
    flock -u 3; exec 3>&-
    flock -s 4
    flock -u 5; exec 5>&-
    break
  fi
  exec 3>&-; flock -u 5; exec 5>&-
  [ "$(date +%s)" -ge "$deadline" ] && fail "timeout: lanes with renderer class $other are running (classes never mix)"
  sleep 2
done

if [ "$want_input" = 1 ]; then
  exec 6>"$locks/input.lock"
  flock -x -w "$(remaining)" 6 || fail "timeout waiting for input.lock"
fi

echo "OK lane=$got pid=$$" > "$status.tmp"; mv -f "$status.tmp" "$status"
exec sleep "$ttl"
