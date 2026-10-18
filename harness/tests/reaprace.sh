#!/bin/bash
# (written by the P0-HARNESS round-1 reviewer; kept as a regression test, run by tests/test_lanes.sh)
# Review helper: does `lane.sh reap` running concurrently with an acquire of a lane whose previous holder was
# SIGKILLed ever leave the new holder alive without an owner/env file (a leaked, invisible lock)?
#   reaprace.sh <harness dir> <lane> <iterations> <outdir>
H=$1 L=$2 N=$3 OUT=$4
LOCKS=/home/user/freelancer/carrier-mod/local/locks
mkdir -p "$OUT"
leaks=0
for i in $(seq 1 "$N"); do
  # 1. a holder that dies by SIGKILL, leaving a stale owner file
  "$H/lane.sh" acquire --track B --lane "$L" --keep-prefix --owner review-reaprace-old --ttl 120 --wait 20 > "$OUT/old$i.out" 2>/dev/null
  oh=$(sed -n 's/^holder_pid=//p' "$LOCKS/lane-$L.owner")
  kill -9 "$oh"; sleep 0.1
  # 2. reap in a loop while a new acquirer takes the same lane
  ( end=$((SECONDS + 2)); while [ $SECONDS -lt $end ]; do "$H/lane.sh" reap >/dev/null 2>&1; done ) &
  rp=$!
  "$H/lane.sh" acquire --track B --lane "$L" --keep-prefix --owner review-reaprace-new --ttl 120 --wait 5 > "$OUT/new$i.out" 2> "$OUT/new$i.err"
  rc=$?
  wait "$rp"
  tok=$(sed -n 's/^export LANE_TOKEN=//p' "$OUT/new$i.out")
  nh=$(echo "$tok" | cut -d- -f2)
  # the new holder: from the token, or (if acquire failed) whoever holds the lane lock now
  if [ -z "$nh" ]; then
    nh=$(for p in $(pgrep -x sleep); do ls -l /proc/$p/fd 2>/dev/null | grep -q "lane-$L.lock" && echo $p; done | head -1)
  fi
  own=missing; [ -f "$LOCKS/lane-$L.owner" ] && own="holder=$(sed -n 's/^holder_pid=//p' "$LOCKS/lane-$L.owner")"
  alive=dead; [ -n "$nh" ] && kill -0 "$nh" 2>/dev/null && alive=alive
  echo "iter $i: new acquire rc=$rc token=${tok:-none} new_holder=${nh:-?}($alive) owner_file=$own"
  if [ "$alive" = alive ] && [ "$own" = missing ]; then
    leaks=$((leaks + 1)); echo "  LEAK: lane $L locked by holder $nh with no owner/env file"
  fi
  # cleanup: release by token if possible, else kill our own leaked holder directly
  if [ -n "$tok" ] && [ "$own" != missing ]; then "$H/lane.sh" release "$tok" >/dev/null 2>&1
  else [ "$alive" = alive ] && [ "$(cat /proc/$nh/comm 2>/dev/null)" = sleep ] && kill "$nh"; rm -f "$LOCKS/lane-$L.owner" "$LOCKS/lane-$L.env"; fi
  sleep 0.2
done
echo "leaks=$leaks of $N"
"$H/lane.sh" status
