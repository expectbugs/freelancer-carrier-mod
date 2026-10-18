#!/bin/bash
# Interrupt test_display_awake.sh right after `start`; the trap must stop the temp inhibitor and keep the live one.
# (review r1 m14) SIGTERM after `start`: the temp inhibitor must be stopped, xset restored, the live inhibitor kept.
T="$(dirname "$(readlink -f "$0")")/test_display_awake.sh"
OUT=$(mktemp); trap 'rm -f "$OUT"' EXIT
before=$(pgrep -f -- 'xfce4-screensaver-command --inhibit' | sort | tr '\n' ' ')
xb=$(xset q | md5sum)
bash "$T" > "$OUT" 2>&1 &
p=$!
for _ in $(seq 1 100); do grep -q '^start:' "$OUT" && break; sleep 0.1; done
mid=$(pgrep -f -- 'xfce4-screensaver-command --inhibit' | sort | tr '\n' ' ')
kill -TERM "$p"; wait "$p"; rc=$?
sleep 3
after=$(pgrep -f -- 'xfce4-screensaver-command --inhibit' | sort | tr '\n' ' ')
xa=$(xset q | md5sum)
echo "rc=$rc before=[$before] mid=[$mid] after=[$after] xset_same=$([ "$xb" = "$xa" ] && echo yes || echo no)"
[ "$before" = "$after" ] && [ "$xb" = "$xa" ] && { echo "PASS interrupt cleanup"; exit 0; }; echo "FAIL interrupt cleanup"; exit 1
