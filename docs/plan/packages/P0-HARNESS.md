# P0-HARNESS: Dev baselines, lanes, run/deploy, fixtures, devbridge core, crash triage, display keep-awake

- **Type:** impl
- **Wave:** Phase 0
- **Depends on:** — → **Unblocks:** P0-TRACK-A, P0-TRACK-B, all spikes, every in-game test.

## Goal

The build tests itself, in the real game, unattended. This package delivers four things:

1. Two pristine dev baselines (Track A: HDE + FLUF; Track B: HDE untouched), cloned from Adam's play install without modifying it.
2. A lane system that gives each test an exclusive, disposable prefix and a window slot, and can run several game instances at once.
3. Scripts that deploy a build, launch the game into a known save, drive it through a file-based devbridge, capture logs and screenshots, detect crashes and hangs, and tear down cleanly.
4. A display keep-awake helper, a fixture-save generator, and a crash-triage tool.

## Requirements

### A. Safety rails (do these first)

- **REQ-P0-HARNESS-1: Wine guards (verify only).** `tools/env.sh` and the `tools/bin/` guards **exist and are orchestrator-owned** (CONVENTIONS §14–§15; VERIFIED 2026-10-17).
  - **What they do:**
    - `env.sh` exports the `FLMOD_*` paths, prepends `tools/bin`, and sets the sentinel `WINEPREFIX=/home/user/freelancer/prefix-UNSET`.
    - `tools/bin/_wineguard` resolves `WINEPREFIX` with `realpath -m` and allows only `prefix-dev*`, `prefix-lane*` and `prefix-carrier*`.
    - Allowed calls `exec` the wine-proton 11.0.1 binary; anything else exits 97.
  - **Don't modify them.** Add a regression test `harness/tests/test_guards.sh`. It asserts exit 97 for:
    - unset, the sentinel, `/home/user/freelancer/prefix`, `/home/user/.wine`, `/home/user/freelancer/prefix-lane-1/../prefix`;
    - a non-existent `prefix-lane-99`;

    and success for an existing lane prefix. If you find a gap, report it with a proposed patch.
  - **Every harness script** starts with `source /home/user/freelancer/carrier-mod/tools/env.sh` and calls `wine`, `wineserver` and `winedbg` **only through the guards**. Never use `/usr/lib/wine-proton-11.0.1/bin/*` or `/etc/eselect/wine/bin/*` directly.
  - Why: R4 Incidents. On 2026-10-17 `winedbg --help` without a prefix wineboot-updated `~/.wine`, Adam's Battle.net prefix.
- **REQ-P0-HARNESS-2:** Never touch `/home/user/freelancer/prefix`, `play.sh` or `~/.wine` (CLAUDE.md guardrail 1).
  - Clone the play prefix **only** when it's idle: `tools/play_prefix_busy.sh` exits 1. That orchestrator-owned script checks both `WINEPREFIX` in `/proc/*/environ` and processes whose cwd is inside the prefix, because `play.sh` runs `cd EXE; exec wine-proton Freelancer.exe`. If it's busy, wait (poll every 60 s) and never kill anything.
  - Never send kill signals to processes outside your lane prefixes.

### B. Dev baselines (BUILD_PLAN §3)

- **REQ-P0-HARNESS-3:** Script `harness/baseline.sh create A|B` creates `/home/user/freelancer/prefix-dev-base-A` or `-B`.
  - Clone with `cp -a --reflink=always /home/user/freelancer/prefix <dest>`. XFS reflink is VERIFIED (R4 §B10). The prefix has no absolute self-paths in `*.reg` (VERIFIED, R4 §B10).
  - Then apply the tweaks below, idempotently, with **byte verification before every binary patch**.
  - Write `<dest>/BASELINE.json`: track, date, every tweak applied, sha256 of every modified file.
  - `baseline.sh verify A|B` re-checks all of it.
  - HDE dir in any prefix: `<prefix>/drive_c/Games/Freelancer HD Edition` (call it `$HDE`).
- **REQ-P0-HARNESS-4: Common tweaks (A and B).**
  1. `$HDE/EXE/flplusplus.ini`: `save_in_directory = true`, `screenshots_in_directory = true`. Saves then live in `$HDE/SAVE/Accts/SinglePlayer/` and screenshots in `$HDE/SCREENSHOTS/` (R4 §B6, §B10 VERIFIED keys; exact resulting paths UNVERIFIED, so confirm after the first run).
  2. `$HDE/SAVE/PerfOptions.ini`: `[Display] size= 1280, 720`. The file exists in HDE's `SAVE/` (VERIFIED listing). Keep the other keys.
  3. Keep-running-when-unfocused: `$HDE/EXE/Freelancer.exe` at **file offset 0x1B264C**.
     - Verify the 6 bytes are `83 ff 01 0f 94 c2`, then write `BA 01 00 00 00 90` (R4 §B6 table, VERIFIED from installer source and installed bytes).
     - If the bytes differ, don't patch; log `TWEAK_SKIPPED keep_running bytes=<hex>`.
     - Track A: first grep `/home/user/freelancer/refs/FLUF/FLUF/Source` for `0x5B264C` / `0x1B264C` / "focus". If FLUF already patches this, skip ours on A and record why.
  4. `$HDE/EXE/devbridge.enabled`: an empty marker file. The devbridge is inert without it. Never place it in `prefix-carrier`.
  5. Record the baseline FLSpew allow-list (REQ-14).
