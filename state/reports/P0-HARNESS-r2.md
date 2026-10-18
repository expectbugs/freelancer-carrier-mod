REVIEW: P0-HARNESS ROUND 2   VERDICT: PASS

All 4 MAJOR and 14 MINOR findings from round 1 are fixed or accepted, and each fix has a test that would fail on the old code. There are no BLOCKER or MAJOR findings this round, only 4 new MINORs. The selftest gives PASS with `a_eagle` and `b_gate` BLOCKED, as D109 expects. The GPU stayed at `Recovery Action: None` throughout, and the play prefix was UNCHANGED before and after.

```
REVIEW: P0-HARNESS ROUND 2   VERDICT: PASS
Branch wp/P0-HARNESS @ e05dfc9. Evidence: $FLMOD_TESTRUNS/20261018T0910Z-review-P0-HARNESS-r2/

R1 FINDINGS:
MAJOR 1 crash/hang at quit — fixed. The r1 probes now give: exit code 0xC0000005 or 1 after quit → CRASH (exit_code);
  a dw15.exe load seen only in wine.log → CRASH (dw15_loaded); quit acked but no exit → HANG (quit_no_exit).
  Control: a clean quit (trailing handled AV, exit 0) → PASS. selftest asserts clean_quit; test_verdict has a test per case.
MAJOR 2 reap race — fixed. reaprace.sh: 0/8 leaks (r1: 8/8), run while the selftest held lanes, which were not
  disturbed. Now part of test_lanes.
MAJOR 3 ack order — fixed (D111). Live log line: `ack id=h3 ok=0 err="unknown verb launch" verb=launch`; the doctest
  checks the order and the quoting.
MAJOR 4 long commands — fixed. My r1 `perf 75` probe (wined3d-sw, docked) is now PASS with 14 ev=pending lines
  (r1: HANG at 60 s, game killed). selftest b_longcmd also PASS.
MINOR 1 forged-pid gate — fixed. The forged xmessage that r1 T4b/T6b sent keys and clicks to is now refused:
  target_creator_mismatch (X-Resource). With python-xlib unavailable (import shim): xres_lookup_failed, so it fails closed.
  A lane whose owner file claims input=1 while another process holds input.lock → input_lock_not_held_by_lane.
MINOR 2 kill -9 — fixed. Only Wine processes are killed; the test_lanes bystander survives.
MINOR 3 start-up stall rule — fixed. A busy-spin start-up stall → HANG; a start-up TIMEOUT now dumps.
MINOR 4 spew fail-open — fixed. A missing allow-list now gives FAIL (probe).
MINOR 5 partial run.json — fixed (incomplete_run_json / not_ready).
MINOR 6 minidump — partially fixed, accepted. The `bt all` backtrace and failure reasons are recorded; attaching
  winedbg still kills the WoW64 game (seen again: winedbg rc=255).
MINOR 7 menu fallback/docs — fixed.
MINOR 8 b_gate hand-off — fixed. The step now uses the `target` verb.
MINOR 9 lease expiry — fixed. lane_lost abort; evidence run …-085643-lanelost-ttl45 checked.
MINOR 10 lanes / frame cap / mixing — fixed. A wined3d-sw acquire is refused while GPU lanes run
  ("classes never mix"). The d3d9.maxFrameRate cap works: fps_avg 60.0, fps_p1 59.4.
MINOR 11 D107 — fixed. End to end: harness deploy → gen redeploy (dacom.ini unchanged) → gen undeploy (harness.dacom
  kept) → harness removal → dacom.ini byte-identical to the baseline (d107_e2e.txt).
MINOR 12 screenshot root-crop — fixed.
MINOR 13 holder identity / threading — fixed.
MINOR 14 rank check / display-test interrupt — fixed. Rank 38 and 1 read in game; interrupt test PASS.

REPRODUCED:
selftest — reproduced — 20261018-091057-selftest: 7 PASS (host, b_smoke, b_eagle, b_fp9, b_longcmd, a_boot,
  concurrent), a_eagle and b_gate BLOCKED. `concurrent` hit the N19 fullscreen case (FULLSCREEN state cleared, reached
  its slot on try 2, only on the lane's own window).
test_guards 61/61; test_lanes 31/31; test_input_gate 6/6 — reproduced
test_display_awake — reproduced — 14/14 plus interrupt test PASS; temp state dir; live inhibitor 21257 untouched
pytest 138; devbridge doctest 26/26 (737 assertions) — reproduced
baseline.sh verify A / B — reproduced — PASS (23 ok) / PASS (15 ok)
harness/ci.sh --full — reproduced — PASS (public, build, host-tests incl. ASan, pytest 365+361, import-check) — 20261018T091839Z-ci
tools/check_public.py --tree — OK, 367 files; --commits=main..wp/P0-HARNESS — fails only on a5bafe5 (flhash.py,
  gen_fixture.py) → squash-merge per D106
Branch vs main: tools/ untouched; changes only under harness/ plus 2 appended lines in requirements-dev.txt

FINDINGS (new, ordered by severity):
[MINOR] harness/baseline.sh `fluf-init` vs lib/lock_holder.sh + lane.sh recreate_prefix / deploy.sh — lock-order
  inversion. fluf-init holds baseline-A.lock exclusively and then needs input.lock (`flock -w 900`). A track-A
  `--input` lane holds input.lock and then waits for baseline-A shared. A stand-in using the same locks (inversion.txt)
  made the lane wait 22 s and the stand-in time out on input.lock; the real fluf-init would stall 900 s and fail.
  Required change: one lock order, e.g. fluf-init takes input.lock before baseline-A, or lane.sh clones before the
  holder takes input.
[MINOR] harness/selftest.sh:102-105 — the selftest DLL is built only if it is missing. My worktree still had the
  r1-era DLL: b_eagle went HANG with no rank and no ev=hb (selftest_staledll.out). Rebuild when the sources are newer,
  or always (it takes seconds).
[MINOR] harness/lib/runner.py:322-358 — the runner's own window search (find, validity check, place, windowquit)
  still trusts _NET_WM_PID alone. A forged window could be moved, resized and un-fullscreened; the gate would still
  refuse input to it. Reuse xinput.xres_pid there. Not reachable by accident.
[MINOR] harness/tests/test_lanes.sh §10 — the renderer-class checks don't skip when another agent holds lanes (only
  the --perf checks do), so they fail under parallel use. Also, the b_gate BLOCKED text still describes the old T/click path.

NOTE (not this package's to fix): CI stage 30 does not run harness/tests (the harness owns no CI stage in Phase 0),
  so the 138 harness tests run only through selftest.sh.
```

- **Lanes:** I released every lane I took and removed my test windows and fake processes. No lock holders remain.
- **Prefixes:** I created no new prefixes.
- **Commits:** none. My worktree is detached at e05dfc9 and clean.
