#!/bin/bash
# End-to-end harness self test (P0-HARNESS tasks 4, 6, 7 and 10; acceptance "harness/selftest.sh PASS").
#
#   selftest.sh [--renderer auto|dxvk|wined3d|wined3d-sw] [--only step,step,...] [--skip step,...] [--strict-a]
#               [--with-gate]
#
# Steps (in order; each game step acquires its own lane, deploys, runs, releases):
#   host        host tests: tests/test_guards.sh, tests/test_display_awake*.sh (temp state dir), tests/test_lanes.sh
#               (incl. tests/reaprace.sh), tests/test_input_gate.sh,
#               pytest (verdict, triage, fixture generator, devbridge client), devbridge doctest
#   b_smoke     B: boot, devbridge `load` HARNESS_new_story, launch to space (console, input lock), non-uniform
#               screenshot of the window itself (shot rc 0, never a root crop), clean quit, verdict PASS (strict spew)
#   b_eagle     B: HARNESS_endgame_eagle is docked at Li01_01_Base (Li01), 60,000,000 credits, rank 38 (devbridge state)
#   b_fp9       B: HARNESS_lvl1_rich_fp9 is docked at Ew04_01_Base (Ew04), 5,000,000 credits, rank 1
#   b_longcmd   B: a command longer than the 60 s hang window (`perf 75`) completes: ev=pending keep-alives, ack
#               ok=1, verdict PASS (D111)
#   b_gate      B: post-campaign gate check. HARNESS_selftest_gate_post (Eagle 800 m from Li01_to_Li02): target
#               (T), dock (F3) -> the ship jumps to Li02. Control HARNESS_selftest_gate_story (gate still locked by
#               the story): same steps -> stays in Li01. The target is set with the devbridge `target <nick>` verb
#               (W1-SPAWN, CONVENTIONS §4), then F3 (dock) is pressed. BLOCKED by default: the Phase-0 selftest DLL has
#               no `target` verb, `T` selects nothing and clicks in space are refused (NOTES.md N15); --with-gate
#               runs it as written once the verb exists.
#   a_boot      A: FLUF boot to the menu in a vdesk lane: fluf.log present, the five client modules loaded, no
#               dialog windows (no forbidden-DLL MessageBox), verdict PASS
#   a_eagle     A: --save-file=HARNESS_endgame_eagle reaches the game. BLOCKED on P0-TRACK-A (any .fl in the save
#               folder crashes the A profile at the menu, harness/NOTES.md N7); runs only with --strict-a
#   concurrent  2 lanes at once: B (HARNESS_endgame_eagle_space, state/perf/vmstat) + A boot; both PASS, distinct
#               window ids, each window at its slot
#
# Every in-game step also requires a clean exit: verdict.json clean_quit (devbridge quit, then the process exited by
# itself) on B; on A (no devbridge) the game must close by itself after a window close (run.json gentle_close).
# Output: $FLMOD_TESTRUNS/<UTC stamp>-selftest/{summary.md,summary.tsv,<step>.log}. Exit 0 iff no step FAILed
# (BLOCKED and SKIP steps are listed but do not fail the self test).
source /home/user/freelancer/carrier-mod/tools/env.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/common.sh"
set -u

renderer="" only="" skip="" strict_a=0 with_gate=0
while [ $# -gt 0 ]; do
  case "$1" in
    --renderer) renderer=$2; shift ;;
    --only) only=",$2,"; shift ;;
    --skip) skip=",$2,"; shift ;;
    --strict-a) strict_a=1 ;;
    --with-gate) with_gate=1 ;;
    -h|--help) sed -n '2,/^source /{/^source /!p}' "$0"; exit 0 ;;
    *) hdie "selftest: unknown option $1" 2 ;;
  esac; shift
done
renderer=$(resolve_renderer "$renderer") || exit 2
OUT="$FLMOD_TESTRUNS/$(utc_stamp)-selftest"
mkdir -p "$OUT"
SELFTEST_DLL_DIR="$HARNESS_DIR/../build/selftest_dll"
TSV="$OUT/summary.tsv"
printf 'step\tresult\trundirs\tdetail\n' > "$TSV"
declare -A RESULT
HELD_TOKENS=()
cleanup() { local t; for t in "${HELD_TOKENS[@]}"; do "$HARNESS_DIR/lane.sh" release "$t" >/dev/null 2>&1; done; }
trap cleanup EXIT