- **REQ-P0-HARNESS-5: Track A tweaks** (FLUF install per R1 §6, VERIFIED file list from the release `listing.txt`).
  1. Extract `/home/user/freelancer/refs/FLUF-release-nightly-2026-10-16/FLUF.tar.xz`, or reuse `$FLMOD_VENDOR/FLUF` from P0-TOOLCHAIN (read-only).
  2. Copy `EXE/fluf/*` (FLUF.dll, FLUF_boot.dll, dacom_fix.dll, freetype.dll, libcurl.dll, curl-ca-bundle.crt, adjectives.json, nouns.json, backgroundpattern.png, `migrations/`, `modules/`) to `$HDE/EXE/fluf/`. Copy the release `DATA/*` (FONTS, INTERFACE/FLIGHT_MANUAL, SCRIPTS/FLUF) into `$HDE/DATA/`.
  3. Edit `$HDE/EXE/dacom.ini` with idempotent marker blocks; keep the original as `dacom.ini.hde-orig`:
     - `[DACOM]`: add `dll_search_path = .\fluf` and `dll_search_path = .\fluf\modules`.
     - `[Libraries]`: first entry `fluf/dacom_fix.dll`. The docs example shows a bare `dacom_fix.dll`; a subpath in `[Libraries]` is UNVERIFIED. Test it; if the subpath fails, copy `dacom_fix.dll` to `EXE/` and list it bare.
     - Insert `fluf/FLUF.dll` directly after `flmaterials.dll`, which places it before `HudShift.dll` (required: "HudShift must load AFTER FLUF", R1 §3.4).
     - Comment out (`;`) `jflp.dll`, `DelayDisplay.dll`, `MP3codec.dll`, `storyfactions.dll`, `FLSharp.dll`. These are on FLUF's forbidden list (`/home/user/freelancer/refs/FLUF/FLUF/Source/Fluf.cpp:55-57`, VERIFIED).
  4. `$HDE/EXE/freelancer.ini [Initial SP DLLs]`: comment out the `callsign.dll, player 1 1-1` line (forbidden).
     - **Do not** just delete `DLLS/BIN/callsign.dll`. A missing `[Initial SP DLLs]` DLL crashes vanilla; FLSharp's `freelancer_dll_crash_fix` normally prevents that, and FLSharp is removed here (R5 §2, VERIFIED).
  5. First launch writes `$HDE/EXE/fluf/FLUF.yml`. Then set:
     - `logLevel: Debug`
     - `logSinks: [File]` (no `Console`: `AllocConsole` opens a window under Wine)
     - `writeSpewToLogSinks: true`
     - `clientConfig.modules: [debugger.dll, delay_display.dll, story_factions.dll, story_enhancements.dll, FLUF.CrashWalker.dll]`. **Single player reads only `clientConfig.modules`** (R1 §1.2 item 7, VERIFIED `Fluf.cpp:650-664`; the docs are wrong).
     - Do **not** enable FLUF's `setSaveDirectoryRelativeToExecutable`. flplusplus already detours `GetUserDataPath`, and a double detour is a risk (R5 §3.1).
  6. **Address space.** FLUF.dll's SizeOfImage is 404 MiB because of DWARF, and HDE's Freelancer.exe is not large-address-aware (R1 §8.3, VERIFIED).
     - If baseline A fails to reach the main menu or crashes loading a busy system, try in this order:
       1. Set `IMAGE_FILE_LARGE_ADDRESS_AWARE` (0x0020) in `Freelancer.exe`'s COFF Characteristics. Byte-verify the PE header offset; record old and new values.
       2. Use a debug-stripped copy (`/usr/lib/llvm/22/bin/llvm-strip --strip-debug`) of FLUF.dll and the modules.
       3. Use the stable 2.0 release (`/home/user/freelancer/refs/FLUF-release-stable-2026-03-28/FLUF.tar.xz`).
     - Record which worked. P0-TRACK-A measures headroom properly.
  7. The FLUF log goes to `GetUserDataPath()\fluf.log` (R1 §1.4; exact path UNVERIFIED). With flplusplus `save_in_directory` it is probably `$HDE/SAVE/fluf.log`. Find it after the first run and record it.
