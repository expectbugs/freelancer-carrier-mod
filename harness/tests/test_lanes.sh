#!/bin/bash
# Lane locking tests (REQ-P0-HARNESS-7 acceptance): global locks across worktrees, --perf exclusivity with writer
# preference, --input lock, reap of dead owners, TTL expiry, token checks. Uses lanes 6-8 only (never 1-3) and
# a second copy of harness/ in a temp dir to stand in for another worktree (locks are absolute $FLMOD_LOCKS).
source /home/user/freelancer/carrier-mod/tools/env.sh
set -u
H1="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
TMP=$(mktemp -d); trap 'cleanup' EXIT
cp -a "$H1" "$TMP/harness"; H2="$TMP/harness"
pass=0; fail=0
ok()  { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; fail=$((fail+1)); }
tok() { sed -n "s/^export LANE_TOKEN=//p" <<<"$1"; }
acq() { local h=$1; shift; "$h/lane.sh" acquire --track B --keep-prefix --owner test_lanes "$@" 2>/dev/null; }
cleanup() {
  for f in "$FLMOD_LOCKS"/lane-[678].owner; do
    [ -f "$f" ] && "$H1/lane.sh" release "$(sed -n 's/^token=//p' "$f")" >/dev/null 2>&1
  done
  [ -n "${BGP:-}" ] && kill "$BGP" 2>/dev/null
  rm -rf "$TMP"
  # the test lanes' prefixes are disposable clones; remove them unless a process still uses one
  local n p
  for n in 6 7 8; do
    p=/home/user/freelancer/prefix-lane-$n
    [ -d "$p" ] || continue
    [ -f "$FLMOD_LOCKS/lane-$n.owner" ] && continue
    WINEPREFIX="$p" wineserver -k >/dev/null 2>&1
    grep -lszxF "WINEPREFIX=$p" /proc/[0-9]*/environ >/dev/null 2>&1 || rm -rf --one-file-system -- "$p"
  done
}

others=$(ls "$FLMOD_LOCKS"/lane-*.owner 2>/dev/null | grep -v 'lane-[678].owner' | wc -l)

# 1. cross-worktree contention on the same lane
o1=$(acq "$H1" --lane 6 --wait 30); t1=$(tok "$o1")
[ -n "$t1" ] && ok "wt1 acquired lane 6" || bad "wt1 could not acquire lane 6"
o2=$(acq "$H2" --lane 6 --wait 4); rc=$?
[ $rc -ne 0 ] && [ -z "$(tok "$o2")" ] && ok "wt2 blocked on lane 6 (rc=$rc)" || bad "wt2 got lane 6 while wt1 holds it"
o3=$(acq "$H2" --lane 7 --wait 30); t3=$(tok "$o3")
[ -n "$t3" ] && ok "wt2 acquired lane 7 concurrently" || bad "wt2 could not acquire lane 7"
"$H2/lane.sh" release "$t3" >/dev/null 2>&1 && ok "released lane 7 from wt2" || bad "release lane 7"
"$H1/lane.sh" release "bogus-token" >/dev/null 2>&1 && bad "release with a bogus token succeeded" || ok "bogus token refused"

# 2. --perf waits for other lanes, and blocks new ones while held (only meaningful with no foreign lanes held)
if [ "$others" -eq 0 ]; then
  op=$(acq "$H2" --lane 7 --perf --wait 4); rc=$?
  [ $rc -ne 0 ] && ok "--perf blocked while lane 6 is held" || { bad "--perf acquired while lane 6 held"; "$H2/lane.sh" release "$(tok "$op")" >/dev/null 2>&1; }
  # writer preference: queue a perf request, then a normal request must wait behind it
  ( acq "$H2" --lane 7 --perf --wait 60 > "$TMP/perf.out" ) & BGP=$!
  sleep 2
  on=$(acq "$H1" --lane 8 --wait 4); rc=$?
  [ $rc -ne 0 ] && ok "normal acquire queued behind a waiting --perf (writer preference)" || { bad "normal acquire jumped a waiting --perf"; "$H1/lane.sh" release "$(tok "$on")" >/dev/null 2>&1; }
  "$H1/lane.sh" release "$t1" >/dev/null 2>&1; t1=""
  wait "$BGP"; BGP=""
  tp=$(tok "$(cat "$TMP/perf.out")")
  [ -n "$tp" ] && ok "--perf acquired once lane 6 was released" || bad "--perf never acquired"
  on=$(acq "$H1" --lane 8 --wait 4); rc=$?
  [ $rc -ne 0 ] && ok "normal acquire blocked while --perf held" || { bad "normal acquire while --perf held"; "$H1/lane.sh" release "$(tok "$on")" >/dev/null 2>&1; }
  "$H2/lane.sh" release "$tp" >/dev/null 2>&1
  on=$(acq "$H1" --lane 8 --wait 20); t8=$(tok "$on")
  [ -n "$t8" ] && ok "normal acquire works after --perf released" || bad "normal acquire after perf release"
  "$H1/lane.sh" release "$t8" >/dev/null 2>&1
