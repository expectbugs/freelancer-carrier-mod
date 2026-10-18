# P0-HARNESS working notes (bugs, hypotheses, experiments)

Evidence paths are under `/home/user/freelancer/carrier-mod/local/testruns/` (`$FLMOD_TESTRUNS`).

## RESUME POINT (fix round 1 of attempt 1, 2026-10-18 ~08:45Z)

Branch `wp/P0-HARNESS` (main merged in at e666b6d: P0-REPO, P0-TOOLCHAIN, P0-SIDECAR, P0-DATATOOLS). Review r1
(`state/reports/P0-HARNESS-r1.md`) findings are all addressed; N18 lists what changed and why, N17 is the frame cap.
Section index: N1 X freeze; N2 Track A size; N3 gamescope (NOT VIABLE); N5 FL cursor; N6 X stalls; N7 Track A + any
save crash (P0-TRACK-A, D109); N8 GPU fault; N9 input incident + gate; N10 renderer fallback; N11 concurrency + lane
count; N12 reference citations (D106); N13 shared window id bug; N14 hang dump / start-up stalls; N15 post-campaign
checks (W1-HARNESS, D109); N16 REQ-8 evaluation; N17 DXVK frame cap; N18 fix-round changes.

### State

| Item | State |
|---|---|
| Review r1 MAJOR 1-4, MINOR 1-14, baseline flock | DONE (commits 9ed7527, 791a3ff, 6520d4e; MINOR 11 = D107 harness.dacom unit after the merge) |
| Host tests | test_guards 61, test_lanes 30 (incl. reaprace 0/6 leaks, render classes, baseline lock), test_display_awake 14 + interrupt test, test_input_gate 6, pytest 137, doctest 26 |
| In game | selftest (see the latest `*-selftest/summary.md`), mixload 12/12 at 60 fps, perf 75 PASS |
| Carried (D109) | Track A save load (P0-TRACK-A); post-campaign gate/bar (W1-HARNESS, needs the `target` verb) |

### Next steps (for a further fix round or the next owner)

1. P0-TRACK-A: N7; then `selftest.sh --strict-a`, and rebuild the A allow-lists with a save load.
2. When a devbridge `target` verb exists: `selftest.sh --with-gate` (N15).
3. Track A has no heartbeat while idle (no devbridge): a frozen A game during `--hold-s` is not detected yet.

### State outside the repo

| Path | State |
|---|---|
| `/home/user/freelancer/prefix-dev-base-A`, `-B` | clean baselines (never launched in place) |
| `/home/user/freelancer/prefix-lane-1..4` | disposable, recreated by every `lane.sh acquire` |
| `$FLMOD_VENV` | + python-xlib 0.33 (X-Resource lookup; `requirements-dev.txt`) |
| `$FLMOD_TESTRUNS` | run dirs; `p0-harness-evidence/` (concurrency, mixload, probes, montages) |
| `<worktree>/build/` | selftest DLL + host test binaries (rebuild: `devbridge/selftest_dll/build.sh`, `devbridge/tests/build_and_run.sh`) |

## N1. Track A runs went bad after the first one (2026-10-18 04:42-04:53 UTC)

**Observations**

- O1 `20261018-044114-lane2-boot-menu-A`: fresh lane from baseline A; reached the main menu (PASS). The window
  came up at 3744x2106 although `SAVE/PerfOptions.ini` said `size= 1280, 720`; afterwards FL had rewritten it to
  `size= 3744, 2106`.
- O2 `…-044214-lane2-res-1280x720`: same lane, PerfOptions line hand-edited back (with a stray `\r`); the game
  crashed ~1 s after its window appeared: `Unhandled page fault on read access to 71B1984A at address 065B5E6C`,
  triage: `dacom.dll+0x5e6c`, exit code 5. `shot.sh` then timed out after 60 s.
- O3-O5 (`res-1024x768`, `res-1280x960`, `res-1920x1080`): Freelancer.exe appeared only ~30 s after launch, no
  window was ever found, the logs stopped growing (HANG), and `winedbg --minidump` timed out after 120 s.