- **REQ-P0-HARNESS-6: Track B tweaks.** HDE stays untouched apart from the common tweaks, plus `$HDE/EXE/jflp.dll` at **file offset 0x1528**: if the byte is `33`, write `04`. This disables JFLP's Alt+Enter toggle, which is required together with the 0x1B264C patch to avoid focus ping-pong (R4 §B6 table, VERIFIED).

### C. Lanes

- **REQ-P0-HARNESS-7:** `harness/lane.sh`.
  - `acquire [--track A|B] [--input] [--perf] [--lane N]` takes an exclusive `flock` on **`$FLMOD_LOCKS/lane-<N>.lock` (absolute: `/home/user/freelancer/carrier-mod/local/locks/`)**. All worktrees must see the same locks (CONVENTIONS §1, §7).
    - Run it as a long-lived lock holder: a backgrounded `flock` on a fd held by a sleeper PID, started with `setsid -f` so it survives the calling tool invocation.
    - Record the holder in `$FLMOD_LOCKS/lane-<N>.owner` with the agent or package id, timestamp and PID.
  - It then recreates `/home/user/freelancer/prefix-lane-<N>` from `prefix-dev-base-<track>`: `wineserver -k` + `-w` for that lane, `rm -rf`, then `cp -a --reflink=always`.
  - It prints `export` lines (`LANE`, `WINEPREFIX`, `HDE`, `FL_SAVEDIR`, `FL_DEVBRIDGE_DIR`, `LANE_X`, `LANE_Y`, **`FLCOPILOT_PORT=$((29170+N))`**, the per-lane sidecar port from CONVENTIONS §7) and a release token.
  - `--input` also takes `$FLMOD_LOCKS/input.lock`. Only the holder may focus windows or send synthetic input. Synthetic input means XTEST: `xdotool windowactivate --sync <wid>`, then `xdotool key …` to the focused window. **Never `xdotool key --window`** (XSendEvent is invisible to `GetAsyncKeyState`).
  - `--perf` takes `$FLMOD_LOCKS/perf.lock` **exclusively**. It waits until no other lane is held, and while held, `acquire` without `--perf` blocks. Use it for FPS and scale measurements (S-PERF, metrics).
  - `release <token>` kills that lane's wineserver (`WINEPREFIX=<lane> wineserver -k; wineserver -w`) and releases the locks.
  - `status` lists lanes and owners. `reap` frees locks whose owner PID is dead.
  - Lane count comes from `harness/config.sh` `LANES` (TESTING §Lanes default **3**; you measure 1–4 instances and set it). Window slots are on a 2×2 grid of 1280×720 at (0,0), (1280,0), (0,720), (1280,720). The screen is 3744×2106, VERIFIED R4 §0.5.
- **REQ-P0-HARNESS-8: identify each lane's window.** All instances are titled `Freelancer` (VERIFIED R4 §B6), so the title alone won't do. Implement and evaluate, in order:
  1. `xdotool search --pid <wine unix pid>`. Whether Wine sets `_NET_WM_PID` is UNVERIFIED.
  2. A Wine virtual desktop per lane: `wine explorer /desktop=lane<N>,1280x720 Freelancer.exe`. This gives a unique title `lane<N> - Wine desktop`; DXVK under a virtual desktop is UNVERIFIED.
  3. Serialized startup under the input lock: record the new window id that appears after launch.

  Choose the first that works reliably over 5 runs with 2 lanes at once, and record it.
- **REQ-P0-HARNESS-9: headless evaluation.**
  - Try `gamescope --backend headless -w 1280 -h 720 -- env WINEPREFIX=<lane> /home/user/freelancer/carrier-mod/tools/bin/wine Freelancer.exe` (gamescope is installed, with a headless backend: VERIFIED R4 §B6).
  - Pass condition: the game reaches the main menu (devbridge `state` → `state=menu`) and loads a save.
  - A screenshot must also be obtainable. Use devbridge `shot` (REQ-12), which posts VK_SNAPSHOT so flplusplus writes a PNG to `$HDE/SCREENSHOTS/`. flplusplus's `alternative_fullscreen_screenshots_code` defaults true on Wine (R4 §B6).
  - Record USABLE / NOT USABLE. If usable, `lane.sh acquire --headless` runs that lane in gamescope. Input-requiring tests always use `:0`.
  - Don't spend more than about 2 hours on this; it's optional (Xvfb is not expected to work with DXVK on NVIDIA).

### D. Deploy and run