else
  echo "SKIP --perf checks: $others foreign lane(s) held right now (perf would wait for them)"
  [ -n "$t1" ] && "$H1/lane.sh" release "$t1" >/dev/null 2>&1; t1=""
fi
[ -n "${t1:-}" ] && "$H1/lane.sh" release "$t1" >/dev/null 2>&1

# 3. input lock is global and exclusive
ia=$(acq "$H1" --lane 6 --input --wait 30); ta=$(tok "$ia")
[ -n "$ta" ] && ok "lane 6 with --input" || bad "lane 6 --input"
ib=$(acq "$H2" --lane 7 --input --wait 4); rc=$?
[ $rc -ne 0 ] && ok "second --input blocked" || { bad "two input holders"; "$H2/lane.sh" release "$(tok "$ib")" >/dev/null 2>&1; }
ic=$(acq "$H2" --lane 7 --wait 20); tc=$(tok "$ic")
[ -n "$tc" ] && ok "lane 7 without --input runs alongside the input holder" || bad "lane 7 without input blocked"
"$H2/lane.sh" release "$tc" >/dev/null 2>&1
"$H1/lane.sh" release "$ta" >/dev/null 2>&1
ib=$(acq "$H2" --lane 7 --input --wait 20); tb=$(tok "$ib")
[ -n "$tb" ] && ok "--input free again after release" || bad "--input not freed"
"$H2/lane.sh" release "$tb" >/dev/null 2>&1

# 4. reap frees a lane whose owner process died
sleep 300 & fake=$!
ro=$(acq "$H1" --lane 6 --owner-pid "$fake" --wait 30); tr_=$(tok "$ro")
hp=$(sed -n 's/^holder_pid=//p' "$FLMOD_LOCKS/lane-6.owner")
kill "$fake"; wait "$fake" 2>/dev/null
"$H1/lane.sh" reap >/dev/null 2>&1
[ ! -f "$FLMOD_LOCKS/lane-6.owner" ] && ! kill -0 "$hp" 2>/dev/null && ok "reap freed lane 6 (owner dead, holder $hp killed)" || bad "reap did not free lane 6"
ra=$(acq "$H2" --lane 6 --wait 10); tra=$(tok "$ra")
[ -n "$tra" ] && ok "lane 6 acquirable after reap" || bad "lane 6 not acquirable after reap"
"$H2/lane.sh" release "$tra" >/dev/null 2>&1

# 5. TTL lease expiry
lo=$(acq "$H1" --lane 6 --ttl 3 --wait 30)
sleep 5
la=$(acq "$H2" --lane 6 --wait 10); tla=$(tok "$la")
[ -n "$tla" ] && ok "lease expired after ttl; lane re-acquired" || bad "ttl lease did not expire"
"$H2/lane.sh" release "$tla" >/dev/null 2>&1

# 6. lane.sh status works
"$H1/lane.sh" status >/dev/null && ok "status" || bad "status"

# 7. renderer-aware lane count (NOTES.md N11): LANES on dxvk, min(LANES, LANES_SW) on wined3d-sw
er=$(bash -c "source '$H1/lib/common.sh'; LANES=4; LANES_SW=2; echo \$(effective_lanes dxvk) \$(effective_lanes wined3d-sw) \$(resolve_renderer wined3d-sw) \$(resolve_renderer dxvk)")
[ "$er" = "4 2 wined3d-sw dxvk" ] && ok "effective_lanes/resolve_renderer ($er)" || bad "effective_lanes/resolve_renderer: '$er'"
bash -c "source '$H1/lib/common.sh'; resolve_renderer bogus" >/dev/null 2>&1 && bad "bogus renderer accepted" || ok "bogus renderer refused"

# 8. reap racing an acquire never leaks a lock (review r1 M2; the reviewer's reaprace.sh, 0 leaks required)
rr=$(bash "$H1/tests/reaprace.sh" "$H1" 8 6 "$TMP/reaprace" 2>&1 | grep '^leaks=')
[ "$rr" = "leaks=0 of 6" ] && ok "reap vs acquire: $rr" || bad "reap vs acquire: ${rr:-no result}"
# a status file of a live acquisition survives reap; a dead acquirer's one is removed
sleep 300 & live=$!
touch "$FLMOD_LOCKS/.acq-$live-30-1.status" "$FLMOD_LOCKS/.acq-999999-30-2.status"
"$H1/lane.sh" reap >/dev/null 2>&1
[ -e "$FLMOD_LOCKS/.acq-$live-30-1.status" ] && ok "reap keeps a live acquisition's status file" || bad "reap removed a live status file"
[ ! -e "$FLMOD_LOCKS/.acq-999999-30-2.status" ] && ok "reap removes a dead acquirer's status file" || bad "stale status file kept"
kill "$live"; wait "$live" 2>/dev/null; rm -f "$FLMOD_LOCKS/.acq-$live-30-1.status"
# reap leaves a lane alone while its lock is held, even if the owner file is stale (acquisition in progress)
( exec 9>"$FLMOD_LOCKS/lane-7.lock"; flock -x 9; sleep 6 ) & lk=$!
sleep 0.5
printf 'lane=7\nholder_pid=999999\nowner_pid=999999\n' > "$FLMOD_LOCKS/lane-7.owner"
"$H1/lane.sh" reap >/dev/null 2>&1
[ -f "$FLMOD_LOCKS/lane-7.owner" ] && ok "reap skips a locked lane with a stale owner file" || bad "reap cleaned a locked lane"
wait "$lk"; "$H1/lane.sh" reap >/dev/null 2>&1
[ ! -f "$FLMOD_LOCKS/lane-7.owner" ] && ok "reap cleans it once the lock is free" || bad "stale owner file not reaped"

