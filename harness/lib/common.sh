# Shared helpers for harness scripts. Usage (first lines of every harness script):
#   source /home/user/freelancer/carrier-mod/tools/env.sh
#   source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/common.sh"
# Requires tools/env.sh to be sourced first (guards on PATH, FLMOD_* paths). Never calls wine binaries directly.

HARNESS_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
# shellcheck source=../config.sh
source "$HARNESS_DIR/config.sh"

if [ -z "${FLMOD_REPO:-}" ] || ! command -v wine >/dev/null || [ "$(command -v wine)" != "$FLMOD_REPO/tools/bin/wine" ]; then
  echo "harness: tools/env.sh not sourced (wine guard not first on PATH)" >&2
  exit 96
fi

hlog() { echo "[harness] $(date -u +%H:%M:%S) $*" >&2; }
hdie() { echo "[harness] ERROR: $*" >&2; exit "${2:-1}"; }

utc_stamp() { date -u +%Y%m%d-%H%M%S; }
now_ms() { date +%s%3N; }

hde_of() { echo "$1/$HDE_REL"; }
spew_of() { echo "$1/$SPEW_REL"; }
lane_prefix() { echo "${LANE_PREFIX_STEM}$1"; }
base_prefix() { case "$1" in A) echo "$BASE_PREFIX_A";; B) echo "$BASE_PREFIX_B";; *) hdie "bad track '$1'";; esac; }

# Refuse to operate (rm/patch/kill) on anything that is not one of P0-HARNESS's own prefixes.
assert_owned_prefix() {
  local p; p=$(realpath -m -- "$1")
  case "$p" in
    "$BASE_PREFIX_A"|"$BASE_PREFIX_B") return 0 ;;
    "${LANE_PREFIX_STEM}"[0-9]|"${LANE_PREFIX_STEM}"[0-9][0-9]) return 0 ;;
  esac
  hdie "refusing to operate on '$1' (resolved '$p'): not prefix-dev-base-A|B or prefix-lane-<N>" 95
}

# Lane N window slot on the 2x2 grid; lanes > 4 wrap (overlap harmlessly).
lane_slot() {
  local i=$(( ($1 - 1) % 4 ))
  echo "$(( (i % 2) * LANE_W )) $(( (i / 2) * LANE_H ))"
}

# Scoped wineserver kill for one of our prefixes (through the guard).
lane_wineserver_kill() {
  local p="$1"; assert_owned_prefix "$p"
  [ -d "$p" ] || return 0
  WINEPREFIX="$p" wineserver -k >/dev/null 2>&1 || true
  WINEPREFIX="$p" timeout 60 wineserver -w >/dev/null 2>&1 || true
}

# Unix PIDs of processes belonging to a prefix (WINEPREFIX in environ). Read-only /proc scan.
prefix_pids() {
  local p; p=$(realpath -m -- "$1")
  # one grep over every readable environ (NUL-separated entries, whole-entry match)
  grep -lszxF "WINEPREFIX=$p" /proc/[0-9]*/environ 2>/dev/null | sed -n 's#^/proc/\([0-9]*\)/environ$#\1#p'
  return 0
}

# Unix PID of the lane's Freelancer.exe (empty if not running).
game_pid() {
  local pid
  for pid in $(prefix_pids "$1"); do
    [ "$(cat "/proc/$pid/comm" 2>/dev/null)" = Freelancer.exe ] && { echo "$pid"; return 0; }
  done
  return 0
}

# Any dw15.exe (FL's Watson crash reporter) inside the prefix?
prefix_has_dw15() {
  local pid
  for pid in $(prefix_pids "$1"); do
    case "$(cat "/proc/$pid/comm" 2>/dev/null)" in dw15*) return 0 ;; esac
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qi 'dw15\.exe' && return 0
  done
  return 1
}

# Wait (poll every 60 s, never kill anything) until the play prefix is idle (REQ-P0-HARNESS-2).
wait_play_prefix_idle() {
  local max_wait=${1:-7200} waited=0
  while "$FLMOD_REPO/tools/play_prefix_busy.sh" >/dev/null 2>&1; do
    [ "$waited" -ge "$max_wait" ] && hdie "play prefix still busy after ${max_wait}s; not cloning"
    hlog "play prefix busy; waiting 60 s (never killing anything)"
    sleep 60; waited=$((waited + 60))
  done
}