- **REQ-P0-HARNESS-10:** `harness/deploy.sh --lane N --artifacts <dir> [--dacom-lib <name.dll> ...] [--overlay <dir>]`.
  - Copies DLLs into `$HDE/EXE/` (or `$HDE/EXE/fluf/modules/` for Track A modules: `--fluf-module <dll>` also adds it to `FLUF.yml clientConfig.modules`).
  - Appends dacom `[Libraries]` lines inside a `; >>> carrier-mod` … `; <<< carrier-mod` marker block at the end of `[Libraries]`.
  - Rsyncs an overlay dir onto `$HDE/` (new files only; never overwrites an HDE file unless the overlay manifest lists it as a patch).
  - Runs the data pipeline if present: `$FLMOD_VENV/bin/python -I gen/run.py deploy --install "$HDE"`, the P0-DATATOOLS entry point that W1-DATA's plugins extend. If it's absent, skip with a log line.
  - Writes `$HDE/DEPLOY_MANIFEST.json` (git SHA, file sha256s).
- **REQ-P0-HARNESS-11:** `harness/run.sh --lane N [--save <pattern>] [--timeout S] [--cmds <file>] [--name <run-name>] [--expect <regex> ...]`.
  1. `source tools/env.sh`. Export `WINEDEBUG=fixme-all,+seh,+loaddll`, `DXVK_LOG_LEVEL=warn`, `DXVK_FRAME_RATE=60`, `DXVK_CONFIG="d3d9.presentInterval = 0"` (R4 §B6, §B7). Set `cd "$HDE/EXE"`.
  2. Launch in the background, logging to `<run>/wine.log`:
     - Track A with `--save`: `wine Freelancer.exe --save-file=<pattern>`. The FLUF debugger module matches the save description, then the mission IDS, then the filename (VERIFIED `refs/FLUF/modules/debugger/Source/Debugger.cpp:94-240`). Whether FL's own `+/-` switch parser tolerates `--save-file` is UNVERIFIED: test it.
     - Track B: after the main menu, write devbridge `load <file>` (implemented by P0-TRACK-B). Until that exists, fall back to xdotool menu clicks under the input lock: measure coordinates at 1280×720 once and store them in `harness/config/menu_coords.json`.
  3. Find the window (REQ-8) and move it to the lane slot.
  4. Wait for the devbridge `HARNESS state=` line, or the FLSpew line `Starting single player game` (VERIFIED in the play FLSpew), with a timeout.
  5. Feed `--cmds` (one devbridge command per line, waiting for each `HARNESS ack id=...`).
  6. Evidence: screenshots, `FLSpew.txt` (`<prefix>/drive_c/users/steamuser/AppData/Local/Freelancer/FLSpew.txt`, VERIFIED path), the FLUF log, the devbridge log, new `*.dmp` files, `wine.log`, and a `verdict.json` from REQ-13.
  7. Teardown: devbridge `quit`, then `wineserver -k` scoped to the lane.
  - The run directory is **`$FLMOD_TESTRUNS/<UTC YYYYmmdd-HHMMSS>-lane<N>-<name>/`** (absolute, gitignored; CONVENTIONS §5). Nothing is written under the worktree or `harness/out/`.