# 9. holder_is_ours checks the start time, not just comm (pid reuse, review r1 m13)
sleep 300 & sp=$!
hio=$(bash -c "source '$H1/lib/common.sh'; source <(sed -n '/^holder_is_ours()/,/^}/p' '$H1/lane.sh'); \
  holder_is_ours $sp && echo nostart-yes; holder_is_ours $sp \"\$(proc_start $sp)\" && echo start-yes; \
  holder_is_ours $sp 12345 || echo wrongstart-no; holder_is_ours $$ || echo notsleep-no")
kill "$sp"; wait "$sp" 2>/dev/null
[ "$(echo $hio)" = "nostart-yes start-yes wrongstart-no notsleep-no" ] && ok "holder_is_ours: comm + cmdline + start time" || bad "holder_is_ours: '$hio'"

# 10. renderer classes never mix (review r1 m10): a wined3d-sw lane waits while a DXVK lane is held, and vice versa
og=$(acq "$H1" --lane 6 --renderer dxvk --wait 30); tg=$(tok "$og")
os_=$(acq "$H2" --lane 7 --renderer wined3d-sw --wait 4); rc=$?
[ -n "$tg" ] && [ $rc -ne 0 ] && ok "sw lane refused while a dxvk lane runs" || { bad "sw lane got a lane next to dxvk"; "$H2/lane.sh" release "$(tok "$os_")" >/dev/null 2>&1; }
og2=$(acq "$H2" --lane 7 --renderer dxvk --wait 10); tg2=$(tok "$og2")
[ -n "$tg2" ] && ok "a second dxvk lane runs alongside" || bad "second dxvk lane blocked"
"$H2/lane.sh" release "$tg2" >/dev/null 2>&1; "$H1/lane.sh" release "$tg" >/dev/null 2>&1
os_=$(acq "$H2" --lane 7 --renderer wined3d-sw --wait 10); ts=$(tok "$os_")
og=$(acq "$H1" --lane 6 --renderer dxvk --wait 4); rc=$?
[ -n "$ts" ] && [ $rc -ne 0 ] && ok "dxvk lane refused while a sw lane runs" || { bad "dxvk lane next to sw"; "$H1/lane.sh" release "$(tok "$og")" >/dev/null 2>&1; }
"$H2/lane.sh" release "$ts" >/dev/null 2>&1

# 12. recreating a lane prefix kills only Wine processes of that prefix (review r1 m2): a plain `sleep` that merely
#     has WINEPREFIX=<lane> in its environment survives
env WINEPREFIX=/home/user/freelancer/prefix-lane-8 sleep 120 & bystander=$!
ob=$("$H1/lane.sh" acquire --track B --lane 8 --owner test_lanes --wait 60 2>/dev/null); tb8=$(tok "$ob")
kill -0 "$bystander" 2>/dev/null && ok "non-wine process with the lane's WINEPREFIX survived the prefix recreate" \
  || bad "prefix recreate killed a non-wine process"
kill "$bystander" 2>/dev/null; wait "$bystander" 2>/dev/null
"$H1/lane.sh" release "$tb8" >/dev/null 2>&1

# 11. baseline lock: a lane clone waits while baseline.sh would hold baseline-B exclusively
( exec 8>"$FLMOD_LOCKS/baseline-B.lock"; flock -x 8; sleep 6 ) & bl=$!
sleep 0.5
t0=$(date +%s)
ob=$("$H1/lane.sh" acquire --track B --lane 8 --owner test_lanes --wait 60 2>/dev/null); tb=$(tok "$ob")
dt=$(( $(date +%s) - t0 ))
wait "$bl"
[ -n "$tb" ] && [ "$dt" -ge 4 ] && ok "lane clone waited ${dt}s for the exclusive baseline lock" || bad "lane clone did not wait for the baseline lock (dt=$dt token=${tb:-none})"
"$H1/lane.sh" release "$tb" >/dev/null 2>&1

for n in 6 7 8; do
  [ -f "$FLMOD_LOCKS/lane-$n.owner" ] && bad "lane $n still held at end"
done
echo "test_lanes: pass=$pass fail=$fail"
[ $fail -eq 0 ]
