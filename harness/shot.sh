#!/bin/bash
# Screenshot a game window (REQ-P0-HARNESS-18).
#   shot.sh <wid> <out.png>
# 1. `import -window <wid>`; if the result is black/uniform (pixel std-dev below SHOT_MIN_STDDEV), fall back to
# 2. `import -window root -crop WxH+X+Y` using `xdotool getwindowgeometry --shell`, but only if no other top-level
#    window is stacked above the game window's area (_NET_CLIENT_LIST_STACKING): a root crop captures whatever is on
#    screen there, possibly someone else's application (review r1 m12).
# Always writes <out>_small.png at 50% when a PNG was written. Prints "shot=<path> method=<window|root-crop> stddev=<v>".
# Exit codes: 0 = the window's own pixels, non-uniform: proof of rendering.
#             2 = root-crop of an uncovered window, non-uniform: evidence only, never proof of rendering.
#             1 = failed, uniform, window gone, or root-crop refused because the area is covered (or unverifiable).
# Read-only for the game (no focus change, no input).
set -u
export DISPLAY=${DISPLAY:-:0}
wid="${1:?usage: shot.sh <wid> <out.png>}"; out="${2:?usage: shot.sh <wid> <out.png>}"
min=${SHOT_MIN_STDDEV:-0.004}
mkdir -p "$(dirname "$out")"
small="${out%.png}_small.png"

stddev() { magick "$1" -colorspace Gray -format '%[fx:standard_deviation]' info: 2>/dev/null || echo 0; }
uniform() { awk -v s="$1" -v m="$min" 'BEGIN{exit !(s+0 < m+0)}'; }

# covered_by <wid> X Y W H: prints the first window stacked above <wid> that overlaps the rectangle; exit 0 if covered,
# 1 if not covered, 2 if it cannot be verified (the window is not in the stacking list).
covered_by() {
  local me=$1 x=$2 y=$3 w=$4 h=$5 stack above=0 s g
  stack=$(timeout 10 xprop -root _NET_CLIENT_LIST_STACKING 2>/dev/null | grep -o '0x[0-9a-fA-F]*') || return 2
  for s in $stack; do
    if [ "$above" = 0 ]; then [ $((s)) -eq $((me)) ] && above=1; continue; fi
    g=$(xdotool getwindowgeometry --shell $((s)) 2>/dev/null) || continue
    local X Y WIDTH HEIGHT; eval "$g"
    if [ "$X" -lt $((x + w)) ] && [ $((X + WIDTH)) -gt "$x" ] && [ "$Y" -lt $((y + h)) ] && [ $((Y + HEIGHT)) -gt "$y" ]; then
      echo "$((s))/$(xdotool getwindowname $((s)) 2>/dev/null)"; return 0
    fi
  done
  [ "$above" = 1 ] && return 1 || return 2
}

# `import` grabs the X server while capturing; if the window dies mid-capture it can hang holding the grab and freeze
# the whole display (observed 2026-10-18, see harness/NOTES.md). Never run it without a hard kill timeout, and only
# for a window that still exists.
IMPORT_T=${SHOT_IMPORT_TIMEOUT:-10}
xdotool getwindowname "$wid" >/dev/null 2>&1 || { echo "shot=FAILED wid=$wid (window gone)"; exit 1; }
method=window
if ! timeout -s KILL "$IMPORT_T" import -silent -window "$wid" "$out" 2>/dev/null || [ ! -s "$out" ]; then rm -f "$out"; fi
sd=0
[ -s "$out" ] && sd=$(stddev "$out")
if [ ! -s "$out" ] || uniform "$sd"; then
  geo=$(xdotool getwindowgeometry --shell "$wid" 2>/dev/null) || geo=""
  if [ -n "$geo" ]; then
    eval "$geo"   # sets X Y WIDTH HEIGHT
    cov=$(covered_by "$wid" "$X" "$Y" "$WIDTH" "$HEIGHT"); crc=$?
    if [ $crc -ne 1 ]; then
      rm -f "$out"
      [ $crc -eq 0 ] && echo "shot=FAILED wid=$wid (window capture uniform; root-crop refused: covered by $cov)" \
                     || echo "shot=FAILED wid=$wid (window capture uniform; root-crop refused: stacking unverifiable)"
      exit 1
    fi
    method=root-crop
    timeout -s KILL "$IMPORT_T" import -silent -window root -crop "${WIDTH}x${HEIGHT}+${X}+${Y}" +repage "$out" 2>/dev/null
    [ -s "$out" ] && sd=$(stddev "$out")
  fi
fi
[ -s "$out" ] || { echo "shot=FAILED wid=$wid"; exit 1; }
magick "$out" -resize 50% "$small" 2>/dev/null
echo "shot=$out method=$method stddev=$sd small=$small"
uniform "$sd" && { echo "shot: image is uniform (stddev $sd < $min)" >&2; exit 1; }
[ "$method" = root-crop ] && exit 2
exit 0
