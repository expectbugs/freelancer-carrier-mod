I've stopped at a clean checkpoint. Eight of the 13 checklist items pass, two are partial, and items 7, 10 and 13 have not been run. Everything is committed on `wp/P0-TRACK-B` at `1515d38`. No lanes, locks or game processes are left. GPU Recovery Action is None and `check_public.py --tree .` passes.

```
PACKAGE: P0-TRACK-B   ATTEMPT: 1   RESULT: PARTIAL
BRANCH: wp/P0-TRACK-B @ 1515d38
SUMMARY: spike_b.dll and spike_platform_b (common header byte-identical with Track A) run with HD Edition untouched.
  19 patch sites (frame tick, 8 server vtable slots, launch-position import slot plus a client-side launch hook,
  PlayerData::save entry, launch check, button Execute/Click slots, ReShade D3D9 EndScene/Present/Reset), each
  checked before writing; addresses and original bytes are in PATCHES.md. Devbridge verbs per REQ-4, plus a YAML
  scenario runner (run_scenario.py) that can do real XTEST clicks through the harness input gate.
FILES: spikes/track_b/{CMakeLists.txt, include/*, platform/*, spike_b.cpp, tests/test_pure.cpp, scenarios/*,
  NOTES.md, RESULTS.md, PATCHES.md}, harness/scenarios/bakeoff_vmstat.yaml (Track A's file, byte-identical)
TESTS: host track_b* — PASS (5 cases); in-game scenario dirs are listed in RESULTS.md
DECISIONS: menu load uses FL's own front-end "start game" step, not LoadGame (finding 1); the server-side launch
  block uses "redock", because "skip" freezes the client (finding 6); dtGame is 0 on the frame after the pause;
  the shared vmstat route is forceland + launch at Los Angeles (same choice as Track A's file)
ENGINE FACTS LEARNED: in NOTES.md "Findings" (11 items), all VERIFIED with run dirs
OPEN QUESTIONS / BLOCKERS: real mouse clicks never reach FL's own UI buttons (item 6/7 real-click part)
KNOWN ISSUES: diagnostic traces (srv_hook lines, button Click slot) are still on; the final regression pass
  on one build has not been run
```

| # | Item | Result |
|---|---|---|
| 1 | Boot, all 38 HDE `[Libraries]` DLLs + callsign + spike_b loaded | PASS |
| 2 | Load a fixture save | PASS, asserted inside the item 3/8/9 runs; `item02_load.yaml` not run on its own |
| 3 | Dock/undock/jump hooks fire in SP | PASS |
| 4 | Game-time tick, F1 pause (real keys) | PASS |
| 5 | ImGui overlay and a real click on its button | PASS (my own vision.json; needs independent re-judging) |
| 6 | Native NavBar button | PARTIAL: appears at Manhattan and Missouri; pressing it in code works; a real click is not routed |
| 7 | Launch block | NOT RUN (scenario written) |
| 8 | Undock override | PASS (exact offset applied) |
| 9 | Save writes sidecar JSON, load reads it back | PASS |
| 10 | 60-minute soak | NOT RUN (scenario written) |
| 11 | No new FLSpew errors | PARTIAL: every run is clean under the strict check; no aggregate yet |
| 12 | Address-space headroom | PASS: `va_largest_free_mb=2048` |
| 13 | No HDE feature lost | NOT RUN |

Findings that matter beyond this package:
- **Menu load bug:** `LoadGame` from the main menu leaves an intro-scene flag set. The client then never tells the server about base enter/exit, and the first launch puts the ship at the system origin, where it dies. The harness selftest DLL's `load` has the same bug, so EF-007 never checked that the ship survives. The fix in `LoadGame` runs FL's own "start game" step.
- **Undock override:** patching only the server's launch position (what FLUF does) does not move the player in single player, because the client works out its own launch position. I added a client-side hook and now it works. Track A may hit the same wall.
- **Pause:** server game time stops during F1 but jumps forward by the whole pause on the first frame after.
- **Server launch block:** skipping the original `PlayerLaunch` freezes the client for 60 s, then drops it to the main menu.
- **Real clicks:** synthetic clicks register in FL's mouse state but FL's UI ignores them, vanilla buttons included. I have 10 hypotheses in NOTES.md "Pointer".

RESUME POINT (top of spikes/track_b/NOTES.md), next steps in order:
1. Rebuild and re-run items 1, 2, 3, 8 and 9 on the final build.
2. Run `item07_launch_block.yaml` (input lane, two runs; the second tests the "redock" backstop).
3. Item 13: deploy with `--pipeline skip`, diff `dacom.ini` and `freelancer.ini` against baseline B, write `LOST_FEATURES.md`. Note: the normal harness deploy also runs the gen pipeline, which adds `fcm_text.dll` and edits `freelancer.ini`; that is the data pipeline's change, not mine.
4. Run `ehprobe.sh --crt both`, then the in-game `ehtest` cases (verb exists, untested).
5. Run the 60-minute soak (`item10_soak.yaml`).
6. Aggregate the spew results for item 11.
7. Optionally, time-boxed, look into the real-click issue.
8. Turn off or gate the diagnostic traces, update PATCHES.md, run `check_public`, write the final report.

Harness changes I'd propose (not my files): fix the selftest DLL's menu `load`, let `@click` use `--warp`, and add `harness/scenario.sh` (my adapter fills that gap for now).
