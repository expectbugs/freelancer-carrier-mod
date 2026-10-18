REVIEW: P0-HARNESS ROUND 1   VERDICT: CHANGES_REQUIRED

There are no BLOCKERs. The play install was not touched, every wine call goes through the guards, kills stay inside the lane prefixes, and gamescope is gone. The selftest reproduced exactly. There are 4 MAJOR findings: three in verdict and hang logic and lock handling, and one where the devbridge ack line doesn't match CONVENTIONS §4. No GPU fault occurred (`GPU Recovery Action: None` after every run).

```
REVIEW: P0-HARNESS ROUND 1   VERDICT: CHANGES_REQUIRED
COVERAGE:
REQ-1:  covered — test_guards.sh 61/61, including the success case; tools/ untouched
REQ-2:  covered — clones only after play_prefix_busy reports idle, re-checks after the copy; play-prefix hashes in verify; manifest UNCHANGED before and after the review
REQ-3:  covered — baseline.sh create/verify; BASELINE.json records each tweak with its byte check
REQ-4:  covered — B keep-running patch applied; A skipped with FLUF evidence and launched with -w
REQ-5:  covered — FLUF install and dacom/freelancer/FLUF.yml edits; the fluf/dacom_fix.dll subpath loads (VERIFIED in the a_boot wine.log)
REQ-6:  covered — jflp.dll byte 0x1528 changed 33→04 and verified
REQ-7:  partial — acquire/release/status/--input/--perf work; 6 acquirers at once got 4 different lanes; recovery after a SIGKILLed holder works; reap leaks locks (MAJOR 2)
REQ-8:  covered — _NET_WM_PID checked per window (x11), vdesk title + explorer pid (A); N16 has 5 two-lane runs
REQ-9:  covered — NOT VIABLE (D103); headless modes are refused in lane.sh and runner.py
REQ-10: covered — deploy.sh/deploy.py; the D107 switch to a patch unit is still pending (MINOR 12)
REQ-11: covered — run.sh; the menu-click fallback is broken (MINOR 8)
REQ-12: partial — core, client and tests are good; the ack line deviates from CONVENTIONS §4 (MAJOR 3); nothing is written while an async command runs (MAJOR 4)
REQ-13: partial — a crash or hang during quit gives PASS (MAJOR 1); false HANG on long commands (MAJOR 4); the hang minidump has never succeeded
REQ-14: covered — `triage.py --lookup server.dll 0x14990` finds the exact entry ("no valid undock point")
REQ-15: covered — one list per track and renderer, tight anchored patterns; A covers menu only (N7/D109); a missing list fails open (MINOR 4)
REQ-16: partial — generator, specs and path refusals are good; B new_story/eagle/fp9 load VERIFIED; A load BLOCKED (D109); post-campaign gate/bar UNVERIFIED (D109); fp9 rank is not read back in game
REQ-17: covered — 14/14; live inhibitor 21257 untouched
REQ-18: covered — shot.sh has a hard kill timeout; the root-crop fallback is a concern (MINOR 13)

REPRODUCED:
harness/selftest.sh — reproduced — $FLMOD_TESTRUNS/20261018-074027-selftest/summary.md: host, b_smoke, b_eagle, b_fp9, a_boot and concurrent PASS; b_gate and a_eagle BLOCKED as D109 expects; renderer dxvk. Vision check: b_smoke launched.png shows space, the A menu has no forbidden-DLL MessageBox
test_guards.sh — reproduced — 61/61 (selftest host.log)
test_lanes.sh — reproduced — 20/20, --perf checks included
test_display_awake.sh — reproduced — 14/14; temp state dir on every call; live inhibitor, its pid file and the settings backup unchanged
pytest — reproduced — 126 passed
devbridge doctest — reproduced — 23/23 test cases, 665 assertions, ASan/UBSan on
baseline.sh verify A / verify B — reproduced — PASS (23 ok) / PASS (15 ok)
check_public --tree — reproduced — OK, 152 files
check_public --commits=main..wp/P0-HARNESS — reproduced — only a5bafe5 fails (flhash.py, gen_fixture.py, R4-decomp), the case D106 covers
git diff main...wp/P0-HARNESS -- tools/ — empty; all 52 changed files are under harness/
D109 hand-off evidence — reproduced — N7 E8 CRASH dacom.dll+0x5e6c 2/2, M0 CRASH, T1 (no FLUF) PASS; the N15 screenshots match the text
Input-gate, lock and verdict probes — $FLMOD_TESTRUNS/20261018T0740Z-review-P0-HARNESS-r1/{gate_and_lock_probes.txt,verdict_probes.txt}

FINDINGS (ordered by severity):

[MAJOR 1] harness/verdict.py:175-187,263-265; harness/lib/runner.py:902-908; harness/selftest.sh:127
  Problem: a crash or hang during or after `quit` gives PASS.
  - The exit code is only checked when early_exit is set, and after quit early_exit is never set.
  - The post-quit wait loop doesn't call tick(), so dw15.exe and crash windows go unseen.
  - "Quit acked but the process never exits" is only an info line.
  Probes:
  - trailing AV, exit code 0xC0000005 or 1 after an acked quit → PASS
  - dw15.exe loaded, visible only in wine.log → PASS
  - quit acked, no exit → PASS
  Real crashes exit nonzero (N16 conc-winid3: exit code 3). Acceptance requires "clean quit", but b_smoke doesn't assert clean_quit.
  Required change:
  - CRASH on a nonzero game exit code or a trailing system exception after quit (x11 lanes; the launcher is the game process)
  - keep tick() running in the post-quit wait
  - scan wine.log for dw15.exe loads
  - an acked quit with no exit → HANG (at least FAIL)
  - selftest asserts clean_quit; add tests for each case

[MAJOR 2] harness/lane.sh:201 (`rm -f "$FLMOD_LOCKS"/.acq-*.status`), cmd_reap 190-200
  Problem: reap deletes the status files of acquisitions still in progress.
  - The acquirer fails with "lock holder did not report within 35 s".
  - Its holder keeps the lock with no owner or env file, invisible to status and reap, until LOCK_TTL_S (4 h).
  - If the lane was taken with --input or --perf, input.lock or perf.gate is leaked as well, which stalls all input runs or all lane acquisitions.
  - reap also deletes owner/env files and kills a lane's wineserver without taking lane-N.lock first.
  - test_lanes.sh itself runs reap.
  Evidence (reaprace.sh):
  - 8/8 leaks with a concurrent reap
  - 4/4 OK without reap (control.sh)
  - 0/6 leaks with that rm disabled in a scratch copy
  Required change:
  - only remove stale status files (the acquirer's pid in the name; remove only if it is dead or the file is older than wait_s+60)
  - `flock -n lane-N.lock` before cleaning a lane, and leave it alone if the lock is held
  - add a reap-vs-acquire concurrency test

[MAJOR 3] harness/devbridge/devbridge_core.cpp:188-196; PROTOCOL.md §3/§4
  Problem: the core emits `ack id=<id> ok=0 verb=<verb> err=<text>` (seen: `ack id=h3 ok=0 verb=launch err="unknown verb launch"`).
  - CONVENTIONS §4, REQ-12 and the W1-CORE spec say `ack id=<id> ok=1|0 [err="…"]`.
  - TESTING §Devbridge matches `ack ok=0 err=timeout`.
  - PROTOCOL §3 ("ack ... ok=0 err=timeout") contradicts its own §4 key order.
  Required change: put err right after ok (`ack id= ok= [err=] verb= …`), make §3/§4 consistent, state the err quoting rule, update the doctest and pytest. Alternatively, the orchestrator amends CONVENTIONS before ARCH-0 freezes the format.

[MAJOR 4] harness/lib/runner.py:244-260; devbridge_core.cpp FinishOrPark
  Problem: HANG means "no log growth for 60 s while a command is pending", and the core writes nothing while an async command runs. A legitimate long command therefore kills a healthy game.
  Evidence: $FLMOD_TESTRUNS/20261018-080341-lane3-review-longperf (wined3d-sw, docked, `perf 75`):
  - HANG after 60.1 s with cpu_s_while_idle=795
  - shots/hang.png shows the game rendering normally
  - the lane was killed; no minidump
  S-PERF measures `perf` over 60 s and 3 min.
  Required change: the core emits a periodic `ev=pending id= verb= elapsed_s=` while a command is pending (a protocol change, so before ARCH-0), and/or the runner allows the command's own budget; add a test with a command longer than 60 s.

[MINOR 1] harness/lib/xinput.py:120-158,253-261
  The gate trusts _NET_WM_PID, which any X client can set: a forged xmessage got keys and clicks (T4b, T6b).
  It refused every real case: another lane's window, a same-title non-game window, a window on another desktop, a covered point, a foreign or duplicate vdesk.
  - Add WM_CLASS/WM_CLIENT_MACHINE checks or an XRes client-pid lookup.
  - `--prefix` mode doesn't verify that input.lock is held, and accepts any prefix-dev* prefix.

[MINOR 2] harness/lane.sh:76
  `kill -9` hits every process whose environment has WINEPREFIX=<lane>, wine or not; it killed the reviewer's `sleep`. Restrict it to wine processes or rely on `wineserver -k -w`.

[MINOR 3] runner.py:252-257, verdict.py:99-102
  The "≥25 % of a core = slow start-up" rule is unvalidated: no run has ever taken that path, and it was added right after the N16 stalls, which had no CPU data. A start-up busy-spin hang becomes TIMEOUT with no dump. Use an I/O or wine.log progress signal and dump on a start-up TIMEOUT.

[MINOR 4] verdict.py:112-126, runner.py:929-933
  The spew gate fails open when no allow list exists for the track and renderer (e.g. wined3d): a new ERROR line still gives PASS. Fail closed or refuse that renderer.

[MINOR 5] verdict.py compute_verdict
  A run.json missing ready/window_id/cmds gives PASS (`{"name":"x"}` → PASS). The runner's "ERROR" verdict is not in the documented enum.

[MINOR 6] runner.py:388-416
  The hang minidump has never succeeded (N14, and minidump=None in the review run). Record why the dump failed and add a text-backtrace fallback.

[MINOR 7] config/menu_coords.json:6, runner.py:528-535, run.sh:4
  - load_menu coordinates are null, so `--load-method menu` raises TypeError.
  - The file cites a NOTES N4 that doesn't exist.
  - run.sh documents a `--ready` option that doesn't exist.

[MINOR 8] selftest.sh:159-162, NOTES.md:413
  The N15 hand-off says `--with-gate` will run "unchanged" once a `target` verb exists, but b_gate sends `@key t` / `@key F3`, not the verb. Fix the step or the note.

[MINOR 9] config.sh:36 LOCK_TTL_S
  The 4 h lease expires silently and the runner checks the holder only at start. Soaks run up to 6 h, so another acquirer could recreate the prefix under a running game. Abort the run when the holder dies, and document --ttl.

[MINOR 10] NOTES N11/N14/N16
  - LANES=4 rests on two four-lane runs on a quiet host; under mixed load 4 of 6 instances failed.
  - "Don't mix wined3d-sw and DXVK lanes" is not enforced.
  - Instances run at about 198 fps despite DXVK_FRAME_RATE=60.
  - fps_p1 and frame pacing are not reported as the spec asks.

[MINOR 11] harness/lib/deploy.py:154-161 (D107)
  The harness still writes its own `; >>> carrier-mod` block in dacom.ini, then runs gen/run.py. Once P0-DATATOOLS merges, the gen deploy will strip that block and the DLL will silently not load. Switch to a `harness.*` patch unit and add a "DLL loaded" check.

[MINOR 12] harness/shot.sh:30-37
  The root-crop fallback captures whatever covers the game window, possibly Adam's apps, and still counts as a valid non-uniform screenshot. Check for cover first, or don't accept a root-crop as proof of rendering.

[MINOR 13] lane.sh:39-41; devbridge_core.cpp Init/Shutdown/Harness
  - holder_is_ours only checks comm == sleep, so a reused PID could be killed.
  - Init and Shutdown are not thread-checked, and Harness() is accepted from any thread before the first Tick. Document both as main-thread only.

[MINOR 14] selftest b_fp9; tests/test_display_awake.sh
  b_fp9 doesn't check rank 1 (the acceptance asks for it). test_display_awake doesn't stop its temp inhibitor if it is interrupted.
```

Housekeeping:
- I released every lane I took and removed my test windows and fake processes. I left no lock holders and created no `prefix-dev-review-harness*` prefixes; lanes 1-4 existed before and remain.
- I made no commits. My worktree is detached at 181ebcc and clean.
- Evidence is in `/home/user/freelancer/carrier-mod/local/testruns/20261018T0740Z-review-P0-HARNESS-r1/`.