want() { # <step>
  [ -n "$only" ] && [[ "$only" != *",$1,"* ]] && return 1
  [ -n "$skip" ] && [[ "$skip" == *",$1,"* ]] && return 1
  return 0
}
record() { # <step> <PASS|FAIL|BLOCKED|SKIP> <rundirs> <detail>
  RESULT[$1]=$2
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$TSV"
  hlog "selftest $1: $2 $4"
}
id_of() { hpy "$HARNESS_DIR/fixtures/flhash.py" "$1" | sed -n 's/.* create_id=\([0-9]*\).*/\1/p'; }
jqr() { jq -r "$2" "$1/run.json" 2>/dev/null; }
verdict_of() { jq -r .verdict "$1/verdict.json" 2>/dev/null || echo NONE; }
clean_quit_of() { jq -r .clean_quit "$1/verdict.json" 2>/dev/null || echo false; }   # B: devbridge quit + own exit
gentle_of() { jqr "$1" .gentle_close; }                                            # A: exited after a window close

# game_run <log> <track> <input 0|1> "<deploy args>" <run args...>: acquire -> deploy -> run -> release.
# Sets RUNDIR (empty if the run never started) and returns run.sh's exit code.
game_run() {
  local log=$1 track=$2 inp=$3 dep=$4; shift 4
  local acq=(--track "$track" --owner selftest --renderer "$renderer")
  [ "$inp" = 1 ] && acq+=(--input)
  local envs rc
  RUNDIR=""
  envs=$("$HARNESS_DIR/lane.sh" acquire "${acq[@]}" 2>>"$log") || { echo "acquire failed" >> "$log"; return 90; }
  local LANE LANE_TOKEN
  LANE=$(sed -n 's/^export LANE=//p' <<<"$envs"); LANE_TOKEN=$(sed -n 's/^export LANE_TOKEN=//p' <<<"$envs")
  HELD_TOKENS+=("$LANE_TOKEN")
  # shellcheck disable=SC2086
  if "$HARNESS_DIR/deploy.sh" --lane "$LANE" $dep >>"$log" 2>&1; then
    "$HARNESS_DIR/run.sh" --lane "$LANE" --renderer "$renderer" "$@" > "$log.run" 2>&1; rc=$?
    cat "$log.run" >> "$log"
    RUNDIR=$(sed -n 's/^rundir=//p' "$log.run" | tail -1)
  else
    echo "deploy failed" >> "$log"; rc=91
  fi
  rm -f "$log.run"
  "$HARNESS_DIR/lane.sh" release "$LANE_TOKEN" >>"$log" 2>&1
  return $rc
}

selftest_dll_deploy() {
  # always rebuild (a few seconds): a DLL left over from older sources would test the wrong code (review r2)
  rm -f "$SELFTEST_DLL_DIR/devbridge_selftest.dll"
  bash "$HARNESS_DIR/devbridge/selftest_dll/build.sh" >> "$OUT/build.log" 2>&1 || return 1
  [ -f "$SELFTEST_DLL_DIR/devbridge_selftest.dll" ] || return 1
  echo "--artifacts $(realpath "$SELFTEST_DLL_DIR") --dacom-lib devbridge_selftest.dll"
}