- **REQ-P0-HARNESS-12: devbridge core** (engine-agnostic C++, compiled into both track spike DLLs and later replaced by W1-CORE's production devbridge). Files: `harness/devbridge/devbridge_core.hpp/.cpp` plus `harness/devbridge/PROTOCOL.md`, with Python client `harness/devbridge.py`.
  - **Directory:** `$HDE/SAVE/devbridge/`, located relative to the exe as `<exe dir>\..\SAVE\devbridge\` (fixed; independent of GetUserDataPath). It is active only if `<exe dir>\devbridge.enabled` exists.
  - **Input:**
    - The harness writes `cmd-<seq>.txt`, where `<seq>` is a zero-padded monotonic integer. Write to a temp name, then `mv`.
    - Each file holds one command line: `<id> <verb> <args...>`.
    - The game polls every 10 frames **on the main thread** and processes files in seq order. It deletes each after reading and remembers the last seq processed, because Wine delete lag means a file can be seen twice (R4 §B10).
  - **Output:** append-only `log.txt`, one line per event, flushed per line:
    - `HARNESS t=<game seconds, 3 decimals> wall=<unix ms> <key=value ...>`
    - values with spaces are double-quoted;
    - every command produces `HARNESS ack id=<id> ok=1|0 [err="..."]` plus any data lines.
  - **Core API (C++):**
    - `void DevbridgeInit(const char* exeDir)`
    - `void DevbridgeTick(double gameSeconds)` (call every frame from the platform's tick)
    - `void DevbridgeRegister(const char* verb, std::function<CmdResult(const Cmd&)>)`
    - `void Harness(std::string_view kv)` (emits a line)
  - **Built-in verbs** (core): `ping`, `echo <text>`, `sleep_frames <n>`, `seq`.
  - **Track-provided verbs** (each track implements; same names and semantics):
    - `state` → `state=menu|space|docked|dead|loading base=<nick|-> system=<nick|-> ship=<arch|-> hull=<0..1> cash=<n> paused=0|1`
    - `load <savefile|pattern>`
    - `save <description>`
    - `quit`
    - `shot <name>`: emits `shot=<path>` when the PNG exists
    - `vmstat`: `VirtualQuery` loop over 0..0x7FFF0000 (0xFFFF0000 if LAA), emitting **`va_free_mb`, `va_largest_free_mb`** and `va_committed_mb` (the CONVENTIONS §4 key names)
    - `perf <seconds>`: `fps_avg`, `fps_p1`, `frame_ms_max` measured in the tick
  - **Events** use the `ev=<name>` key, never `ev=` (CONVENTIONS §4). The core emits `HARNESS ev=devbridge_ready` at init.
  - Never run game calls off the main thread. File I/O is fine on the main thread, given the tiny files and the 10-frame poll.
  - **Ownership:** `harness/devbridge/` is yours in Phase 0. W1-CORE promotes it in Wave 1 **without changing the wire format**.

### E. Fixtures

- **REQ-P0-HARNESS-13: crash and hang detection.** `harness/verdict.py <rundir>` → `verdict.json`: `{"verdict":"PASS|FAIL|CRASH|HANG|NO_WINDOW|EXITED_EARLY|TIMEOUT", "signatures":[...], "fault":{"module","rva","offset_lookup"}, "new_spew_errors":[...]}`.
  - **Crash signatures** (R4 §B7, §B10):
    - the process exited before the run finished;
    - `wine.log` contains `code=c0000005` or `Unhandled exception` (with `+seh`) followed by process exit;
    - a `dw15.exe` process (FL's Watson, launched by its own SEH filter);
    - a window titled `Fatal Crash` (FLUF CrashWalker) or `Freelancer has encountered`;
    - a new `*.dmp` / `*.mdmp` in the save dir or EXE dir.
  - **Hang:** the process is alive and neither FLSpew nor the devbridge log has grown for 60 s while commands are pending. Then dump with `WINEPREFIX=<lane> winedbg --minidump <rundir>/hang.mdmp <wpid>`, **through the guard** (`source tools/env.sh` first), with the wpid from `winedbg --command "info proc"` (R4 §B10), and kill (scoped `wineserver -k`).
  - **New spew errors:** `ERROR`/`WARNING` lines not matched by the baseline allow-list (REQ-14).
- **REQ-P0-HARNESS-14: crash triage.** `harness/triage.py <rundir>`:
  - Parse `+loaddll` lines to map module names to base addresses.
  - Find the faulting address in the `+seh` trace and compute module + RVA.
  - Look it up in the Starport crash-offsets table: `/home/user/freelancer/refs/StarportKnowledgeBase/static/payloads/crash-offsets.json` (VERIFIED present). The same file is in `/home/user/freelancer/refs/starport-kb-payload/crash-offsets.json`. Inspect its schema first.
  - Print the likely cause. Also print the last 50 FLSpew lines and the last 20 devbridge lines.
- **REQ-P0-HARNESS-15: baseline spew allow-list.** For each baseline: 3 runs of boot → main menu → load the `HARNESS_new_story` fixture → launch → 120 s in space → quit.
  - Collect `ERROR` and `WARNING` lines, normalize timestamps and pointers into regexes, and write them to `harness/baseline/spew_allow_<A|B>.txt`.
  - The known benign line is `StreamingSound: missing MP3 codec?`, which the play FLSpew shows four times (VERIFIED, R4 §B8). FLUF patches the MP3 warning off on A (R1 §3.4).
  - These files are our own derived regexes, not game files, so they are committed. Keep each pattern short.
- **REQ-P0-HARNESS-16: fixture save generator.** **`harness/fixtures/gen_fixture.py`**, the one generator from CONVENTIONS §6 / TESTING §Fixtures: `gen_fixture.py --install <HDE dir> --spec <yaml|name> --out <savedir>`. You seed it in Phase 0; W1-HARNESS owns and extends it from Wave 1.
  - Reads the **lane's** `EXE/newplayer.fl` as the template at runtime. Never commit it or any generated `.fl` (check_public blocks `.fl`).
  - Writes a plain-text `.fl` with CRLF line endings. HDE reads plain text; encryption is patched out (R5 §3.1 VERIFIED; R4 §A3.2).
  - **Fields** (R5 §3.2 VERIFIED field list):
    - `[Player]`: `description` (hex UTF-16BE of `HARNESS_<name>`, so FLUF `--save-file=HARNESS_<name>` matches), `name`, `tstamp`, `rank`, `money`, `system`, `base` (if docked) or `pos`/`rotate` (if in space), `location` (room hash, from a docked vanilla save; otherwise omit), `ship_archetype`, `equip = item, hardpoint, health`, `cargo = item, count, health, , mission`, `house = rep, faction` overrides, and `visit` entries for systems and bases that should be known.
    - `[StoryInfo]`: `Mission`, `MissionNum`.
    - `[mPlayer]`: `locked_gate` lines removed for post-campaign.
  - Save **filename**: FL names named saves `"%x.fl"` of CreateID(description) (adoxa console `fl_name`, R5 §3.1). Try that; if the game's load list doesn't show the fixture, try other names. Record what works.
  - **Specs** (YAML, committed: they contain only nicknames and numbers; no copied game text) under `harness/fixtures/specs/`. **Names are the TESTING §Fixtures `HARNESS_<name>` set.** Phase 0 seeds the subset the spikes need. Every fixture sets `system`, `base` (or `pos`) **explicitly**, because HDE's `newplayer.fl` starts the player in FP7, not Manhattan (CONVENTIONS §6).
    - `HARNESS_new_story`: newplayer story state (Mission_01a, rank 1), docked at `Li01_01_Base` (Manhattan), set explicitly.
    - `HARNESS_endgame_eagle`: docked at `Li01_01_Base`; `Mission = Mission_13`, `MissionNum = 42`; 60,000,000 credits; Eagle `ge_fighter6` with Nomad guns where the hardpoints allow, the best class-10 shield and 63 bots and batteries (TESTING §Fixtures); broadly friendly reps; all story `locked_gate` lines removed.
    - `HARNESS_endgame_eagle_space`: the same, in space about 3 km from Manhattan, at explicit `pos`.
    - `HARNESS_endgame_crete`: the same, docked at Planet Crete `Hi02_01_Base`, so Ew06 is reachable via `Hi02_to_Ew06_hole`.
    - `HARNESS_lvl1_rich_fp9`: rank 1, 5,000,000 credits, rep ≥ 0.6 with Freeport 9's owning faction, docked at Freeport 9 `Ew04_01_Base` (the D-2.1 level-gating test).
    - `HARNESS_ew06_space` (TESTING): endgame Eagle in space in Ew06 near the `Ew06_to_Hi02_hole` arrival.

    The other TESTING fixtures (yards, frontier, poor, OSP) are W1-HARNESS's.
  - **Post-campaign validity is UNVERIFIED.** R5 §6 and R3 §7: MissionNum 42 = `mission_end` per Librelancer; HDE open single player may differ. Verify by loading `HARNESS_endgame_eagle` and checking:
    - no story mission objective active;
    - the bar has no story offer;
    - flying through a story-locked gate works: `Li01_to_Li05` is `npc_locked` only. Use a story `locked_gate` from `newplayer.fl` instead, e.g. hash `2830511361` = `Li01_to_Li02`, which the story locks early (R3 §2.2).

    If MissionNum 42 doesn't produce free play, try `Mission = Mission_13` + `MissionNum = 41` with `[MissionState]` omitted. Then try copying the trigger effects of HDE's `m13_opensp_normal.ini` into the save: reps + unlocks. Record what works.
  - Fixture files are written into the **lane's** save dir only, never into Adam's `My Games` folder, never as `Restart.fl`.

### F. Display

- **REQ-P0-HARNESS-17: display keep-awake (test only).** `tools/display-awake.sh` **exists and is orchestrator-owned** (CONVENTIONS §14). It saves and restores the xset timeout/cycle/blanking and DPMS, plus xfce4-power-manager presentation mode, and holds a `setsid`-detached `xfce4-screensaver-command --inhibit`. The orchestrator verified an exact restore on 2026-10-17.
  - **Never run it against the live state.** The orchestrator's build-wide inhibitor must never be stopped by a test.
  - Add `harness/tests/test_display_awake.sh`. It runs `start`/`status`/`stop` with **`DISPLAY_AWAKE_STATE_DIR=$(mktemp -d)`**, asserts `xset q` is identical before and after, and asserts no extra inhibitor process remains.
  - Note the subtlety: if the live build's inhibitor is running, the test must not kill it. The script's pid file is per state dir, so it won't.
- **REQ-P0-HARNESS-18: screenshots.** `harness/shot.sh <wid> <out.png>`:
  1. `import -window <wid> out.png`; if it is black or uniform (check pixel variance with `magick`), fall back to `import -window root -crop WxH+X+Y`, using `xdotool getwindowgeometry --shell`.
  2. Also produce `out_small.png` with `magick -resize 50%`.

  The devbridge `shot` path (flplusplus PNG) is the preferred in-game alternative.

## Context pack

- `CLAUDE.md`; **`docs/plan/CONVENTIONS.md` (all; authoritative: §1 paths, §4 devbridge, §5 run output, §6 fixtures, §7 locks/ports, §14 ownership, §15 wine)**; `docs/plan/BUILD_PLAN.md` §3 (install profiles); `docs/plan/AUTONOMY.md` §1–2; `docs/plan/TESTING.md` §Lanes, §Devbridge, §Fixtures, §CrashTriage, §Scenarios
- Orchestrator scripts to read (don't modify): `tools/env.sh`, `tools/bin/_wineguard`, `tools/play_prefix_busy.sh`, `tools/play_prefix_manifest.sh`, `tools/display-awake.sh`
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md`: **all of Part B** (§B6 launching, the window-mode patch table, command-line switches, auto-load options, xdotool, screenshots, shutdown; §B7 logs, crash chain, Wine diagnostics; §B8 MP3 codec; §B10 harness design and the run-script sketch) and §0.1 pitfalls 12–15
- `$FLMOD_RESEARCH/R1-fluf.md` §1.4 (config, log path), §3.4 (HDE graphics chain and plugin conflicts), §6 (install steps)
- `$FLMOD_RESEARCH/R5-sp-architecture.md` §3 (saves: location, format, fields, filename, hooks), §6 (campaign-end detection, OSP)
- `$FLMOD_RESEARCH/R3-game-data.md` §7 (story state), §2.2 (locked gates), §10 (CreateID)
- `/home/user/freelancer/refs/FLUF/modules/debugger/Source/Debugger.cpp` (`--save-file` behaviour), `/home/user/freelancer/refs/adoxa-plugins/console/console.cpp` (`cmdLoad` / `fl_name` / `LoadGame` 0x5b2c70)
- `/home/user/freelancer/refs/StarportKnowledgeBase/static/payloads/crash-offsets.json`, `/home/user/freelancer/refs/universal-modder/` (methodology only: oracles, command-file bridge; `um win` refuses Linux, R4 §A5)

## Ownership

- **Owns:** `harness/` (except `harness/ci.sh` and `harness/ci.d/README.md`, which P0-REPO owns; no `ci.d` stage is yours in Phase 0), the runtime contents of `$FLMOD_LOCKS` and `$FLMOD_TESTRUNS`, and the prefixes `prefix-dev-base-A`, `prefix-dev-base-B`, `prefix-lane-*`.
- **Test only, orchestrator-owned:** `tools/env.sh`, `tools/bin/`, `tools/display-awake.sh`, `tools/play_prefix_*.sh`, `tools/watchdog.sh`, `tools/start-build.sh`.
- **Reads:** the play prefix (clone only), refs, research.
- **Must not touch:** `/home/user/freelancer/prefix`, `play.sh`, `~/.wine`, `docs/plan/`, `state/`, the orchestrator-owned `tools/` files above, and the live keep-awake state (`$FLMOD_LOCAL/display-*`).

## Contract

**Provides:**

- CLIs: `harness/baseline.sh`, `lane.sh` (incl. `--input`, `--perf`, `reap`), `deploy.sh`, `run.sh`, `config.sh`, `verdict.py`, `triage.py`, `shot.sh`, `devbridge.py`, `fixtures/gen_fixture.py`.
- The devbridge core C++ files and `PROTOCOL.md`. ARCH-0 promotes them to `docs/spec/devbridge.md`.
- The run-directory layout and `verdict.json` schema.
- Baseline prefixes A and B.

These are documented in `harness/README.md`.

## Tasks

1. Guard regression test (REQ-1) and the play-prefix idle check (REQ-2). Read, don't modify, the orchestrator scripts.
2. Write `baseline.sh`. Create B, then A, applying the tweaks and byte checks. Write `BASELINE.json`.
3. `lane.sh` with flock locking, plus the window-identification evaluation (REQ-8).
4. `deploy.sh` and `run.sh`. First run on B: launch, wait for the window, screenshot, quit. FLSpew shows `Starting single player game` at the main menu.
5. Devbridge core and Python client. For an in-game proof before the tracks exist, build a throwaway `harness/devbridge/selftest_dll` (Track-B-style dacom DLL, built with P0-TOOLCHAIN once available) that detours only the frame function at 0x5B2890 (VERIFIED R5 §1.3) and implements `ping`/`state` (menu vs in-game via the client base id at 0x673358, system at 0x673354, R5 §1.2). If P0-TOOLCHAIN isn't ready, deliver the C++ with host unit tests (a fake file system), and the in-game proof happens in P0-TRACK-A/B.
6. Fixture generator and specs. Verify loading (A via `--save-file`; B via menu clicks or later devbridge `load`). Verify post-campaign validity.
7. `verdict.py`, `triage.py`, and the baseline allow-lists for A and B.
8. Keep-awake test against a temp state dir (REQ-17).
9. Headless evaluation (REQ-9).
10. Concurrency proof: 2 lanes at once (A and B), each loading a fixture, both screenshotted, both torn down, with no interference.
11. `harness/README.md` and a `harness/selftest.sh` that runs tasks 4, 6, 7 and 10 end to end.

## Acceptance (automated; attach evidence)

- Guard refusal tests pass. Exit code 97 for the protected prefixes; a real `wine --version` works with an allowed prefix.
- `baseline.sh verify A` and `verify B` both PASS. `BASELINE.json` lists every tweak with its byte check, and the play prefix's files are unchanged: compare sha256 of `Freelancer.exe`, `dacom.ini` and `flplusplus.ini` before and after.
- `harness/selftest.sh` PASS:
  - B boots to the menu, loads `HARNESS_new_story`, launches into space, screenshot non-uniform, clean quit, `verdict=PASS`;
  - A boots with FLUF (fluf.log present, the five modules loaded, no forbidden-DLL MessageBox in the screenshot), loads `HARNESS_endgame_eagle` via `--save-file=HARNESS_endgame_eagle`, docked at Manhattan, `verdict=PASS`;
  - two lanes concurrently.
- **Crash-detection unit tests:** `verdict.py` on synthetic run dirs (crafted `wine.log` with a `c0000005` trace, a missing process, a dw15 marker) → CRASH; a stalled log → HANG.
- `triage.py` resolves a synthetic fault (e.g. `server.dll+0x14990`) to its documented cause from crash-offsets.json. R4 §0.1 pitfall 1 lists server.dll 0x14990 as "no valid undock point".
- **Fixture validity:** `HARNESS_endgame_eagle` loads into free play, with evidence per REQ-16. `HARNESS_lvl1_rich_fp9` loads at Freeport 9 with rank 1.
- `test_display_awake.sh` (temp state dir) passes: identical `xset q` before and after, and the live inhibitor (if any) untouched.
- `test_guards.sh` passes.
- **Locks are global:** two lane acquisitions from two different worktrees contend correctly (absolute `$FLMOD_LOCKS`); `--perf` excludes other lanes.
- Headless evaluation report: USABLE or NOT USABLE, with evidence.

## Engine facts to rely on / verify

- VERIFIED: the HDE window title is `Freelancer`; multi-instance is allowed (`Freelancer.exe` @0x1E6DCC = `00`); intros are already skipped; FLSpew path; plain-text saves; frame function 0x5B2890; client base/system mirrors at 0x673358 / 0x673354.
- **UNVERIFIED, to settle here:**
  - `--save-file` coexistence with FL's own CLI parser;
  - a subpath in dacom `[Libraries]`;
  - window-to-PID mapping;
  - headless gamescope with DXVK;
  - the fixture filename convention;
  - the post-campaign fixture state;
  - the FLUF log path.

## Pitfalls

- **FL pauses when unfocused** unless the 0x1B264C patch is applied. Proton only reliably delivers real XTest input to the focused window, and `windowactivate` steals Adam's desktop. That's acceptable during the build (AUTONOMY §1), but always hold the `input` lock (R4 §0.1 #14).
- `WINEDEBUG=-all` (as in `play.sh`) hides silent DLL load failures. Lanes use `fixme-all,+seh,+loaddll` (R4 §0.1 #12).
- FL's own SEH filter launches `dw15.exe`, so `winedbg --auto` may never run. Rely on `+seh` and the process state (R4 §B7.2).
- Never `pkill -f Freelancer`; it matches editors too. Only `wineserver -k` with the lane's `WINEPREFIX`.
- Saves shared across differently-modded installs crash (darklab8: `000c22fe`, `000c21de`). That's why each lane has its own prefix and `save_in_directory = true` (R4 §0.1 #15).
- flplusplus `always_regenerate_restart_file = true` regenerates `Restart.fl`, so never put fixtures there.

## Fallbacks and degrade path

| Problem | Fallback |
|---|---|
| Window/PID mapping fails | Serialize launches under the input lock. Parallel lanes still work for devbridge-only tests. |
| Headless unusable | All lanes on `:0` |
| `--save-file` broken on A | xdotool menu loading for A too, until the platform layer offers `load` |
| Post-campaign fixture can't be made valid | Keep `fresh_*` fixtures plus a `force_postcampaign` devbridge verb, which later packages implement by setting the mod's own `campaign_complete` flag (DESIGN D-13.1 tracks it with our own flag) |
| FLUF baseline A can't boot after all mitigations | Report it. G0a treats A as failing items 1–2 |

## Report

AGENT_BRIEF_TEMPLATE format. Include `BASELINE.json` for both tracks, the window-identification method chosen, the headless verdict, the fixture filename rule, the post-campaign fixture recipe, the FLUF log path, and lane-count advice (FPS with N instances).

## Gate-time addendum

(Orchestrator: attempt number, commit trailer.)