# Renderer a run would use (D103/D105): $1, else $FLMOD_RENDERER, else RENDERER_DEFAULT. auto = dxvk when a Vulkan
# device can be created (vulkaninfo --summary succeeds), else RENDERER_FALLBACK. Same rule as lib/runner.py.
resolve_renderer() {
  local r=${1:-${FLMOD_RENDERER:-$RENDERER_DEFAULT}}
  case "$r" in
    dxvk|wined3d|wined3d-sw) echo "$r" ;;
    auto)
      local out
      if out=$(timeout 30 vulkaninfo --summary 2>&1) && ! grep -qE 'vkCreateDevice failed|ERROR_INITIALIZATION_FAILED' <<<"$out"; then
        echo dxvk
      else
        echo "$RENDERER_FALLBACK"
      fi ;;
    *) hdie "unknown renderer '$r' (auto|dxvk|wined3d|wined3d-sw)" 2 ;;
  esac
}

# How many lanes acquire may hand out for a renderer: LANES, capped at LANES_SW for the CPU renderer (NOTES.md N11).
effective_lanes() {
  if [ "$1" = wined3d-sw ] && [ "$LANES_SW" -lt "$LANES" ]; then echo "$LANES_SW"; else echo "$LANES"; fi
}

# GLOBAL LOCK ORDER (every harness process takes the locks it needs in this order, never the reverse; a process
# that needs a later lock must not hold it while waiting for an earlier one; README.md "Lock order"):
#   1. lane-<N>.lock   2. perf.gate / perf.lock   3. render.gate / render-<class>.lock   4. input.lock
#   5. baseline-<T>.lock
# lane.sh: the holder takes 1-4, then the clone takes 5 (shared). deploy.sh: holds 1(-4) via the lane, takes 5.
# baseline.sh fluf-init: 4 (input, for FLUF's first-run dialog), then 5 (exclusive). baseline.sh create: 5 only.
#
# Baseline lock (P0-TOOLCHAIN r3 note): baseline.sh holds $FLMOD_LOCKS/baseline-<T>.lock exclusively while it
# creates or tweaks a baseline; everything that clones from a baseline (lane.sh, deploy.sh) holds it shared.
#   with_baseline_lock -x|-s <A|B> <command...>
with_baseline_lock() {
  local mode=$1 track=$2 fd rc; shift 2
  mkdir -p "$FLMOD_LOCKS"
  exec {fd}>"$FLMOD_LOCKS/baseline-$track.lock"
  if ! flock "$mode" -w "${BASELINE_LOCK_WAIT_S:-3600}" "$fd"; then
    exec {fd}>&-
    hlog "timeout waiting for the baseline-$track lock ($mode)"
    return 75
  fi
  "$@"; rc=$?
  flock -u "$fd"; exec {fd}>&-
  return $rc
}

# input.lock held by this shell for the duration of <command...> (lock order step 4, before any baseline lock).
# Children (xinput.py --prefix) find the open fd on an ancestor, so they must not take the lock again.
#   with_input_lock <command...>
with_input_lock() {
  local fd rc
  mkdir -p "$FLMOD_LOCKS"
  exec {fd}>"$FLMOD_LOCKS/input.lock"
  if ! flock -x -w "${INPUT_LOCK_WAIT_S:-900}" "$fd"; then
    exec {fd}>&-
    hlog "timeout waiting for input.lock"
    return 75
  fi
  "$@"; rc=$?
  flock -u "$fd"; exec {fd}>&-
  return $rc
}

# Start time of a process (field 22 of /proc/<pid>/stat), empty if unknown. Guards pid reuse.
proc_start() { sed -n 's/^.*) //p' "/proc/$1/stat" 2>/dev/null | awk '{print $20}'; }

# Is <pid> a Wine process (its executable lives under a wine install, or it is a Windows .exe / wineserver)?
is_wine_pid() {
  local exe c
  exe=$(readlink "/proc/$1/exe" 2>/dev/null) || exe=""
  c=$(cat "/proc/$1/comm" 2>/dev/null) || c=""
  case "$exe" in */wine*|*/lib/wine-proton*) return 0 ;; esac
  case "$c" in wineserver|*.exe|wine*|*-preloader) return 0 ;; esac
  return 1
}

# Python from the shared venv, isolated mode.
hpy() { "$FLMOD_VENV/bin/python" -I "$@"; }

git_sha() { git -C "$HARNESS_DIR" rev-parse HEAD 2>/dev/null || echo unknown; }
