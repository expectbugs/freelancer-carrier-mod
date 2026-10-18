# Lock-contention helpers for the lane test suites (test_lanes.sh, test_input_gate.sh). Sourced, not run.
# The suites use test lanes 6-8 only; when one of their acquires fails because ANOTHER agent holds a lock (input.lock,
# a renderer class, the perf gate), that check is a SKIP, not a FAIL (review P0-HARNESS-b r1).
#   ACQ_ERR=<file>       stderr of the last `lane.sh acquire` (the suites redirect it there)
#   foreign_holds <lock> $FLMOD_LOCKS/<lock> has more flock() holders (/proc/locks) than this suite accounts for
#   contention           the last acquire failed on a lock that another agent holds right now
#   foreign_sw           a wined3d-sw lane is held elsewhere (every default-class acquire would wait)
# Holders are counted, not named: /proc/locks records the pid of whoever called flock(), which for flock(1) on an
# inherited fd is a short-lived child, so the pid there says nothing. This suite's holders are its lane 6-8 lock
# holders (and $CONTENTION_EXCLUDE_PIDS); each holds a lock through an open fd on the lock file.

_lock_key() { # maj:min:inode as /proc/locks prints it (hex major/minor, 2 digits)
  local d i
  d=$(stat -c '%d' "$1" 2>/dev/null) || return 1
  i=$(stat -c '%i' "$1" 2>/dev/null) || return 1
  printf '%02x:%02x:%s' $(( (d >> 8) & 0xfff )) $(( (d & 0xff) | ((d >> 12) & 0xfff00) )) "$i"
}

_lock_entries() { # number of FLOCK entries on the lock file
  local k; k=$(_lock_key "$1") || { echo 0; return; }
  awk -v k="$k" '$2 == "FLOCK" && tolower($6) == k {n++} END {print n+0}' /proc/locks
}

_our_holders() {
  local n
  for n in 6 7 8; do sed -n 's/^holder_pid=//p' "$FLMOD_LOCKS/lane-$n.owner" 2>/dev/null; done
  [ -n "${CONTENTION_EXCLUDE_PIDS:-}" ] && echo "$CONTENTION_EXCLUDE_PIDS" | tr ' ' '\n'
}

_our_count() { # how many of our holders have the lock file open
  local f="$1" p fd c=0
  for p in $(_our_holders); do
    for fd in /proc/"$p"/fd/*; do
      [ "$(readlink "$fd" 2>/dev/null)" = "$f" ] && { c=$((c + 1)); break; }
    done
  done
  echo "$c"
}

foreign_holds() { # <lock file name>
  local f="$FLMOD_LOCKS/$1"
  [ -e "$f" ] || return 1
  [ "$(_lock_entries "$f")" -gt "$(_our_count "$f")" ]
}

contention() {
  [ -s "${ACQ_ERR:-/nonexistent}" ] || return 1
  if grep -q 'input.lock' "$ACQ_ERR" && foreign_holds input.lock; then return 0; fi
  if grep -q 'renderer class' "$ACQ_ERR" && { foreign_holds render-sw.lock || foreign_holds render-gpu.lock; }; then
    return 0
  fi
  if grep -qE 'perf\.(gate|lock)|--perf run' "$ACQ_ERR" && { foreign_holds perf.gate || foreign_holds perf.lock; }; then
    return 0
  fi
  return 1
}

foreign_sw() { foreign_holds render-sw.lock; }
