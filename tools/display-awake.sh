#!/bin/bash
# Keep display :0 awake during the autonomous build and restore Adam's settings afterwards.
#   display-awake.sh start | stop | status
# State dir defaults to $FLMOD_LOCAL; tests MUST set DISPLAY_AWAKE_STATE_DIR to a temp dir (never touch the live state).
set -u
export DISPLAY="${DISPLAY:-:0}"
ST="${DISPLAY_AWAKE_STATE_DIR:-/home/user/freelancer/carrier-mod/local}"
BAK="$ST/display-settings.bak"
PIDF="$ST/display-inhibit.pid"
mkdir -p "$ST"
inhibitor_alive(){ [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
case "${1:-status}" in
  start)
    if [ ! -f "$BAK" ]; then
      q=$(xset q)
      {
        echo "XSET_S_TIMEOUT=$(awk '/timeout:/{print $2; exit}' <<<"$q")"
        echo "XSET_S_CYCLE=$(awk '/cycle:/{print $4; exit}' <<<"$q")"
        echo "XSET_PREFER_BLANK=$(grep -q 'prefer blanking:  yes' <<<"$q" && echo yes || echo no)"
        echo "DPMS_ENABLED=$(grep -q 'DPMS is Enabled' <<<"$q" && echo 1 || echo 0)"
        echo "PM_PRESENTATION=$(xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/presentation-mode 2>/dev/null || echo unset)"
      } > "$BAK"
    fi
    xset s off; xset s noblank; xset -dpms
    xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/presentation-mode -n -t bool -s true 2>/dev/null || true
    if ! inhibitor_alive; then
      # setsid: fully detached so it survives the shell/tool call that started it
      setsid -f bash -c 'echo $$ > "$1"; exec xfce4-screensaver-command --inhibit -n flbuild -r "autonomous Freelancer mod build"' _ "$PIDF" >/dev/null 2>&1
      sleep 1
    fi
    inhibitor_alive && echo "display-awake: ON (inhibitor pid $(cat "$PIDF"); settings saved in $BAK)" || echo "display-awake: ON (xset only; inhibitor failed to start)" ;;
  stop)
    inhibitor_alive && kill "$(cat "$PIDF")" 2>/dev/null; rm -f "$PIDF"
    if [ -f "$BAK" ]; then
      # shellcheck disable=SC1090
      . "$BAK"
      # power-manager first: changing presentation-mode makes xfce4-power-manager re-apply its own X settings,
      # so restore the raw xset values afterwards
      if [ "${PM_PRESENTATION:-unset}" = unset ]; then
        xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/presentation-mode -r 2>/dev/null || true
      else
        xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/presentation-mode -s "$PM_PRESENTATION" 2>/dev/null || true
      fi
      sleep 2
      xset s "${XSET_S_TIMEOUT:-1200}" "${XSET_S_CYCLE:-1200}"
      [ "${XSET_PREFER_BLANK:-no}" = yes ] && xset s blank || xset s noblank
      [ "${DPMS_ENABLED:-0}" = 1 ] && xset +dpms || xset -dpms
      rm -f "$BAK"
    fi
    echo "display-awake: OFF (settings restored)" ;;
  status)
    xset q | grep -A2 -E 'Screen Saver|DPMS'; inhibitor_alive && echo "inhibitor pid $(cat "$PIDF")" || echo "no inhibitor"; [ -f "$BAK" ] && echo "saved settings present" || true ;;
  *) echo "usage: $0 start|stop|status"; exit 2 ;;
esac