- At 04:53 an `import -window 146800641 …/res-1280x720/shots/final.png` process (orphaned when shot.sh was killed
  by the runner's 60 s timeout) was still alive, and `xdotool getdisplaygeometry` timed out: **the X display was
  frozen**. Killing that `import` immediately restored X (`xdotool getdisplaygeometry` → `3744 2106`).

**Hypotheses (O3-O5 hang / slow start / no window)**

1. A hung `import` holds an X server grab (ImageMagick grabs the server while capturing; the window was destroyed
   mid-capture by the O2 crash), so every X client — the new game windows, xdotool, the orchestrator's desktop —
   blocks. **Confirmed**: X frozen while the orphan lived, responsive right after it was killed.
2. Leftover wine processes/wineserver of the previous run in the same prefix delayed the next start.
3. The hand-edited PerfOptions line (`\r` inside an LF file) made FL choose a bad mode.
4. Without JFLP/FLSharp, FL rejects non-4:3 / non-listed modes and falls back to the desktop size, and mode
   switching through dxwrapper → ReShade → DXVK misbehaves.
5. FLUF.CrashWalker fetches crash-offsets.json with libcurl at start-up; a network stall delays start by ~30 s.
6. FLUF's 404 MiB DWARF image fragments the 32-bit address space → random allocation failures.
7. The killed `winedbg --minidump` left the lane prefix (wineserver/debug objects) in a bad state.
8. A DXVK/driver resource left over from the crashed instance (shader cache lock, GPU context) blocked the next.
9. HudShift/console.dll/other HDE plugins racing FLUF's hooks during `[Libraries]` loading (crash in DACOM).
10. Another agent's game instance competing for the GPU/display at the same time.
11. FLUF writes its log/CrashWalker files under `My Games` (GetUserDataPath before flplusplus' detour) while
    flplusplus redirects saves to `SAVE` — inconsistent user-data paths.

**Experiment chosen:** kill the orphan and probe X (cheapest; discriminates H1 against all others at once). Result:
H1 confirmed for the freeze. Fix: `shot.sh` and every `import` in the harness now run under `timeout -s KILL`, only
for windows that still exist; the runner never screenshots a dead game. Killing the client releases its grab.
O2 (the dacom.dll crash) is a separate question → N2.

## N6. X server stalls reported by P0-SIDECAR (04:50Z-05:10Z) and the hang-dump path

P0-SIDECAR saw new X11 connections to `:0` time out (15 s) from ~04:50Z to ~05:10Z.

- **Attributed (VERIFIED):** the orphaned `import` from N1 was alive from 04:42Z (the res-1280x720 crash) until I
  killed it at ~04:53Z; during that time `xdotool getdisplaygeometry` timed out, and right after the kill it
  answered. Every harness `import` now runs under `timeout -s KILL` and only for windows that still exist.
- **A healthy `import` does not freeze X (VERIFIED, `grabtest`, 2026-10-18):** a full 3744x2106 `import -window root`
  took ~7 s while a concurrent client's `getdisplaygeometry` never exceeded 115 ms (ffmpeg x11grab: 1.5 s, max 71 ms).
  So the freeze needed the hung/killed-mid-capture state, not ordinary captures.
- **The `winedbg --minidump` runs (04:45Z, 04:49Z, 04:52Z) timed out after 120 s.** They ran while X was already
  frozen by the orphan, so the game (blocked on X) could not be suspended/dumped in time. Whether a dump can itself
  freeze X (a suspended Wine thread holding an X grab) is UNVERIFIED; treated as possible.
- **04:53Z-05:10Z is UNVERIFIED.** Candidates: (a) residual effects of the frozen period (clients reconnecting);
  (b) my Track A runs at 3744x2106 (04:55Z-04:59Z) with `import -window` of a desktop-sized DXVK window (normally no
  grab, see above); (c) gamescope nested start-up (05:00Z-05:03Z) creating an SDL window / Xwayland; (d) another
  session's X client. I have no per-second X-latency record for that window, so I can't separate these.
- **Mitigations now in the runner:** an X liveness probe every 10 s (fresh connection, 3 s limit; stalls > 1 s go
  to `run.json` `x_stalls`), and the hang dump is bounded (`HANG_DUMP_S`=30 s instead of 120 s), skipped if X is
  already unresponsive, and abandoned (lane killed, which releases any grab the game held) as soon as X stops
  answering during the dump. Track A lanes now run inside gamescope (nested/headless), whose screenshots use
  `gamescopectl`, not `import`.

## N7. Track A crash at the main menu: `dacom.dll+0x5e6c` = `stricmp(garbage)`

**Observations (VERIFIED, run dirs below)**

- `dacom+0x5e6c` lies inside dacom's exported `stricmp` (RVA 0x5e60, `llvm-objdump -p dacom.dll`); the faulting
  instruction is `movzbl (%esi),%ecx` with ESI=`0x71B1984A`: someone passed a garbage string pointer. The **same
  garbage value** appears in every occurrence, so it is deterministic data, not random memory. The stack is
  unwalkable (EBP garbage), so the caller is unknown.
- It happens ~2 s **after** `Starting single player game` (main menu reached) — not during DLL loading.
- Occurrences: `…-044214-lane2-res-1280x720` (x11 lane, 2nd launch in that lane, no fixture, no selftest DLL,
  hand-edited PerfOptions); `…-052402-lane2-load-HARNESS_endgame_eagle-A`, `…-052725-…-A-1`, `…-052744-…-A-2`
  (gamescope nested, selftest DLL + fixture `HARNESS_endgame_eagle` + `--save-file`): 3/3 with that recipe.
- Non-occurrences: 10/10 plain boots (`p0-harness-evidence/boot_rep_A_x10.txt`, nested, no fixture, no selftest),
  3/3 plain x11 boots, the res tests, fluf-init launches.

**Hypotheses**

1. FLUF's debugger module (`--save-file`) presses menu buttons ~55 frames after the menu and its save matching
   reaches a `stricmp` with a bad pointer (e.g. a save field it doesn't expect from our generated `.fl`).
2. FL's own save-list scan of our fixture `.fl` hits a field the A build (no FLSharp `save_crash_fix`) can't
   handle (R5 §3.5: FLSharp adds null checks in the save scan; FLSharp is removed on A).
3. The selftest DLL in `[Libraries]` (no version resource: dacom logs `[0.0.0]`) confuses something that later
   compares DLL names.
4. MultiIntro's random menu scene (4 variants) makes one variant crash under FLUF (would explain O2 without a fixture).
5. A second launch in the same lane leaves state (My Games `fluf.log`, `FLUF.CrashWalker.yml`) that changes
   start-up (O2 was a 2nd launch).
6. The stray `\r` in O2's hand-edited PerfOptions line.
7. FLUF's `story_factions`/`story_enhancements` read `[mPlayer]`/rep data from the save list and compare names.
8. A `Restart.fl` regenerated by flplusplus from our fixture's `newplayer.fl` template mismatching A's data.
9. Timing: FLUF.CrashWalker's libcurl fetch finishing during the menu and racing the main thread.
10. A HUD plugin (HudShift and friends load after FLUF) reacting to the menu → game transition.

**Experiments, session 2 (DXVK, vdesk lane 1, 2026-10-18 06:40-06:47Z; run dirs `<stamp>-lane1-n7-*`)**

| # | Recipe (Track A baseline, `-w`) | Result | Discriminates |
|---|---|---|---|
| E1 | selftest DLL + `HARNESS_endgame_eagle` + `--save-file` | CRASH 1/1 (`…-064006-…-E1-…`) | reproduces on DXVK outside gamescope |
| E2 | selftest DLL + fixture, **no** `--save-file` | CRASH 3/3 (`…-064052/064119/064147-…-E2-*`) | rules out H1 (FLUF debugger load path) |
| E6 | fixture only (no selftest, no `--save-file`) | CRASH 3/3 (`…-064218/064245/064313-…-E6-*`) | rules out H3 (selftest DLL) |
| E7 | `HARNESS_new_story` fixture only | CRASH 2/2 (`…-064406/064433-…-E7-*`) | not specific to the post-campaign content |
| E8 | the game's own `EXE/newplayer.fl` copied as `SAVE/Accts/SinglePlayer/nptest.fl` | CRASH 2/2 (`…-064508/064535-…-E8-*`) | **any** `.fl` crashes A: rules out every "our fixture content" hypothesis |
| M0 | `HARNESS_new_story`, FLUF.yml `clientConfig.modules: []` | CRASH 1/1 (`…-064627-…-mod-none-…`) | rules out H7/H9 (story_factions/enhancements, CrashWalker) and the debugger module |
| T1 | `HARNESS_new_story`, FLUF.dll and dacom_fix.dll commented out of dacom.ini (forbidden DLLs still off) | **PASS** 1/1, 20 s at the menu (`…-064725-…-dacom-nofluf-…`) | FLUF core is necessary; FLSharp's absence alone is not the cause (rules out H2 as stated) |

Also seen: the selftest DLL logs `ev=selftest_hook_failed bytes=E93B289DE657896C` on A: the frame function 0x5B2890
already starts with a `jmp` (another A component detours it), so the selftest DLL stays inert on A (by design). The
garbage pointer is `0x71B1984A` with the five modules and `0x7673984A` with none: the low 16 bits are constant and
the high half moves with the module layout. No module is mapped at either base in the `+loaddll` trace.

**Conclusion (VERIFIED by the table above):** Track A = HDE + FLUF nightly 2026-10-16 crashes ~2 s after the main
menu appears whenever the single-player save folder contains at least one `.fl` file. FLUF core alone (no modules)
is enough; the same profile without FLUF.dll is fine. This is a **Track A profile problem for P0-TRACK-A**, not a
harness or fixture problem. Leading candidates (UNVERIFIED): FLUF's server-side save parsing patches (the
house-entry patch it applies at server.dll+0x679C6 / +0x78B39, see `FLUF/Source/Server/FlufServer.cpp` ~584) or
its single-player account/character mirroring (`Server/Database/AccountManager.cpp`). Next experiments for
P0-TRACK-A: the stable 2.0 FLUF release; FLUF core with the house-entry patch bytes restored right after start-up;
a `+relay` or breakpoint trace on dacom `stricmp` to get the caller.

Reproduce: `lane.sh acquire --track A`; `deploy.sh --lane N --fixture HARNESS_new_story`; `run.sh --lane N
--renderer dxvk --hold-s 20` → `verdict=CRASH fault=dacom.dll+0x5e6c` within ~6 s of launch.

Consequence for this package: the Track A fixture-load acceptance item (`--save-file=HARNESS_endgame_eagle`, docked
at Manhattan) cannot pass on the current A profile; it is reported BLOCKED on P0-TRACK-A. Track A boot (menu, FLUF
log, modules, no dialogs) does pass.

## N8. GPU stopped creating Vulkan devices (~05:28Z)

From 05:28:03Z every gamescope start failed (`vulkan_remake_swapchain` assert, then `vkCreateDevice failed (-3)`);
`vulkaninfo --summary` fails system-wide with `ERROR_INITIALIZATION_FAILED`; `nvidia-smi -q` reports
`GPU Recovery Action: Reset`; OpenGL (`glxinfo -B`) still works; no nvidia/vulkan files changed. It followed the
two N7 crashes (Wine `winedbg --auto` + the runner's `wineserver -k`). Cause UNVERIFIED (no dmesg without sudo):
a GPU fault from killing a process mid-submission, resource exhaustion after ~40 launches in 60 min, or another
GPU user (frigate, ffmpeg, sidecar CUDA tests). Recovery needs a GPU reset / reboot, outside a package's authority.
Reported to the orchestrator at 05:39Z. All in-game work paused.

## N9. Synthetic input reached Adam's Steam window (reported by Adam, 2026-10-18)

**What sent input 04:40Z-05:30Z** (from my run dirs and scratch scripts; times UTC):

| Time | Run / script | Input | Guard at the time |
|---|---|---|---|
| 04:40Z, 04:41Z | `…-baselineA-fluf-init` launch1 | `windowactivate --sync <dialog>` + `key Return` (FLUF "No ship classes") | none (no active-window check) |
| 05:06:48Z | `…-050637-lane1-load-HARNESS_new_story-B` | `windowactivate --sync`, `mousemove --window 760 30`, `click 1` | none |
| 05:08:37Z | `…-050837-lane1-activate` | activate/raise/focus + `mousemove` (no click/key) | none |
| 05:09:39Z | `…-050928-lane1-load-HARNESS_new_story-B` | click 760,30 | active window + stacking checked once |
| 05:11:29Z | `…-051129-lane1-click-exp` | relative moves, warp, mousedown/up at 760,30 | none |
| 05:12:43Z | `…-051243-lane1-click-exp` | clicks at 580,30 and 760,30; the second landed at screen (1366,61) on `Desktop` (xfdesktop) | none |
| 05:14:31Z | `…-051431-lane1-input-exp` | minimize/activate round trip; clicks; F1/Escape | xinput v1 (checked once per step) |
| 05:15-05:20Z | `cursor-cal`, `cursor-cal2`, `ptrtrace`, `click-reckon` | relative mouse sweeps (±1279 px), one click | none for the sweeps |
| 05:21:36Z | `…-052136-lane1-load-HARNESS_new_story-B` | Return, typed `launch`, Return (console) | checked before the first key only |

No run after 05:22Z sent input. VERIFIED evidence of a miss: the 05:06:48Z run's `shots/launched.png` (root-crop fallback,
taken ~70 s after the click) shows the Steam store window over the game's slot at (0,0); `xprop` at ~05:09Z showed
Steam maximized at (0,0) 3744x2043 and `_NET_WM_STATE_FOCUSED`.

**Hypotheses (how input reached Steam)**

1. The 05:06:48Z click: Steam (maximized, full screen) was stacked above the game window at slot (0,0) and
   `windowactivate --sync` did not raise the game, so `click 1` at screen (760,30) hit Steam's title area.
2. Focus-stealing prevention in xfwm4 refused `_NET_ACTIVE_WINDOW`; keys/clicks then went to the focused app.
3. The game warps the X pointer (observed jumps to (1345,506), (1366,61)); a click issued after a warp landed
   outside the game window, on whatever was below (Steam covers the whole screen when maximized).
4. Unchecked relative sweeps (05:15-05:20Z) dragged the pointer across Steam while Steam had focus (hover/scroll).
5. The fluf-init Return (04:40Z) went to the focused window if the dialog wasn't activated.
6. Console typing (05:21Z) was only checked before the first key; a focus change mid-typing would send the rest
   of `launch` + Return to the newly focused app.
7. A Steam notification/pop-up raised Steam above the game between activation and the click.
8. The click opened a Steam menu; later keys (F1/Escape at 05:14Z) went to that menu.
9. `windowminimize`/`windowactivate` round trip (05:14Z) left Steam active after the restore.
10. Mouse wheel/button state stuck after a killed xdotool, applying to the next window.

**Fix (now):** `lib/xinput.py` is the only input path; it gates every key, every typed character, every batch of
pointer motion and each button event on: lane input lock, target window `_NET_WM_PID` = the lane's Freelancer.exe,
window on the current workspace (never switch desktops; refuse if `windowactivate` would), active window
`_NET_WM_PID` = game after activation, pointer inside the game window and the point uncovered. Refusal prints
`HARNESS input_refused reason=... active=<wid/name>` and sends nothing; there is no fallback. `baseline.sh`'s
dialog Return goes through the same gate. The runner records each window's `_NET_WM_DESKTOP` and refuses
screenshots of windows on another workspace.

**Workspace switch vs the crashes and the GPU fault (N7/N8).** Adam switched to desktop 2 at ~05:25-05:26Z
(orchestrator). Run start times (UTC, from run dir names): first `dacom+0x5e6c` crash with the selftest+save recipe
**05:24:02Z** (window 05:24:06Z) — before the switch, so the switch is not needed for that crash; A boots x10
05:25:02-05:26:44Z, all PASS (gamescope nested windows; their workspace was not recorded then — UNVERIFIED which
desktop each was created on); crashes 05:27:25Z and 05:27:44Z; Xid 51 (Xwayland, BAD_TSG) at 05:28:03Z, the start
of the next gamescope. Added hypothesis for N8: gamescope SDL windows left on the old workspace were unmapped by the
switch, forcing swapchain rebuilds (`vulkan_remake_swapchain` assert seen at 05:28) that ended in the Xid. Added
hypothesis for N7: none (the 05:24Z crash predates the switch).

## N2. Track A resolution and the O2 crash

Track A ignores `size= 1280, 720` (window 3744x2106, PerfOptions rewritten). Still open; see the run log below.

## N3. Headless lanes via gamescope (REQ-9): evaluated, then banned

- Nested (`gamescope -w 1280 -h 720 --backend sdl`) and headless (`--backend headless`) both reached the Track A main
  menu in ~6 s once `ENABLE_GAMESCOPE_WSI=0` was set (without it DXVK picked gamescope's WSI layer and the game never
  showed a window: `…-050037-lane2-gamescope-sdl-A` menu_reached=0). Screenshots worked through `gamescopectl`
  (`…-050325-lane2-gamescope-headless-A/gs_shot.png`). VERIFIED by those run dirs.
- At 05:28Z gamescope's Xwayland faulted the GPU (Xid 51/154, N8, D103). gamescope is banned on this host for the
  build, so the REQ-9 verdict is **NOT VIABLE** (`HEADLESS_USABLE=0`); every lane runs on `:0`. `lane.sh` refuses
  `--headless` and the runner refuses any display mode other than `x11|vdesk`.

## N5. Mouse input: FL draws its own cursor from relative motion

- FL's cursor follows relative pointer deltas, not the absolute X pointer: after an absolute warp the drawn cursor
  stays where it was, and the game warps the X pointer itself (seen at (1345,506) and (1366,61)). Calibration runs
  `…-051544-lane1-cursor-cal`, `…-051654-lane1-cursor-cal2` (`r.txt`, crops): parking the pointer and sweeping to
  the top-left clamps FL's cursor at (0,0); relative moves then land at target × ~1.034 (`FL_CURSOR_GAIN`).
- Consequence: menu clicks are unreliable and avoided. Loads go through the devbridge (`load`), launches through the
  adoxa console chat command (`xinput.py console launch`, keyboard only). `xinput.py click` exists for experiments
  only and always passes the gate (N9).

## N10. Renderer fallback while the GPU was degraded

- After the N8 fault, hardware wined3d (`WINEDLLOVERRIDES=d3d8=b;d3d9=b` on the NVIDIA GL driver) failed as well:
  `GL_OUT_OF_MEMORY` / `GLXBadContextState` in `…-054729-lane1-rtest-nvgl-B/wine.log`, plus GPFIFO RESET_REQUIRED
  lines in the kernel log per launch. Mesa llvmpipe (`__GLX_VENDOR_LIBRARY_NAME=mesa LIBGL_ALWAYS_SOFTWARE=1`) worked
  (`…-054702-lane1-rtest-llvmpipe-B/menu.png`) and touches no NVIDIA channel. Hence `FLMOD_RENDERER=auto|dxvk|
  wined3d|wined3d-sw`, with `auto` = dxvk when `vulkaninfo --summary` succeeds, else `wined3d-sw` (D105).
- After the reboot (session 2) `auto` resolves to dxvk again (VERIFIED: every session-2 run records
  `renderer=dxvk` in `verdict.json`).

## N11. Concurrency and lane count (session 2, DXVK, 2026-10-18 06:50-06:54Z)

Each lane: acquire → deploy (selftest DLL + fixture) → boot → devbridge `load` → `state`, `perf 10`, `vmstat` →
screenshot → `quit` → release, all started at the same moment. GPU sampled every 2 s (`gpu.txt`); 10-15 % GPU load
was already present from other users before the runs.

| Instances | Mix | Verdicts | fps_avg per instance (devbridge `perf 10`, in space) | GPU max util / mem | Evidence (`p0-harness-evidence/`) |
|---|---|---|---|---|---|
| 1 | B in space | PASS | 198.4 | - | `…-064916-lane1-space-perf-B-1` |
| 2 | B in space + A menu | PASS, PASS | 198.5 (B) | 62 % / 2.9 GB | `conc-AB2-20261018-065012` |
| 2 | B space + B docked | PASS, PASS | 198.0, 198.1 | 42 % / 3.0 GB | `conc-BB2-20261018-065116` |
| 3 | 3× B in space | 3× PASS | 192.2, 197.7, 195.4 | 49 % / 3.9 GB | `conc-BBB3-20261018-065148` |
| 4 | 4× B in space | 4× PASS | 198.4, 196.4, 199.4, 198.0 | 39 % / 4.3 GB | `conc-BBBB4-20261018-065222` |
| 2 | 2× B in space, **wined3d-sw** | PASS, PASS | 41.4, 41.3 (68.7 alone, D105) | CPU load avg 11.6 | `conc-BB2sw-20261018-065335` |
| 2 | B space + A menu, **window fix (N13)** | PASS, PASS | - | - | `conc-AB2fix-20261018-070225` |
| 2 | 2× B in space, window fix | PASS, PASS | - | - | `conc-BB2probe-20261018-070315` |
| 4 | 4× B in space, window fix | 4× PASS, 4 distinct wids, each at its slot (`ok=1`) | 196.7, 199.0, 198.8, 193.5 | - | `conc-BBBB4fix-20261018-0704*`, `conc-BBBB4fix-montage.png` |

- `GPU Recovery Action: None` after every run (VERIFIED, `gpu.txt` tails), and every game-side check passed (each
  lane has its own devbridge dir, so load/state/perf/quit were per lane).
- **But the window identification was wrong in these runs** (found afterwards, N13): in `conc-BB2` both runners
  recorded window `92274689`, in `conc-BBB3` all three recorded `88080385`, in `conc-BBBB4` lanes 1-3 recorded
  `85983233`. They moved and screenshotted one shared window. Fixed in the runner (per-window pid check, periodic
  re-validation, slot check). Re-runs with the fix: `conc-AB2fix-20261018-070225` (B lane 1 wid 111149057 at 0,0;
  A lane 2 vdesk 73400327 at 1280,49; both `ok=1`, both PASS) and `conc-BB2probe-*` (below).
- The game's own frame rate sits at ~198 fps with `DXVK_FRAME_RATE=60` set; the devbridge counts calls of the
  frame function, so either the DXVK limiter does not apply through HDE's dxwrapper → ReShade → DXVK chain or the
  frame function runs more often than presents (UNVERIFIED which).
- **Decision:** `LANES=4` (the 2×2 slot grid; measured safe on DXVK), `LANES_SW=2` when the renderer resolves to
  `wined3d-sw` (CPU-bound: 2 instances already drop to 41 fps). `lane.sh acquire` without `--lane` uses the
  renderer-aware count. More than 4 lanes would overlap window slots; not measured.

## N12. Reference sources behind the fixture encodings (D106: citations live here, not in code)

- `harness/fixtures/flhash.py` (`create_id`, `make_id`, `make_location_id`) and the encoding helpers in
  `gen_fixture.py` (`wide_to_hex`/`hex_to_wide`, `tstamp`, `cargo` field order, `[Player]` key order, Restart.fl =
  `newplayer.fl` + `initialworld.ini`) were cross-read against the Freelancer-Decomp sources in
  `$FLMOD_REFS` (Common `CFLIDMaker::CreateStaticID` lower-cases ASCII before hashing; `MakeId` is a CRC-16/CCITT
  table applied LSB-first from 0xFFFF; `MakeLocationID` formats the base id with `%X`; server `create_restart_file`,
  `PlayerData_LoginAccount`, `PlayerData_SaveGame`, the `[Player]` writer), plus R3 §10 (Librelancer FLHash,
  FLHookSDK CommonMethods). No code was copied; the implementations are ours and are tested by
  `harness/tests/test_gen_fixture.py`.

## N13. Concurrent runners shared one window id: `xdotool search --pid P --name N` is an OR

**Observations (VERIFIED):** see N11: in the first concurrency runs, 2-3 runners recorded the same window id. In
`…-065703-lane1-spewbase-B-dxvk-2` the B runner tracked `75497473`, a window at (1280,49), the A vdesk slot of lane
2, and the gate then refused the console input with `target_not_game_window` (the gate's own per-window pid check
worked). In `…-065718-…-3` the B runner's "hang" screenshot of `75497473` shows Track A's FLUF menu.

**Hypotheses**

1. `xdotool search --pid P --name N` combines the criteria with OR (`--any` is the default), so every lane's
   `Freelancer` window matches.
2. Wine sets the same `_NET_WM_PID` on windows of different processes (e.g. explorer.exe's or wineserver's pid).
3. X window ids are reused across lanes (client resource-id bases recycled between short-lived connections).
4. FL creates a short-lived early window, and the runner caught another process's window during that gap.
5. `--onlyvisible` races with mapping: the search returned a window that was being unmapped.
6. The window manager reparents windows; `_NET_WM_PID` sits on the frame, not the client.
7. `windowmove` of one lane's window triggered a re-stack that made another lane's window match.
8. The vdesk child window (A's game window inside `lane2 - Wine Desktop`) carries the B pid through Wine's
   desktop process.
9. xdotool's `getwindowpid` falls back to the parent's pid for child windows.
10. The runner's per-tick `find_window` ran before `self.gpid` was set and searched with a stale pid.

**Experiment:** two B lanes up at once (`conc-BB2probe-*`), then `xdotool search` variants
(`p0-harness-evidence/xdotool_search_pid_probe.txt`): `--pid 1 --name ^Freelancer$` returns **both** windows;
`--pid <A> --name ^Freelancer$` returns both; `--all --pid <A> --name …` and `--pid <A>` alone return only A's
window; `getwindowpid` gives the right, distinct pid per window. H1 confirmed; H2/H9 ruled out by the distinct
`getwindowpid` values. The two windows also both sat at (0,0) right after creation, so before the fix a wrong pick
was invisible in the screenshots whenever the lanes overlapped.

**Fix:** never use `--pid` together with `--name`; the runner (`Run.pid_windows`), `xinput.py` and `baseline.sh`
list candidates by title and check `getwindowpid` per window. The runner re-validates its window every 2 s
(still viewable and still the lane's), records `window_changes`, prefers the largest candidate (FL may show an
early window), and records whether the window reached its slot (`window_placed.ok`).

## N14. Hang dump crashed the game; one B start hung before the menu

- `…-065718-lane1-spewbase-B-dxvk-3`: FLSpew stopped at `found d3d device` (01:57:20) and the devbridge emitted
  nothing after `ev=selftest_hooked`: the main thread was stuck before the menu. 60 s later the runner detected the
  HANG, ran `winedbg --command "info proc"` and `winedbg --minidump`; right then a **new** thread (01d0) faulted at
  `0xFFF40E50` (EIP = the fault address: a thread started at a bad address, consistent with a remote break-in
  thread under WoW64), no minidump was written, and the verdict said CRASH.
- Treatment: the runner records `hang.wine_log_lines` at detection; `verdict.py` reports crash texts after that
  line as info ("attributed to the hang dump/kill"), so such a run is a HANG. Whether `winedbg --minidump` can dump
  a WoW64 Freelancer.exe at all is UNVERIFIED (no successful dump seen yet).
- Pre-menu hang hypotheses (one occurrence, not reproduced yet): (1) two DXVK devices created at the same moment
  (lane 2's A run started ~15 s earlier); (2) NVIDIA shader-cache lock contention between processes; (3) the old
  runner's `windowmove`/`windowsize` of a wrong window (N13) disturbing the other lane's swapchain creation; (4) an
  X request blocked by another client's grab (no `x_stalls` recorded, so unlikely); (5) audio device contention;
  (6) dxwrapper/ReShade first-start cache writes; (7) a Wine/DXVK race at swapchain creation independent of other
  lanes; (8) the selftest DLL's hook racing start-up (it hooked fine); (9) the input lock holder's earlier
  activation of a now-dead window; (10) memory pressure (no evidence). Watch for recurrence: every concurrency run
  since the N13 fix records it.

## N16. REQ-8 evaluation: 5 two-lane runs with the fixed identification

| Run | Lanes | Distinct window ids | Each at its slot | Game verdicts |
|---|---|---|---|---|
| `conc-AB2fix-20261018-070225` | B x11 + A vdesk | yes (111149057 / 73400327) | yes / yes | PASS, PASS |
| `conc-BB2probe-20261018-070315` | B + B | yes (106954753 / 104857601) | yes / yes | PASS, PASS |
| `conc-winid1-*` | B + B | yes | yes / yes | PASS, HANG (pre-menu stall, N14) |
| `conc-winid2-*` | B + B | yes | yes / yes | HANG, HANG (pre-menu stall, N14) |
| `conc-winid3-*` | B + B | yes | yes / yes | PASS, CRASH (after load, exit code 3) |

(`p0-harness-evidence/window_id_2lane_runs.txt`.) Identification worked 5/5 with method 1 (`_NET_WM_PID`, checked
per window) for x11 lanes and method 2 (per-lane Wine virtual desktop) for A, which needs it anyway (N2). Method 3
(serialized start-up) is not needed. The winid runs overlapped with two `wined3d-sw` (llvmpipe) instances, an A
vdesk input test and the B allow-list loop (load average 15-18 on 24 threads); their game failures are N14 material,
not identification failures.

### N14 (cont.). Failures under heavy mixed load (07:10-07:14Z)

While two `wined3d-sw` (llvmpipe) instances, the B allow-list loop and an A vdesk test ran (load average 15-18 on
24 threads), the extra 2-lane runs (N16) showed three more pre-menu stalls (`conc-winid1-B3`, `conc-winid2-B3`,
`conc-winid2-B4`: FLSpew stops right after the second `found d3d device`; wine.log shows `d3dcompiler_47.dll` being
loaded (ReShade compiling its effects) and nothing after) and one crash after the load
(`conc-winid3-B4`: `err:msvcrt:_wassert "!status && vkCreateGraphicsPipelines"` in winevulkan, then the access
violation at `dacom.dll+0x3de4`). `GPU Recovery Action: None` and no new NVRM/Xid lines in `/var/log/kern.log` since
the 01:27 module load (VERIFIED). On a quiet host 4 B lanes at once passed twice (N11).

- (Superseded in fix round 1, N18: the CPU heuristic is gone. Progress is now log growth: FLSpew, the devbridge
  log, and during start-up also wine.log; a start-up wait that never reaches the menu ends as TIMEOUT with a
  backtrace/minidump attempt; `cpu_ticks` stays in `liveness.tsv` as a diagnostic only.)
- Mixing is now enforced: renderer classes never run at once (`render.gate` + `render-<class>.lock`, N18). With
  the 60 fps cap (N17), 4 mixed DXVK lanes passed 12/12 (N11 re-measure).

## N15. Post-campaign fixture checks (REQ-16): what is and is not verified

| Check | Result | Evidence |
|---|---|---|
| `HARNESS_endgame_eagle` loads on B, docked at `Li01_01_Base`, 60,000,000 cr | VERIFIED (devbridge `state`: docked, base_id = CreateID(Li01_01_Base), cash) | session 1 + selftest `b_eagle` |
| `HARNESS_endgame_eagle_space` in space in Li01, Eagle with Nomad guns, 63 bots / 63 batteries | VERIFIED (state + HUD screenshot) | `…-064916-lane1-space-perf-B-1/shots/final.png` |
| No story script starts after loading in space | VERIFIED by contrast: the story control (`HARNESS_selftest_gate_story`, Mission_01a) drops straight into a letterboxed cutscene; the post-campaign fixture at the same spot shows the normal HUD | `…-072951-lane1-obj-HARNESS_selftest_gate_story/shots/objective.png` vs `…-072156-lane1-gate-post-B-2/shots/objective.png` |
| No story objective active | **UNCLEAR**: `N` (USER_DISPLAY_LAST_OBJECTIVE) on the post-campaign fixture shows "DOCK WITH PLANET TOLEDO", an M12 objective text (`m12.ini dock_with_toledo`). It is the *last* objective display; whether it is active is UNVERIFIED | `…-072156-lane1-gate-post-B-2/shots/objective.png` |
| Bar without story offer | NOT RUN: needs base-room navigation by mouse (N5) | - |
| Story-locked gate `Li01_to_Li02` passable | **NOT VERIFIED**: the post fixture has no player `locked_gate` line and the story control has `locked_gate = 2830511361`, but the in-game check needs the gate targeted. `T` selected nothing (the contact list is empty under its default filter: `…-071622-lane1-gate-post-B-1/shots/target.png`), and a click on the gate in space was refused by the input gate because the X pointer ended outside the window after the cursor moves (`…-072156-…-gate-post-B-2`, `pointer_outside_game_window x=1981 y=1092`) | runs named |

Next (W1-HARNESS / W1-SPAWN / W1-CORE): `selftest.sh --with-gate` already sends the devbridge verb
`target Li01_to_Li02` (CONVENTIONS §4, W1-SPAWN), then F3 (dock) through the input gate, then waits for `state`
`system_id` = CreateID(Li02) = 2745692751 (post fixture) or stays in Li01 (story control). With the Phase-0
selftest DLL `target` is an unknown verb, so the step is BLOCKED by default; once the verb exists it runs as written
(fix round 1: the step used `@key t` before, which can never work, see the T row above). If "Dock with Planet Toledo" proves to be a live objective, try MissionNum 41 with
`[MissionState]` omitted, then the `m13_opensp_normal.ini` trigger effects (REQ-16 fallbacks); the
`force_postcampaign` verb remains the documented degrade path.

## N17. Why DXVK_FRAME_RATE=60 did not cap the game, and the cap that works (fix round 1, review r1 m10)

Observation: every lane ran at ~198 fps (devbridge `perf`) although the runner exported `DXVK_FRAME_RATE=60`.

**Hypotheses**

1. The DXVK in Proton 11 no longer reads `DXVK_FRAME_RATE` (renamed or replaced by a config key).
2. The env var never reaches Freelancer.exe (wine/explorer drops it).
3. HDE's chain bypasses DXVK: dxwrapper/dgVoodoo or wined3d presents instead.
4. DXVK's d3d8 front-end is the presenter and the limiter applies only to d3d9/dxgi.
5. ReShade (EXE/d3d9.dll) presents through its own path and skips DXVK's limiter.
6. `DXVK_CONFIG="d3d9.presentInterval = 0"` disables the limiter together with vsync.
7. The devbridge counts frame-function calls, not presents: FL may run several sim frames per present.
8. A `dxvk.conf` in EXE overrides the environment.
9. dxwrapper's own `LimitPerFrameFPS = 0` or frame-skip setting interferes.
10. The limiter works but is per swapchain, and FL recreates swapchains (menu → space).

**Experiments** (lane runs `fcap-*`, B in space, `perf 10`, DXVK HUD):

- `RUN_DXVK_LOG_LEVEL=info RUN_DXVK_HUD=fps,version,api` (`…-082901-lane1-fcap-V0-info-hud`): the HUD shows
  **DXVK v3.1.1, D3D9, FPS 200.2** (screenshot `shots/hud.png`): DXVK d3d9 is the presenter (H3, H4, H5 out) and
  presents run at the frame-function rate (H7 out). DXVK logs `Found config env` for DXVK_CONFIG but nothing about
  a frame rate. No `dxvk.conf` in EXE (H8 out).
- `strings syswow64/d3d9.dll` (the prefix's DXVK): contains `DXVK_HUD`, `DXVK_CONFIG`, `DXVK_CONFIG_FILE`,
  `d3d9.maxFrameRate`, `dxgi.maxFrameRate`, `dxvk.maxFrameRate`, and **no `DXVK_FRAME_RATE`**: H1 VERIFIED.
- `RUN_DXVK_CONFIG="d3d9.presentInterval = 0; d3d9.maxFrameRate = 60"` (`…-082940-lane1-fcap-V1-maxFrameRate`):
  `fps_avg=60.0 fps_p1=59.7 frame_ms_max=18.87`; DXVK warns `Built-in frame rate limiter enabled` (in wine.log only).
  H6 out (presentInterval 0 and the limiter coexist).

**Decision:** the default lane `DXVK_CONFIG` is now `d3d9.presentInterval = 0; d3d9.maxFrameRate = 60`; the dead
`DXVK_FRAME_RATE` export is gone. `RUN_DXVK_CONFIG`, `RUN_DXVK_HUD` and `RUN_DXVK_LOG_LEVEL` can be overridden from
the environment for perf experiments (S-PERF uncapped runs: `RUN_DXVK_CONFIG="d3d9.presentInterval = 0"`).

### LANES re-measured with the cap under a mixed load (N11 continued)

`p0-harness-evidence/mixload-cap60-20261018-083102/summary.txt`: 3 rounds × 4 lanes at once, each round = B in
space, B docked (new_story), B docked (endgame_eagle), A at the FLUF menu; B lanes run `perf 30`.

| Round | Verdicts | B fps_avg / fps_p1 / frame_ms_max | GPU max util | Load avg max |
|---|---|---|---|---|
| 1 | 4× PASS, B clean quits | 60.0/59.8/21.3, 60.0/59.6/16.9, 60.0/59.6/17.4 | 46 % | 3.8 |
| 2 | 4× PASS | 59.9/59.8/88.6, 60.0/59.6/18.1, 60.0/59.6/17.1 | 48 % | 4.1 |
| 3 | 4× PASS | 60.0/59.5/21.8, 60.0/59.0/17.3, 60.0/59.6/17.1 | 38 % | 4.2 |

12/12 PASS, `GPU Recovery Action: None` after every round, frame pacing flat (p1 ≥ 59.0; one 88 ms spike in
round 2, lane 1). Uncapped, the same hardware ran 4 lanes at ~198 fps each (N11). `LANES=4` stays, now on measured
mixed-load evidence; mixing with `wined3d-sw` is impossible by construction (N18). The GPU utilisation numbers
include 10-15 % from other users of the GPU that were already present.

## N18. Fix round 1 (review r1): what changed and why

- **Quit outcome decides (M1).** Clean quits end with a *handled* access violation near the end of wine.log
  (76 of 77 PASS runs of this session have a system exception within 300 lines of the end, 12 lines for every B
  run; in `…-073306-lane1-selftest-b_eagle` it is at dacom.dll+0x3de4), exit code 0 — so a trailing exception
  after quit is not a crash signal by itself. The game's own exit
  code is: nonzero after quit or a window close → CRASH (x11 lanes only: on vdesk the launcher is explorer.exe,
  `exit_code_is_game=false`; never when the harness killed the game, `killed_by_harness`). A `quit` that does not
  end the process within 30 s → HANG `quit_no_exit`. The post-quit wait keeps ticking (dw15.exe, crash windows),
  and `dw15.exe` loads in wine.log count as CRASH.
- **Heartbeat.** The selftest DLL emits `ev=hb` every 10 s; once seen, a silent devbridge log for 60 s is a HANG
  even with nothing pending (frozen game during `--hold-s` / `@sleep`). Track A (no devbridge) cannot be checked
  this way while idle (UNVERIFIED alternative: none yet).
- **Fail closed.** No allow-list for the track+renderer → strict check against the built-in patterns only. A
  run.json without `ready/window_id/cmds/end_ms`, or with `ready=false`, is FAIL; `lane_lost` is FAIL.
- **Reap race (M2).** `.acq-<pid>-<wait_s>-<rand>.status` files are removed only when the acquirer is dead or the
  file is older than wait_s + 60; a lane is cleaned only while reap itself holds `lane-N.lock` (`flock -n`).
  The reviewer's `reaprace.sh` (now `tests/reaprace.sh`) gives 0 leaks of 8 (before: 8 of 8).
- **Renderer classes** never mix: `lock_holder.sh` takes `render-<gpu|sw>.lock` shared after checking, under
  `render.gate`, that nobody holds the other class.
- **Baseline lock.** `baseline.sh create|fluf-init` hold `baseline-<T>.lock` exclusively; `lane.sh` (clone) and
  `deploy.sh` (rsync refresh) hold it shared.
- **Holder identity.** `holder_is_ours` checks comm `sleep`, cmdline `sleep <ttl>` and the start time recorded at
  acquire (`holder_start`); the runner aborts with `lane_lost` when the holder disappears (lease expiry).
- **Input gate.** X-Resource (`XResQueryClientIds`, python-xlib) must confirm the window's creator pid; a forged
  `_NET_WM_PID` is refused (`tests/test_input_gate.sh`). The input lock is verified from the holder's open fd plus
  `/proc/locks` (the pid there is flock(1)'s short-lived child, so the pid alone is useless — VERIFIED, lane-6 debug
  run: the locks entry named a dead pid while the holder `sleep` had the fd open).
- **Dumps.** `capture_dump` writes `backtrace_<tag>.txt` from `winedbg --command "bt all"` first, then tries the
  minidump, and records why anything failed. Live test `…-083528-lane1-dumptest-manual` (`--dump-before-quit`):
  the backtrace covers all 74 threads including Freelancer.exe's main thread (in alchemy.dll); the minidump failed
  (`winedbg rc=255`) and the game died with the same `0xFFF40E50` fault as in N14 → attaching winedbg to the WoW64
  game kills it (VERIFIED twice now); the backtrace comes first for that reason.
- **Shots.** A root-crop is taken only if no window is stacked above the game's area, and is exit code 2:
  evidence, never proof of rendering (selftest requires rc 0).
- **Lane loss (m9), live test** `…-085643-lane1-lanelost-ttl45`: lane acquired with `--ttl 45`, run held for 120 s;
  the lease expired, the runner logged `LANE LOST` within 5 s, killed only its own game process (pid + start time; no
  `wineserver -k`, the prefix may already be someone else's), verdict FAIL `lane_lost`, 50 s instead of 120 s.
- **Non-wine bystanders (m2):** `tests/test_lanes.sh` starts a plain `sleep` with `WINEPREFIX=<lane 8>`; it survives
  the prefix recreate (only processes whose exe is a Wine binary, a `*.exe` or wineserver are killed).
- **Lane window not at its slot** is now a FAIL signature (`window_not_at_slot`), see N19.

## N19. The Track A virtual desktop sometimes comes up fullscreen

Selftest `concurrent` failed once (`…-084729-lane1-selftest-conc-a`): the `lane1 - Wine Desktop` window stayed
3744x2106 at (0,0) for the whole run (5 placement tries), covering the screen; the game inside it was 1280x720 and
the run otherwise PASSed. Reproduction loop (4× `selftest.sh --only a_boot,concurrent`): 2 of 4 concurrent runs
(`…-085329-…`, `…-085427-…`) showed the same, and the new diagnostic recorded the window manager state:
`_NET_WM_STATE_FULLSCREEN, _NET_WM_STATE_FOCUSED` (VERIFIED). The a_boot runs (A alone) never did (4/4 normal), and a
probe with B starting next to it did not reproduce it either (`vdesk-withb`, 39 samples at 1280x720).

Hypotheses (why FULLSCREEN): (1) Wine's explorer marks the virtual desktop fullscreen when the game requests a
display mode change at start-up and the desktop is resized to "match" it; (2) xfwm4 applies fullscreen to a new
window whose requested size equals a monitor's when the size hints race; (3) DXVK's swapchain inside the desktop
asks for exclusive fullscreen during device creation; (4) the A window from the previous run (same title, same X id
reused) left xfwm4 state; (5) FLUF sizes the game to the desktop and the desktop to the screen in a race with
explorer's own size; (6) focus: the window that gets focus during creation gets fullscreen from the WM's
"fullscreen on focus" heuristics for borderless windows; (7) a Wine X11 driver race between the desktop window's
`_NET_WM_STATE` and its first configure; (8) the second game starting (B) triggers an XRandR/monitor re-query in
explorer; (9) a timing-only race unrelated to B; (10) xfwm4's "smart placement" for a window larger than the free area.
Not separated yet. **Fix in place (VERIFIED 2/2):** when placement fails, the runner records `_NET_WM_STATE`,
removes MAXIMIZED/FULLSCREEN with `xdotool windowstate --remove`, and re-places; both reproduced cases reached the
slot on the second try. If it ever stays fullscreen, the verdict is FAIL `window_not_at_slot`.
