#!/bin/bash
# REQ-P0-HARNESS-17: test tools/display-awake.sh (orchestrator-owned) against a TEMP state dir only.
# Asserts: `xset q` identical before/after start->status->stop; no extra inhibitor process remains; the live
# build-wide inhibitor ($FLMOD_LOCAL/display-inhibit.pid), if running, is untouched. Never touches the live state dir.
source /home/user/freelancer/carrier-mod/tools/env.sh
set -u
export DISPLAY=${DISPLAY:-:0}
DA="$FLMOD_REPO/tools/display-awake.sh"
LIVE_PIDF="$FLMOD_LOCAL/display-inhibit.pid"
pass=0; fail=0
ok()  { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; fail=$((fail+1)); }

inhibitors() { pgrep -f -- 'xfce4-screensaver-command --inhibit' | sort; }
pm_mode() { xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/presentation-mode 2>/dev/null || echo unset; }

TMP=$(mktemp -d)
# On any exit, including an interrupt mid-test: stop the TEMP inhibitor (temp state dir only; the live one has its own
# pid file and is never touched), then remove the temp dir (review r1 m14).
cleanup() {
  if [ -f "$TMP/display-inhibit.pid" ]; then
    local p; p=$(cat "$TMP/display-inhibit.pid" 2>/dev/null)
    DISPLAY_AWAKE_STATE_DIR="$TMP" "$DA" stop >/dev/null 2>&1
    [ -n "$p" ] && [ "$p" != "${live_pid:-}" ] && kill "$p" 2>/dev/null
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
[ "$TMP" != "$FLMOD_LOCAL" ] || { echo "refusing: temp dir equals live state dir"; exit 2; }

live_pid=""; live_alive=0
if [ -f "$LIVE_PIDF" ]; then live_pid=$(cat "$LIVE_PIDF"); kill -0 "$live_pid" 2>/dev/null && live_alive=1; fi
live_bak_sum=$(sha256sum "$FLMOD_LOCAL/display-settings.bak" 2>/dev/null | cut -d' ' -f1)
before_xset=$(xset q); before_inh=$(inhibitors); before_pm=$(pm_mode)
echo "live inhibitor pid=${live_pid:-none} alive=$live_alive; inhibitors before: $(echo $before_inh)"

out_start=$(DISPLAY_AWAKE_STATE_DIR="$TMP" "$DA" start 2>&1); echo "start: $out_start"
[ -f "$TMP/display-settings.bak" ] && ok "start wrote settings backup into the temp state dir" || bad "no backup in temp dir"
tpid=$(cat "$TMP/display-inhibit.pid" 2>/dev/null)
if [ -n "$tpid" ] && kill -0 "$tpid" 2>/dev/null; then ok "temp inhibitor running (pid $tpid)"; else bad "temp inhibitor not running"; fi
[ "$tpid" != "$live_pid" ] && ok "temp inhibitor is a different process from the live one" || bad "temp pid equals live pid"
xset q | grep -q 'timeout:  0' && ok "screensaver timeout 0 while started" || bad "screensaver not off while started"
xset q | grep -q 'DPMS is Disabled' && ok "DPMS disabled while started" || bad "DPMS not disabled while started"

out_status=$(DISPLAY_AWAKE_STATE_DIR="$TMP" "$DA" status 2>&1); echo "status: $(echo "$out_status" | tr '\n' ' ')"
echo "$out_status" | grep -q "inhibitor pid $tpid" && ok "status reports the temp inhibitor" || bad "status does not report temp inhibitor"

out_stop=$(DISPLAY_AWAKE_STATE_DIR="$TMP" "$DA" stop 2>&1); echo "stop: $out_stop"
sleep 1
after_xset=$(xset q); after_inh=$(inhibitors); after_pm=$(pm_mode)

if [ "$before_xset" = "$after_xset" ]; then ok "xset q identical before/after"; else bad "xset q differs"; diff <(echo "$before_xset") <(echo "$after_xset"); fi
[ "$before_pm" = "$after_pm" ] && ok "presentation-mode identical ($after_pm)" || bad "presentation-mode $before_pm -> $after_pm"
[ "$before_inh" = "$after_inh" ] && ok "no extra inhibitor process remains" || bad "inhibitors before [$(echo $before_inh)] after [$(echo $after_inh)]"
kill -0 "$tpid" 2>/dev/null && bad "temp inhibitor $tpid still alive" || ok "temp inhibitor gone"
[ ! -e "$TMP/display-inhibit.pid" ] && ok "temp pid file removed" || bad "temp pid file left"
if [ "$live_alive" = 1 ]; then
  kill -0 "$live_pid" 2>/dev/null && ok "live inhibitor $live_pid untouched (still alive)" || bad "LIVE INHIBITOR $live_pid DIED"
  [ "$(cat "$LIVE_PIDF" 2>/dev/null)" = "$live_pid" ] && ok "live pid file unchanged" || bad "live pid file changed"
fi
[ "$(sha256sum "$FLMOD_LOCAL/display-settings.bak" 2>/dev/null | cut -d' ' -f1)" = "$live_bak_sum" ] && ok "live settings backup unchanged" || bad "live settings backup changed"

echo "test_display_awake: pass=$pass fail=$fail"
[ $fail -eq 0 ]