# ---------------------------------------------------------------- host
if want host; then
  log="$OUT/host.log"; fails=()
  for t in test_guards.sh test_display_awake.sh test_display_awake_interrupt.sh test_lanes.sh test_input_gate.sh; do
    echo "== $t" >> "$log"
    bash "$HARNESS_DIR/tests/$t" >> "$log" 2>&1 || fails+=("$t")
  done
  echo "== pytest" >> "$log"
  "$FLMOD_VENV/bin/python" -I -m pytest -q "$HARNESS_DIR/tests" -p no:cacheprovider >> "$log" 2>&1 || fails+=(pytest)
  echo "== devbridge doctest" >> "$log"
  bash "$HARNESS_DIR/devbridge/tests/build_and_run.sh" >> "$log" 2>&1 || fails+=(doctest)
  if [ ${#fails[@]} -eq 0 ]; then record host PASS - "all host suites passed ($log)"
  else record host FAIL - "failed: ${fails[*]} ($log)"; fi
fi

DLL_ARGS=$(selftest_dll_deploy) || DLL_ARGS=""

# ---------------------------------------------------------------- B smoke
if want b_smoke; then
  log="$OUT/b_smoke.log"
  if [ -z "$DLL_ARGS" ]; then record b_smoke FAIL - "selftest DLL build failed ($OUT/build.log)"
  else
    game_run "$log" B 1 "$DLL_ARGS --fixture HARNESS_new_story" --name selftest-b_smoke --save HARNESS_new_story \
      --launch-in-space --spew-check strict; rc=$?
    v=$(verdict_of "$RUNDIR"); launched=$(jqr "$RUNDIR" .launched); cq=$(clean_quit_of "$RUNDIR")
    shot=$(jqr "$RUNDIR" '[.shots[] | select(.name=="launched") | .rc] | first')
    if [ "$v" = PASS ] && [ "$launched" = true ] && [ "$shot" = 0 ] && [ "$cq" = true ]; then
      record b_smoke PASS "$RUNDIR" "loaded, launched to space, window screenshot non-uniform, clean quit, verdict PASS"
    else record b_smoke FAIL "${RUNDIR:--}" "verdict=$v launched=$launched shot_rc=$shot clean_quit=$cq rc=$rc"; fi
  fi
fi

# ---------------------------------------------------------------- B fixture validity
fixture_state_step() { # <step> <fixture> <base> <system> <cash> <rank>
  local step=$1 fx=$2 base=$3 sys=$4 cash=$5 rank=$6 log="$OUT/$1.log" bid sid
  bid=$(id_of "$base"); sid=$(id_of "$sys")
  local cmds="$OUT/$step.cmds"; printf 'state\n' > "$cmds"
  # rank: Server.dll pub::Player::GetRank, read in game by the selftest DLL's `state` (review r1 m14)
  game_run "$log" B 0 "$DLL_ARGS --fixture $fx" --name "selftest-$step" --save "$fx" --cmds "$cmds" \
    --expect "verb=state state=docked .*cash=$cash .*base_id=$bid system_id=$sid .*rank=$rank "; local rc=$?
  local v cq; v=$(verdict_of "$RUNDIR"); cq=$(clean_quit_of "$RUNDIR")
  if [ "$v" = PASS ] && [ "$cq" = true ]; then
    record "$step" PASS "$RUNDIR" "docked at $base ($bid) in $sys ($sid), cash $cash, rank $rank (read in game), clean quit"
  else record "$step" FAIL "${RUNDIR:--}" "verdict=$v clean_quit=$cq rc=$rc (want docked base_id=$bid system_id=$sid cash=$cash rank=$rank)"; fi
}
if want b_eagle; then
  [ -n "$DLL_ARGS" ] && fixture_state_step b_eagle HARNESS_endgame_eagle Li01_01_Base Li01 60000000 38 \
    || record b_eagle FAIL - "selftest DLL missing"
fi
if want b_fp9; then
  [ -n "$DLL_ARGS" ] && fixture_state_step b_fp9 HARNESS_lvl1_rich_fp9 Ew04_01_Base Ew04 5000000 1 \
    || record b_fp9 FAIL - "selftest DLL missing"
fi

# ---------------------------------------------------------------- B long command (D111)
if want b_longcmd; then
  log="$OUT/b_longcmd.log"
  if [ -z "$DLL_ARGS" ]; then record b_longcmd FAIL - "selftest DLL missing"
  else
    cmds="$OUT/b_longcmd.cmds"; printf 'state\nperf 75\nstate\n' > "$cmds"
    game_run "$log" B 0 "$DLL_ARGS --fixture HARNESS_endgame_eagle_space" --name selftest-b_longcmd \
      --save HARNESS_endgame_eagle_space --cmds "$cmds"; rc=$?
    v=$(verdict_of "$RUNDIR"); cq=$(clean_quit_of "$RUNDIR")
    np=$(grep -c 'ev=pending id=\S* verb=perf' "$RUNDIR/devbridge_log.txt" 2>/dev/null)
    pa=$(grep -o 'ack id=\S* ok=1 verb=perf .*' "$RUNDIR/devbridge_log.txt" 2>/dev/null | head -1)
    if [ "$v" = PASS ] && [ "$cq" = true ] && [ "${np:-0}" -ge 10 ] && [ -n "$pa" ]; then
      record b_longcmd PASS "$RUNDIR" "perf 75 completed ($np ev=pending keep-alives; $pa), no false HANG, clean quit"
    else record b_longcmd FAIL "${RUNDIR:--}" "verdict=$v clean_quit=$cq keepalives=$np ack='$pa' rc=$rc"; fi
  fi
fi

# ---------------------------------------------------------------- B post-campaign gate
if want b_gate && [ $with_gate = 0 ]; then
  record b_gate BLOCKED - "needs the devbridge \`target\` verb (W1-SPAWN; the Phase-0 selftest DLL has none), NOTES.md N15; --with-gate runs it"
elif want b_gate; then
  log="$OUT/b_gate.log"; li02=$(id_of Li02); li01=$(id_of Li01)
  cmds="$OUT/b_gate.cmds"
  printf 'state\n@sleep 3\ntarget Li01_to_Li02\n@sleep 1\n@shot target\n@key F3\n@sleep 3\n@shot docking\n@wait_state system_id=%s 150\n@shot after\nstate\n' \
    "$li02" > "$cmds"
  ccmds="$OUT/b_gate_control.cmds"
  printf 'state\n@sleep 3\ntarget Li01_to_Li02\n@sleep 1\n@shot target\n@key F3\n@sleep 3\n@shot docking\n@sleep 60\n@shot after\nstate\n' > "$ccmds"
  if [ -z "$DLL_ARGS" ]; then record b_gate FAIL - "selftest DLL missing"
  else
    game_run "$log" B 1 "$DLL_ARGS --fixture $HARNESS_DIR/fixtures/selftest/HARNESS_selftest_gate_post.yaml" \
      --name selftest-b_gate_post --save HARNESS_selftest_gate_post --cmds "$cmds" --load-timeout 120
    post=$RUNDIR; vp=$(verdict_of "$post")
    game_run "$log" B 1 "$DLL_ARGS --fixture $HARNESS_DIR/fixtures/selftest/HARNESS_selftest_gate_story.yaml" \
      --name selftest-b_gate_story --save HARNESS_selftest_gate_story --cmds "$ccmds" --load-timeout 120
    ctl=$RUNDIR; vc=$(verdict_of "$ctl")
    ctl_jumped=0; grep -q "system_id=$li02" "$ctl/devbridge_log.txt" 2>/dev/null && ctl_jumped=1
    ctl_li01=0; grep -q "verb=state state=space .*system_id=$li01 " "$ctl/devbridge_log.txt" 2>/dev/null && ctl_li01=1
    if [ "$vp" = PASS ] && [ "$vc" = PASS ] && [ $ctl_jumped = 0 ] && [ $ctl_li01 = 1 ]; then
      record b_gate PASS "$post $ctl" "post-campaign: jumped Li01 -> Li02 through Li01_to_Li02; story control stayed in Li01"
    else
      record b_gate FAIL "${post:--} ${ctl:--}" "post verdict=$vp; control verdict=$vc jumped=$ctl_jumped in_li01=$ctl_li01"
    fi
  fi
fi

# ---------------------------------------------------------------- A boot
a_boot_expects=(--expect 'Loaded Module: FLUF CrashWalker' --expect 'Loaded Module: Debugger'
                --expect 'Loaded Module: Story Factions' --expect 'Loaded Module: Story Enhancements'
                --expect 'Loaded Module: Delay Display')
a_boot_check() { # <rundir> -> prints the failure detail, empty if OK
  local d=$1 v
  v=$(verdict_of "$d")
  [ "$v" = PASS ] || { echo "verdict=$v"; return; }
  [ -s "$d/fluf.log" ] || { echo "fluf.log missing"; return; }
  [ "$(gentle_of "$d")" = true ] || { echo "the game did not exit by itself after a window close"; return; }
  [ "$(jq -r '(.dialogs // []) | length' "$d/run.json")" = 0 ] || { echo "dialog windows: $(jq -c .dialogs "$d/run.json")"; return; }
}
if want a_boot; then
  log="$OUT/a_boot.log"
  game_run "$log" A 0 "" --name selftest-a_boot --hold-s 10 "${a_boot_expects[@]}"
  why=$(a_boot_check "$RUNDIR")
  if [ -n "$RUNDIR" ] && [ -z "$why" ]; then record a_boot PASS "$RUNDIR" "FLUF menu, fluf.log, 5 modules loaded, no dialogs"
  else record a_boot FAIL "${RUNDIR:--}" "$why"; fi
fi

# ---------------------------------------------------------------- A fixture load
if want a_eagle; then
  if [ $strict_a = 1 ]; then
    log="$OUT/a_eagle.log"
    game_run "$log" A 0 "--fixture HARNESS_endgame_eagle" --name selftest-a_eagle --save HARNESS_endgame_eagle \
      --load-method fluf --load-timeout 60 --hold-s 20
    v=$(verdict_of "$RUNDIR")
    if [ "$v" = PASS ]; then record a_eagle PASS "$RUNDIR" "--save-file load ran without a crash (docked state not observable without an A devbridge)"
    else record a_eagle FAIL "${RUNDIR:--}" "verdict=$v (known: NOTES.md N7)"; fi
  else
    record a_eagle BLOCKED - "P0-TRACK-A: any .fl in the save folder crashes HDE+FLUF at the menu (dacom.dll+0x5e6c, NOTES.md N7); --strict-a runs it"
  fi
fi

# ---------------------------------------------------------------- concurrency
if want concurrent; then
  log="$OUT/concurrent.log"
  if [ -z "$DLL_ARGS" ]; then record concurrent FAIL - "selftest DLL missing"
  else
    cmds="$OUT/concurrent.cmds"; printf 'state\nperf 10\nvmstat\nstate\n' > "$cmds"
    ( game_run "$log.b" B 0 "$DLL_ARGS --fixture HARNESS_endgame_eagle_space" --name selftest-conc-b \
        --save HARNESS_endgame_eagle_space --cmds "$cmds"; echo "$RUNDIR" > "$OUT/.conc_b" ) &
    pb=$!
    ( game_run "$log.a" A 0 "" --name selftest-conc-a --hold-s 30 "${a_boot_expects[@]}"; echo "$RUNDIR" > "$OUT/.conc_a" ) &
    pa=$!
    wait $pb $pa
    cat "$log.b" "$log.a" > "$log" 2>/dev/null; rm -f "$log.b" "$log.a"
    db=$(cat "$OUT/.conc_b" 2>/dev/null); da=$(cat "$OUT/.conc_a" 2>/dev/null); rm -f "$OUT/.conc_a" "$OUT/.conc_b"
    vb=$(verdict_of "$db"); why=$(a_boot_check "$da")
    [ "$(clean_quit_of "$db")" = true ] || vb="$vb(no clean quit)"
    wb=$(jqr "$db" .window_id); wa=$(jqr "$da" .window_id)
    ob=$(jqr "$db" .window_placed.ok); oa=$(jqr "$da" .window_placed.ok)
    if [ "$vb" = PASS ] && [ -z "$why" ] && [ "$wb" != "$wa" ] && [ "$ob" = true ] && [ "$oa" = true ]; then
      record concurrent PASS "$db $da" "B in space (window $wb) and A at the menu (window $wa) at once, both PASS, both at their slots"
    else
      record concurrent FAIL "${db:--} ${da:--}" "B verdict=$vb; A: ${why:-ok}; windows $wb/$wa placed $ob/$oa"
    fi
  fi
fi

# ---------------------------------------------------------------- summary
fails=0
{
  echo "# harness selftest $(basename "$OUT")"
  echo
  echo "renderer=$renderer, git $(git_sha | cut -c1-12), $(date -Is)"
  echo
  echo "| Step | Result | Run dirs | Detail |"
  echo "|---|---|---|---|"
  tail -n +2 "$TSV" | while IFS=$'\t' read -r s r d t; do echo "| $s | $r | $d | $t |"; done
} > "$OUT/summary.md"
for s in "${!RESULT[@]}"; do [ "${RESULT[$s]}" = FAIL ] && fails=$((fails+1)); done
echo "selftest: $OUT/summary.md"
cat "$OUT/summary.md"
[ $fails -eq 0 ] && { echo "selftest=PASS"; exit 0; }
echo "selftest=FAIL ($fails step(s))"; exit 1
