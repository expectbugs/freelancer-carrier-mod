# Testing strategy: how the unattended build proves the mod works

Adam is away for the whole build. **Nothing is "done" until the build has proven it in the real game under Wine**, with evidence a reviewer can re-run.

Every package spec, gate and milestone cites the sections of this file by name (§Layers, §Lanes, §Devbridge, §Fixtures, §Scenarios, §Playbot, §Vision, §Metrics, §Soak, §SaveCompat, §CrashTriage, §CI, §M1, §M2, §M3, §F).

**`docs/plan/CONVENTIONS.md` is the single source for names, paths, verbs, locks and procedures.** If this file disagrees with it, CONVENTIONS wins and this file gets corrected.

**Ground truth used here** (verified in research; `$FLMOD_RESEARCH/R4` §B6–B10, R5, R6):

- **Wine:** wine-proton 11.0.1 with DXVK. It is always invoked through the guards in `tools/bin/`; never call `/usr/lib/wine-proton-11.0.1/bin/*` or `/etc/eselect/wine/bin/*` directly (CONVENTIONS §15).
- **Game window:** titled `Freelancer`.
- **Display:** X `:0`, currently 3744×2106.
- **Multi-instance:** already enabled in HDE (`Freelancer.exe` @0x1E6DCC = `00`).
- **Saves:** plain text.
- **Focus:** the game pauses when unfocused unless `Freelancer.exe` @0x1B264C is patched to `BA 01 00 00 00 90` (lanes apply this).
- **FLSpew:** per prefix at `drive_c/users/steamuser/AppData/Local/Freelancer/FLSpew.txt`. The baseline already contains 4 harmless `StreamingSound: missing MP3 codec?` ERROR lines, so always diff against the baseline.

---

## §Layers

Each layer must pass before the next is attempted. A package's evidence includes every layer that applies to it.

| # | Layer | What | Who runs it | Pass |
|---|---|---|---|---|
| 1 | **Host unit** | Engine-free C++ in `src/logic/` built natively with clang++ + doctest; Python tools, generators and sidecar with pytest via `$FLMOD_VENV`. Deterministic seeded RNG; golden files in `$FLMOD_GOLDEN` when derived from game data. | author, reviewer, CI | 100% green; no flaky test (each new test is run 20× locally once) |
| 2 | **Build / import** | `clang-cl` i686 build of the module DLL(s); `toolchain/check_imports.py` (only allowed DLLs; every MSVCP140/VCRUNTIME140/api-ms-* import exists in the prefix's Wine builtins, per R1 §5.3 step 8); exports present | author, CI | no warnings-as-errors, import check clean |
| 3 | **Data validation** | `gen/run.py` output against the lane's install: cross-references (archetypes, loadouts with an engine, factions, pilots, bases, rooms, markets, IDS), CreateID + faction-hash collision scan (R4 §A1.3), IDS index detection (expects 8 on HDE), public-safety check (`tools/check_public.py`) | author, CI | zero errors; collisions = 0 |
| 4 | **In-game scenario** | `harness/scenario.sh <file\|dir>` on a lane: fixture save → devbridge steps → `HARNESS` assertions → screenshots + vision checks → crash/spew checks (§Scenarios) | author | verdict `PASS`, or `DEFERRED(<ID>)` (CONVENTIONS §8) |
| 5 | **Reviewer re-run** | An independent reviewer re-runs host tests and the package's primary scenario on its own lane (REVIEWER_BRIEF_TEMPLATE) | reviewer | reproduced |
| 6 | **Regression** | All scenarios tagged `regression` (every merged package contributes ≥ 1) across ≥ 2 lanes after each merge (`ci.sh --full` at gates; the `ci` subset per merge), plus the **wave integration pass** of DEFERRED scenarios (CONVENTIONS §8) | orchestrator via CI | all green; quarantined scenarios report `SKIP(quarantined)` (CONVENTIONS §10); a flaky scenario is a bug (FIX package) |
| 7 | **Playbot** | Agent-driven milestone playthrough using real input, screenshots and vision rubrics (§Playbot, §M1–§M3) | M*-PLAYTEST packages; gate F is run by the orchestrator (§F) | every checklist step PASS, SKIP-DEGRADED, SKIP(quarantined), or FAIL with a FIX proposal |
| 8 | **Soak** | Long randomized journeys, memory/address-space tracking, crash/hang detection (§Soak) | gates, W5-SOAK | zero crashes/hangs; no unbounded growth |

**Rules:**

- A scenario that exercises engine behavior is never replaced by a host test. Host tests prove logic; scenarios prove the engine does what the logic assumes.
- Every bug fixed gets a regression test at the lowest layer that can catch it.
- Results are never faked or silently waived. A skipped check is `SKIP` with a reason, and the gate decides whether a SKIP is acceptable.
- Every evidence path in a report must exist under `$FLMOD_TESTRUNS` (= `/home/user/freelancer/carrier-mod/local/testruns`) at report time. Nothing is written to `harness/out/`.
- A `DEFERRED(<ID>)` scenario is accepted only when `<ID>` is an unmerged sibling in the same (sub-)wave. It always runs in that wave's integration pass.

---

## §Lanes

A **lane** is an exclusive, disposable game install plus a window slot.

- **Prefix:** `/home/user/freelancer/prefix-lane-<N>`. Each one is a reflink clone of the chosen dev baseline (`prefix-dev-base-A|B`, built by P0-HARNESS):
  - `cp -a --reflink=always`;
  - instant;
  - no absolute self-paths in the registry (verified in R4 §B10).
- **Freshness:** before each run, `harness/deploy.sh` does the following:
  1. a lane-scoped `wineserver -k` + `-w`, through the guard (`source tools/env.sh; WINEPREFIX=<lane> wineserver -k`);
  2. `rsync --delete` the HDE dir from the baseline (no leftovers);
  3. overlay the built mod (`gen/run.py deploy` output);
  4. run the idempotent patchers;
  5. write fixtures;
  6. write a manifest (git SHA + sha1 of deployed files) into the run dir.
- **Lane tweaks** (inherited from baseline):
  - flplusplus `save_in_directory = true`, `screenshots_in_directory = true`;
  - PerfOptions `size= 1280, 720`;
  - keep-running-unfocused patch (verify bytes `83ff010f94c2` first);
  - `devbridge.enabled` marker;
  - `WINEDEBUG=fixme-all,+seh,+loaddll`, `DXVK_LOG_LEVEL=warn`;
  - optionally `DXVK_CONFIG="d3d9.presentInterval = 0"` (B6) if a covered window blocks Present (P0-HARNESS measures).
- **Locks** (CONVENTIONS §7): managed by `harness/lane.sh`, using `flock` on files in `$FLMOD_LOCKS` (absolute, so all worktrees share them).

  | Command | Gives |
  |---|---|
  | `lane.sh acquire [--lane N]` | An exclusive lane |
  | `lane.sh acquire --input` | Also the global input lock. Required for anything that focuses a window, moves the mouse or sends keys, since synthetic input goes to the focused X window. |
  | `lane.sh acquire --perf` | The exclusive perf lock: waits until no other lane runs and blocks new ones. Used for S-PERF and every FPS/frame-time metric. |
  | `lane.sh reap` | Breaks locks whose holder pid is dead, and kills that lane's wineserver |

  Locks carry holder info (package id, pid, start time).
- **Window slots:** lane N's window is moved to a fixed tile at 1280×720 with `xdotool windowmove/windowsize`. Lane windows all share the title `Freelancer`, so the harness identifies each by its wine process PID (P0-HARNESS). The screen fits 2×2 tiles; more lanes overlap harmlessly, since screenshots use `import -window <wid>` and that works when uncovered.
  - If P0-HARNESS finds that covered windows break screenshots or Present, the devbridge `shot` command (backbuffer capture via flplusplus' PrintScreen path or our own) becomes the default.
- **Headless option:** P0-HARNESS evaluates `gamescope --backend headless -w 1280 -h 720 -- wine Freelancer.exe` (R4 §B6, UNVERIFIED with DXVK/NVIDIA).
  - If it works, devbridge-only lanes run headless, screenshots come from devbridge `shot`, and `--input` scenarios still use `:0`.
  - Xvfb is not used: no Vulkan WSI on NVIDIA.
- **Concurrency:** default **3 lanes** (`LANES=3` in `harness/config.sh`). P0-HARNESS measures 1–4 concurrent instances (GPU/CPU load, frame pacing, crash rate) and sets the default; S-PERF may lower it. Input-locked runs are serialized; perf-locked runs are exclusive.
- **Sidecar per lane** (CONVENTIONS §7, §13):
  - lane N's game connects to `FLCOPILOT_PORT = 29170 + N`, and the harness starts a sidecar on that port;
  - the sidecar runs in its **test profile** (`--profile test`: fake LLM, null audio sink, offline models, `--mic-file` input);
  - only M3's single live-brain smoke step uses the real brain.
- **Display keep-awake:** `tools/display-awake.sh start|stop|status`, which is **orchestrator-owned** (CONVENTIONS §14). Packages never edit or `stop` it.
  - **`start`** saves the current settings (xset screensaver timeout/cycle and blanking preference, DPMS state, xfce4-power-manager `presentation-mode`) to `local/display-settings.bak`, then:
    - `xset s off`, `xset s noblank`, `xset -dpms`;
    - sets xfce4-power-manager `presentation-mode` to true;
    - starts a `setsid`-detached `xfce4-screensaver-command --inhibit` (its pid goes in `local/display-inhibit.pid`).
  - **`stop`** kills the inhibitor, restores `presentation-mode` first, then the xset values.
  - The orchestrator runs `start` at build start and on every resume (AUTONOMY §5), and `stop` at COMPLETE, HALTED or STOP. The watchdog also runs `stop` on STOP.
  - **Tests** of this tool must set `DISPLAY_AWAKE_STATE_DIR` to a temp dir and never touch the live state.
- **Wine guard:** every lane script sources `tools/env.sh`. The guards resolve `WINEPREFIX` with `realpath -m` and refuse any prefix other than `prefix-dev*|prefix-lane*|prefix-carrier*`, including the sentinel `prefix-UNSET` (CONVENTIONS §15).
  - `harness/` never references `/home/user/freelancer/prefix` except as the clone source.
  - It clones only while `tools/play_prefix_busy.sh` reports the play prefix idle. That check looks at the `WINEPREFIX` env and the cwd of every process; `play.sh` does `cd EXE; exec wine-proton …`, so `pgrep -f` misses it.

---

## §Devbridge

A file-based command channel compiled into dev builds of the module. P0-HARNESS creates the core; W1-CORE promotes it to production without changing the wire format. It needs no keyboard focus, which makes tests deterministic, and it gives a machine-readable oracle.

- **Enable:** only if `EXE/devbridge.enabled` exists in the deployed install. It is never present in `prefix-carrier` unless Adam creates it.
- **Protocol (canonical):** `harness/devbridge/PROTOCOL.md`, created by P0-HARNESS (REQ-P0-HARNESS-12). ARCH-0 copies it to `docs/spec/devbridge.md`, together with the frozen verb and event table (CONVENTIONS §4). The summary below must match; if they differ, `docs/spec/devbridge.md` and CONVENTIONS §4 win.
- **Paths** (lane's install, `<HDE>` = `drive_c/Games/Freelancer HD Edition`): directory `<exe dir>\..\SAVE\devbridge\` = `<HDE>/SAVE/devbridge/`, fixed and independent of GetUserDataPath.
  - **Commands in:** the harness writes `cmd-<seq>.txt` (zero-padded monotonic `seq`) via a temp name then `mv` (atomic). Each file holds one command line: `<id> <verb> <args…>`.
  - **Processing:** the module polls every 10 frames **on the main thread**; the frame loop keeps running during the F1 pause (R5 §1.3). It processes files in `seq` order and deletes each after reading. It remembers the last processed `seq`, because Wine delete lag can show a file twice (R4 §B10). Long waits are `wait_*` verbs that yield across frames, with a per-command timeout.
  - **Output:** append-only `<HDE>/SAVE/devbridge/log.txt`, flushed per line. The module logger mirrors it to FLSpew/`fluf.log` too.
- **Output line format:** `HARNESS t=<game seconds, 3 decimals> wall=<unix ms> <key=value …>`. Values with spaces are double-quoted.
  - Every command produces `HARNESS ack id=<id> ok=1|0 [err="…"]` plus any data lines.
  - Unsolicited event lines carry **`ev=<name>`** (never `evt=`).
  - Periodic events from W1-CORE: `ev=hb` every 10 s (hang detection), `ev=perf fps_avg= fps_p1= ships= window_s=10` every 10 s, `ev=mem va_free_mb= va_largest_free_mb= heap_mb=` every 60 s.
  - **Platform events** (seed list, frozen by ARCH-0 in `docs/spec/events.md`): `ev=docked base=`, `ev=undocked`, `ev=launched`, `ev=jump.out`, `ev=jump.in system=`, `ev=save file=`, `ev=load file=`, `ev=death`, `ev=pause on=0|1`, `ev=menu`. Scenario waits use these names.
- **Vocabulary** (CONVENTIONS §4 is authoritative; units are metres, seconds, credits):

  | Command | Owner | Effect / output |
  |---|---|---|
  | `state` | P0 / W1-PLATFORM, extended by W1-CORE | `state=menu\|space\|docked\|dead\|loading base= system= ship= hull=0..1 cash= paused=0\|1`, plus `pos=x,y,z shield=0..1 docked= in_cruise=` |
  | `vmstat` / `perf <s>` | P0 / W1-PLATFORM | `va_free_mb= va_largest_free_mb=` / `fps_avg= fps_p1= frame_ms_max=` |
  | `load <pattern>` / `save <desc>` / `quit` / `shot <name>` | P0 / W1-PLATFORM | SP load via the menu path; SP save; clean exit; capture to `<HDE>/SAVE/devbridge/shots/<name>.png` → `shot=<path>` |
  | `wait_in_space [timeout]` / `wait_docked [base] [timeout]` / `wait_menu` / `wait_event <ev> [timeout_s]` | W1-CORE | Yields until true, or `ack ok=0 err=timeout` |
  | `time` / `time.skip <s>` / `time.scale <x>` | W1-CORE | `time.skip` advances **the mod's** game clock (wages, respawns, travel), not engine physics → `ev=time skipped=`. `time.scale` answers `err=unsupported` if infeasible |
  | `pause on\|off`, `config get\|set\|reload`, `log level`, `log <text>`, `assert <expr>`, `rng.seed <n>`, `perf.sample`, `mem.sample`, `help` | W1-CORE | `assert` → `ev=assert ok=0\|1 expr=`; `perf.sample` / `mem.sample` emit an immediate `ev=perf` / `ev=mem` |
  | `debug crash` / `debug hang` | W1-CORE (test-only) | Deliberate crash or hang, used to prove triage and hang detection |
  | `base <nick>` / `system <nick> [x,y,z]` / `pos x,y,z` / `launch` | W1-CORE (test cheats) | Dock (in space via ForceLand, deferred one tick; **never** ForceLand while docked) / relocate / undock (`blocked=1 reason=` if blocked). `base carrier:<name>` resolves a carrier (W2-CARRIER-GAME). |
  | `rep <faction> <v>` / `cash <n\|+n\|-n>` / `give <good> <n>` / `take <good> <n>` / `equip <item> <hp>` / `godmode on\|off` | W1-CORE (test cheats) | Reputation, credits, cargo, equipment |
  | `spawn <npc_def> [n] [near=player\|x,y,z] [tag=<t>]` / `despawn <tag\|id>` / `freeze <tag>` / `thaw <tag>` / `target <id\|tag>` / `kill <id\|tag>` | W1-SPAWN | Validated spawns through the spawn service. `near=`/`tag=` are canonical; `rel=`/`at=`/`id=` are accepted aliases |
  | `ui.find <id>` → `ev=ui rect=x,y,w,h visible=0\|1`; `ui.click <id>`; `ui.open <panel>`; `ui.list` | W1-UI | Every UI-kit widget and native button has a stable id; playbot uses `ui.find` for synthetic clicks |
  | `platform.*` / `world.probe` / `inv.*` | W1-PLATFORM / W1-WORLD / W1-INVENTORY | Defined by their specs and frozen by ARCH-0 |

- **Package namespaces** (owners per CONVENTIONS §4; arguments frozen in `docs/spec/devbridge.md` by ARCH packages):

  | Namespace | Owners | Examples |
  |---|---|---|
  | `carrier.*` | W2-CARRIER-GAME/UI, W2-LOADOUT, W3-ESCORT | `carrier.list`, `carrier.status <id>`, `carrier.buy class= tier= name= [at=]` (test), `carrier.travel <id> <dest> [docked\|escort]`, `carrier.stop <id>`, `carrier.escort <id> <dest>`, `carrier.loadout <id> show\|apply`, `carrier.resupply <id> <type> <n>`, `carrier.teleport_model <id> <sys> <x,y,z>` |
  | `yard.*` | W2-YARD | `yard.open`, `yard.buy class= tier= name= [upgrades=]`, `yard.install <carrier> <upgrade>`, `yard.state` |
  | `enc.*` | W2-ENCOUNTER | `enc.define`, `enc.trigger <def> [anchor=]`, `enc.list`, `enc.resolve <id> win\|loss`, plus `enc.freeze`, `enc.thaw` and `enc.state` within the owned namespace |
  | `reflex.*`, `ipc.*` | W2-REFLEX | `reflex.policy <actor> k=v`, `reflex.status <actor>`, `reflex.damage <actor> hull=<f>` (test), `ipc.status`, `ipc.inject <ndjson>` |
  | `ambush.*` | W3-AMBUSH | `ambush.odds <c>`, `ambush.force <c> [faction]`, `ambush.simulate <h> [seed]`, `ambush.state` |
  | `escort.*` | W3-ESCORT | `escort.state <c>`, `escort.force_stall <c>` (test) |
  | `nomad.*` | W3-NOMAD | `nomad.state`, `nomad.engage_test`, `nomad.kill_boss` (test) |
  | `loss.*` | W3-LOSS | `loss.kill <c>` (test), `loss.pods`, `loss.collect <pod>` |
  | `wing.*` / `hire.*` | W4-WINGMEN / W4-HIRING | `wing.list`, `wing.order <who> <order>`, `wing.add_test …` / `hire.candidates`, `hire.hire <idx>`, `hire.pay` |
  | `brain.*` | W4-BRAIN | `brain.context`, `brain.say <speaker> <text>` |
  | `esc.*` | W4-ESC-* | `esc.state`, `esc.stage <n>`, `esc.influence <faction> <sys> <delta>` |

- **Safety:** devbridge commands bypass gameplay rules and are for tests only. They never run unless the marker file exists, and they log every command executed.

---

## §Fixtures

Deterministic plain-text `.fl` saves are generated per run by **`harness/fixtures/gen_fixture.py`** (CONVENTIONS §6). P0-HARNESS creates the generator with the base set; **W1-HARNESS owns it from Wave 1** and adds the full set below. All fixtures use the **`HARNESS_<name>`** namespace (the save description).

- **Template:** the lane's own `EXE/newplayer.fl` plus YAML overrides. **Every fixture sets `system`, `base` and position explicitly.** HDE's `newplayer.fl` starts in the FP7 intro, so never rely on its defaults.
- **Output:** the lane's `<HDE>/SAVE/Accts/SinglePlayer/` (flplusplus `save_in_directory=true`), with `description = HARNESS_<name>`, so the harness loader (FLUF debugger `--save-file=HARNESS_<name>` technique, or our `load`) finds it.
- **Never** written into Adam's `My Games` folder or `Restart.fl` (flplusplus regenerates that).
- Packages may add fixture **definitions** in their own areas (e.g. `harness/fixtures/compat/` for W5-COMPAT, named `HARNESS_compat_*`); the generator renders them.

**Validation:** the generator validates `ship_archetype`, every `equip`/`cargo` good and hardpoint (against shiparch `hp_type`), base/system nicknames, and faction nicknames, against the lane's DATA. An invalid fixture is a generator error, never a game crash (R4 §A1.4.5).

**Campaign state:**

- `post_campaign: true` sets `[StoryInfo] Mission = Mission_13`, `MissionNum = 42` and removes the player `locked_gate` lines.
- Reputations are applied as m13 `enter_bar` would set them (R3 §7). W1-HARNESS must verify in game that gates open and that our campaign-complete detector reads `complete=1`.
- `story_mode: true` keeps the vanilla story state.

**Required fixture set** (more may be added by packages):

| Fixture | Contents | Used by |
|---|---|---|
| `HARNESS_new_story` | Vanilla story state (Mission_01a, level 1), with `system=Li01` / `base=Li01_01_Base` (Manhattan) set explicitly | smoke, pre-mod init, level-gating negative control |
| `HARNESS_lvl1_rich_fp9` | Level/rank 1, 5,000,000 cr, rep ≥ 0.6 with Freeport 9's owner faction, docked at Freeport 9 (`Ew04_01_Base`), post-campaign gates | **D-2.1 level-gating test** (buy Eagle) |
| `HARNESS_endgame_eagle` | Post-campaign, Eagle (`ge_fighter6`) with Nomad guns (`special_nomad_gun01/02` on compatible gun hardpoints, best class-10 shield, 63 bots/bats), 60,000,000 cr, broadly friendly reps, docked at Manhattan | most gameplay scenarios |
| `HARNESS_yard_<base>` (9) | `HARNESS_endgame_eagle` docked at each yard: `Li01_07_Base`, `Br01_02_Base`, `Ku01_03_Base`, `Rh01_02_Base`, `Bw03_01_Base`, `Bw06_01_Base`, `Bw02_01_Base`, `Ew04_01_Base`, `Ew06_02_Base` | Yard scenarios |
| `HARNESS_ew06_space` | Endgame Eagle in space in Ew06 near the Hi02 hole arrival (`Ew06_to_Hi02_hole` ~ 3882,0,19991), Nomads hostile | Nomad boss |
| `HARNESS_hostile_frontier` | Endgame Eagle with hostile reps to Outcasts/Corsairs/Rogues, in Bw01 | ambush odds/live ambush |
| `HARNESS_friendly_frontier` | Same position, friendly reps | ambush suppression |
| `HARNESS_poor` | 1,000 cr, endgame ship | wage/quit, yard refusal |
| `HARNESS_osp` | HDE Open-SP style (Mission_13 succeeded from start) | campaign-complete detection |

**Mod-state fixtures:** a fixture YAML may embed `carrier_json:`, which is written as the paired `<save>.carrier.json`. Examples: a fleet of 3 carriers in mixed states; a waiting ambush. These fixtures are generated through the **real** schema module (a Python mirror generated from the C++ schema, or the devbridge `save` of a constructed state), never hand-written JSON that could drift.

---

## §Scenarios

**Files:** a package's scenarios live in its owned `<dir>/scenarios/` or `harness/scenarios/<area>/` (BUILD_PLAN §6 conventions). The runner discovers both recursively.

**Runner:** `harness/scenario.sh <file|dir> [--lane N] [--keep]` (CONVENTIONS §5). It writes `$FLMOD_TESTRUNS/<UTC stamp>-<name>/` containing:

- `verdict.json`
- `devbridge_log.txt` (copy of the lane's `SAVE/devbridge/log.txt`, with the HARNESS lines)
- `FLSpew.txt` and `FLSpew.diff` (against the lane baseline)
- `wine.log` (with +seh/+loaddll)
- `fluf.log` (Track A)
- `shots/*.png` (+ `_small.png` at 50%)
- `vision.json`
- `manifest.json`
- `crash_lines.txt`

**Schema** (`docs/spec/scenario_schema.md` is this, verbatim):

```yaml
name: carrier_docked_travel_multihop      # unique
package: W2-CARRIER-GAME                  # owner
tags: [regression, carrier, ci]           # ci = in the per-merge subset (must run < 4 min)
lane: any | input | perf                  # input => input lock; perf => exclusive perf lock
requires: [W2-CARRIER-GAME]               # optional: if any listed package is unmerged on this branch => DEFERRED(<ID>)
fixture: HARNESS_yard_Li01_07_Base
mod_state: null | fixtures/state/<file>.yaml
timeout_s: 900                            # hard wall-clock cap for the whole scenario
setup:                                    # devbridge commands before steps; failures abort
  - cash 60000000
steps:                                    # executed in order
  - do: "yard.buy class=fleet tier=core name=Testudo"
    expect: {ack_ok: 1}                   # the runner matches "HARNESS ack id=<auto> ok=1"
  - wait: {ev: carrier.state, id: Testudo, state: Stopped, within_s: 20}
  - do: "base carrier:Testudo"            # test dock at the carrier (devbridge resolves the label)
  - wait: {ev: docked, within_s: 30}      # platform event (CONVENTIONS §4 seed list)
  - do: "carrier.travel Testudo Li03 docked"
  - expect_state: {carrier.Testudo.state: DockedTravel}
  - shot: travel_panel
  - vision: {shot: travel_panel, rubric: rubrics/carrier_travel_panel.yaml}
  - do: "time.skip 240"                   # mod clock only
  - wait: {ev: carrier.arrived, within_s: 30}
  - input: [click ui:carrier.launch]      # synthetic XTEST input: only allowed when lane: input
asserts:
  no_crash: true
  no_hang: true                           # ev=hb gap < 60 s while not paused
  no_new_spew_errors: true                # vs lane baseline, allowlist in harness/spew_allow.txt
  harness: ["ev=carrier.state id=Testudo state=Stopped"]   # regex lines that must appear
  forbid: ["ev=error", "ack id=\\S+ ok=0"]   # unless expected in a step
  metrics: {docked_travel_min_per_system: from_targets}     # thresholds from harness/metrics_targets.yaml
evidence: [shots, devbridge_log, spew_diff, wine_log, mod_json]
```

**Verdicts:**

- `PASS`, `FAIL`, `CRASH`, `HANG` or `ERROR` (harness fault);
- `DEFERRED(<ID>)` (a `requires:` package is unmerged);
- `SKIP(quarantined)` (listed in `/home/user/freelancer/carrier-mod/state/QUARANTINE.md`; CONVENTIONS §10).

A FAIL lists the first failing step, the last 50 HARNESS lines and the last 50 FLSpew lines.

**Flakiness:** a scenario that passes and fails on the same commit is flaky. Rerun it 5×; if flaky, open a FIX package. Flaky tests are never deleted to pass a gate.

**Determinism:**

- Scenarios seed the mod RNG (`rng.seed <n>`).
- Engine randomness (NPC AI) is tolerated by asserting on outcomes and ranges, not exact positions.

---

## §Playbot

The milestone playthroughs (§M1–§M3; §F is run by the orchestrator) are run by a **test agent acting as a player**. It proves the feature works through the same paths Adam will use: real clicks and keys, real camera, real UI. Method:

1. **Devbridge for setup and observation only:** fixtures, teleports to skip boring travel, `state` and `assert`. Gameplay actions that Adam would perform are done with **synthetic input** at least once per milestone: clicking the Yard button, typing a carrier name, pressing push-to-talk, clicking Stop, launching, flying with the mouse toward the carrier.
2. **Input recipe** (XTEST, with `lane.sh acquire --input` held; CONVENTIONS §7):

   ```
   xdotool windowactivate --sync $WID
   xdotool mousemove --window $WID <x> <y>
   xdotool click 1
   xdotool key <keysym>
   ```

   Keys and clicks go to the focused window via XTEST. **Never `xdotool key --window`**: XSendEvent is invisible to `GetAsyncKeyState`. UI coordinates come from `ui.find`, never hard-coded pixels. After each input, take a `shot` and confirm the expected change, by HARNESS event or by vision.
3. **Flight by input:** where the checklist says "fly", the playbot may use FL's own autopilot (Goto via the nav map, or a target plus the autopilot keys) with synthetic keys, rather than hand-steering.
4. **Journal:** `$FLMOD_TESTRUNS/playbot-<milestone>-<ts>/JOURNAL.md`, with one entry per checklist step:
   - intent;
   - actions (input and devbridge);
   - evidence (HARNESS lines, shot names);
   - vision verdicts;
   - PASS / FAIL / SKIP-DEGRADED / SKIP(quarantined) / BLOCKED(<step>);
   - notes on anything that *felt* wrong: UI overlap, confusing text, odd AI, long waits.
5. **Failures** (CONVENTIONS §10):
   - The playthrough **continues past a failed step**, and dependent steps are marked BLOCKED.
   - Every functional failure gets a FIX proposal in the report.
   - "Feel" notes within the §Metrics ranges go to a **Tuning notes** section, which the orchestrator copies into `state/TUNING.md`. They are not FIX proposals.
6. **Exploratory budget:** after the checklist, the playbot spends ≥ 20 minutes on unscripted play around the milestone's features, breaking things on purpose: dock spam, save/load during transitions, F1 pause mid-ambush, alt-tab. It journals and files findings.
7. **Independence:** the playbot agent is never the agent that wrote the feature. Its brief contains the checklist and DESIGN.md sections, not the implementation. Playbots never write `state/`; the orchestrator writes gate files from their reports.

---

## §Vision

How screenshots are judged. The agent reads PNGs with its multimodal Read tool.

- **Capture:** `shot` (backbuffer) or `import -window $WID`. Save the full image and a 50% downscale (`magick in.png -resize 50% out_small.png`); judge the downscale first, then the full image for text.
- **Automatic pre-checks** (`harness/vision_precheck.py`, owned by W1-HARNESS):
  - **Not black:** mean luminance > 8/255.
  - **Not frozen:** the image differs from the previous shot of the same run by more than 0.5% of pixels, unless the step expects a static frame.
  - **Correct size.**

  A failure means retake once after 2 s, then FAIL with reason `capture`.
- **Rubrics:** `harness/rubrics/<name>.yaml`, a list of yes/no items, each `mandatory: true|false`. Write them as concrete observations a stranger could verify. Examples:
  - "A large capital ship hull fills at least 10% of the frame within the centre third."
  - "A window titled 'Carrier Yard' is visible and its text is legible at 1280×720."
  - "No UI element overlaps the vanilla NavBar icons."
  - "The progress text reads like 'arriving in N minutes' with N between 1 and 10."
- **Judgment:** every item gets `yes|no|unclear` plus a one-sentence reason quoting what is seen. Results go to `vision.json`.
  - `unclear` ⇒ retake (different camera via a camera key, or wait 2 s), up to 2 times; then `unclear` counts as `no`.
- **Pass:** all mandatory items `yes`. Non-mandatory `no` items are logged as polish findings.
- **Independence at gates:** the reviewer (or gate agent) re-judges a sample (≥ 30%, always including all mandatory UI rubrics) without seeing the author's verdicts. Disagreement on a mandatory item ⇒ re-shoot and adjudicate by a third judgment; record it.
- **Non-negotiables:** a "feature visible" claim with no screenshot evidence is UNVERIFIED and fails the gate.

---

## §Metrics

Game-feel proxies. Adam can't playtest, so these numbers stand in for "feels right". Each is measured by a named mechanism, and the target ranges are design targets the owning package tunes toward via YAML.

**This table is the single source of thresholds.** W1-HARNESS encodes it verbatim in `harness/metrics_targets.yaml`; specs refer to it and never restate different numbers. Only an orchestrator decision changes it. Out-of-range results become tuning work, not ignored. FPS and frame-time measurements always run under `lane.sh acquire --perf`.

| Metric | Target | Measured by |
|---|---|---|
| Docked travel time per system crossed, balanced class (Fleet Carrier) | **2–4 real minutes** (D-7.13). Class multipliers from `docs/design/CARRIERS.md` (e.g. Trade ×1.5–2.0 slower, Escort ×0.6) must keep every class within 1–8 min | host sim over all adjacent-system pairs (route planner + speed model); in-game spot checks of `ev=carrier.arrived` timing with real time (no `time.skip`) on ≥ 3 routes |
| In-system docked travel | 0.5–3 min typical (gate to planet) | host sim |
| Escort travel crossing time | ≤ 2× the class's docked-travel time (D-7.13) | in-game `ev=escort.progress` |
| Ambush frequency per hour of carrier travel, hostile-rep traveller, no cargo | Liberty core (Li01–Li05) **≤ 0.1**; Bretonia/Kusari/Rheinland interiors **0.1–0.3**; Border Worlds **0.3–0.6**; Edge/Hispania **0.8–1.5** | **host** Monte Carlo (`src/logic/ambush` with real deploy-time `world.json`/exposure; ≥ 10,000 simulated hours per region class, seeded), checked against the analytic expectation Σ(λ·Δt) within 3σ. In game: `ambush.simulate` must reproduce the host result exactly for the same seed (determinism), plus a **qualitative** check (≥ 1 natural ambush on a forced high-exposure route). No in-game statistical rate comparison: about 2 expected events make it unreachable. |
| Reputation effect | Friendly (≥ +0.6) to every faction patrolling the route ⇒ odds × **≤ 0.25** | host sim |
| Cargo effect | Multiplier ≤ **×1.5** at any cargo value (D-9.3) | unit test + host sim |
| Ambush fight duration (player endgame Eagle + carrier, tier-matched) | **2–6 min** | in-game `ev=enc.spawn` → `ev=enc.resolved` |
| Nomad boss fight | **5–12 min** for Nomad-gunned Eagle + crew wingmen, unassisted | M2 playbot |
| Carrier survival vs tier-matched ambush, unaided, full nanobots | **≥ 70%** wins | host balance sim (W1-CARRIER-DESIGN, `src/logic/balance`), spot-checked in game ≥ 3 runs |
| Carrier vs much stronger ambush (two tiers above) | Loses most (≤ 30% wins) | host sim |
| Escort travel stuck detection | Escorted carrier progresses ≥ 300 m per 30 s along its route unless in combat or turning at a waypoint; a 90 s stall ⇒ `ev=escort.stuck` and recovery; no unrecovered stall | in-game `ev=escort.progress` lines |
| Dock-to-interior | < 5 s | `ev=docked` timing |
| Save/load restore drift | ≤ 1 % of route progress | `carrier.status` before save vs after load |
| Reflex decision latency | ≤ 0.5 s game time from threshold crossing to `ev=reflex.use` | in-game |
| Frame rate (1280×720, lane) | Average ≥ 45 fps and 1%-low ≥ 30 fps with ≤ 40 ships in a fight | module frame-time sampler: `ev=perf fps_avg= fps_p1= ships= window_s=10` every 10 s |
| Address space (32-bit) | `va_free_mb` ≥ 300 MB at all times; no growth trend > 20 MB/h after 15 min warm-up | module `ev=mem va_free_mb= va_largest_free_mb= heap_mb=` every 60 s (VirtualQuery walk/GlobalMemoryStatusEx inside the process; host RSS is meaningless under WoW64) |
| Army-scale curve | Report fps_avg/fps_p1/va_free_mb at 10/25/50/100/200 friendly followers + proportional enemies; warn threshold = first count where fps_p1 < 25 or `va_free_mb` < 400 | S-PERF, re-measured in M3 |
| Copilot latency | PTT release → simple order applied ≤ 0.6 s; free-form LLM reply first audio ≤ 6 s (Opus 5.5 low via CLI; measured, tuned) | sidecar instrumentation + fake-client tests |
| Load time impact | Mod adds ≤ 3 s to save load | `ev=load` timestamps vs baseline lane |

**The 10 sample routes.** W1-WORLD and W1-CARRIER-DESIGN measure these, and M1/M2 spot-check them. Endpoints are base nicknames; the route planner chooses the path.

| # | From | To | Kind |
|---|---|---|---|
| R1 | `Li01_01_Base` (Manhattan) | `Li01_07_Base` (Norfolk Shipyard) | in-system |
| R2 | `Li01_07_Base` | `Li02_01_Base` (Los Angeles) | 1 jump |
| R3 | `Li01_07_Base` | `Br01_02_Base` (Southampton) | multi-hop across the Independent Worlds |
| R4 | `Rh01_02_Base` (Oder) | `Bw03_01_Base` (Freistadt) | house to border |
| R5 | `Ku01_03_Base` (Yokohama) | `Bw06_01_Base` (Kurile) | house to border, gates and holes |
| R6 | `Bw02_01_Base` (Cadiz) | `Ew03_01_Base` (Leon) | border to edge, holes |
| R7 | `Ew04_01_Base` (Freeport 9) | `Hi02_01_Base` (Crete) | edge to Hispania |
| R8 | `Hi02_01_Base` (Crete) | `Ew06_02_Base` (Gammu) | to the Nomad system |
| R9 | `Li01_07_Base` | `Ew06_02_Base` | long haul across Sirius |
| R10 | `Br01_02_Base` | `Ku01_03_Base` | cross-Sirius between houses |

If a route is unreachable for capital ships (all links player-locked), W1-WORLD reports that as a finding and substitutes the nearest reachable endpoint.

---

## §Soak

**Journey generator:** `harness/soak/journey.py` (owned by W1-HARNESS; W5-SOAK adds only `harness/soak/mixes/w5_*.yaml`). It produces seeded random sequences of devbridge actions that exercise everything merged so far:

- teleport to a random reachable system/base;
- dock, launch, buy and sell;
- save, then load the same save, then load an older save;
- carrier orders (travel, re-route, stop, escort);
- forced ambushes and encounter freeze/thaw;
- wingman spawn and orders;
- F1 pause and unpause (synthetic key on the input lane only, else skipped);
- jumps via `InstantDock` to gates;
- carrier destruction and rebuy.

**Run:** `harness/soak/soak.sh --hours H --lanes L --seed S [--mix <file>]`. It runs journeys back-to-back per lane, restarting the game process every 45 min to also test cold loads. It collects `ev=hb`, `ev=perf` and `ev=mem` series into `soak.csv` per lane, under `$FLMOD_TESTRUNS`. Sidecars run in the test profile.

**Durations:**

| Gate | Soak |
|---|---|
| G1 | 30 min |
| M1 | 60 min |
| M2 | 2 h |
| M3 | 3 h |
| F | 6 h cumulative, across ≥ 3 lanes, each lane ≥ 1 h continuous |
| W5-SOAK | adds any extra hours it deems necessary |

**Crash-free criteria:**

- zero crash signatures (§CrashTriage);
- zero hangs (no `ev=hb` for 60 s while not paused);
- `va_free_mb` never < 300;
- no `va` growth trend > 20 MB/h after warm-up;
- no new FLSpew ERROR lines outside the allowlist;
- every save made during the soak loads afterwards (post-soak load check of a random 20).

Any failure ⇒ a FIX package with the seed, which reproduces it deterministically up to engine AI variance.

---

## §SaveCompat

The matrix, run by W5-COMPAT, with subsets per gate:

- **Carrier states × location:** save and reload in each of:
  - Stopped (player docked aboard; player in space near it);
  - DockedTravel (aboard), including after a re-route;
  - EscortTravel (player in space escorting);
  - Away (player elsewhere);
  - AmbushWaiting;
  - UnderAttack while docked aboard (held fight). The reload must spawn the solar and the held attackers **before** launch is allowed (W2-CARRIER-GAME REQ-7, W3-AMBUSH).
  - UnderAttack in space: if the engine permits saving in combat (record the fact); if saving is blocked, assert the block is graceful.
  - after Destroyed: carrier gone, loot pods not duplicated on reload.
- **Fleet sizes:** 0, 1, 3, 8, and the maximum **measured** by S-BASE (ENGINE_FACTS).
- **Assertion after each reload:**
  - carrier JSON round-trips (field-by-field diff empty except timestamps);
  - the carrier solar or ship exists where expected;
  - the player can launch when Stopped and cannot when in transit;
  - no duplicate spawns;
  - no orphan objects (`enc.list`, `carrier.list` and a spawn-registry dump agree).
- **Pre-mod saves:** `HARNESS_new_story`, a mid-campaign vanilla save, and an OSP save load into the modded install. They initialize empty mod state, show no errors, and the Yard works.
- **Corrupt/missing JSON:**
  - Missing ⇒ empty state plus a warning toast.
  - Truncated or invalid ⇒ keep a backup `*.carrier.json.bad-<ts>`, then load the last good backup `*.carrier.json.bak` (the module keeps 1 rolling backup) or empty state. Never crash.
  - A save docked at a carrier base whose record is gone recovers by restoring a minimal carrier and its solar, or by rewriting `base=` in the save and reloading. **Never `ForceLand` a docked player.**
- **Schema migrations:** every schema version bump ships a golden `vN → vN+1` migration test (host) and an in-game load of a vN fixture.
- **Uninstall relocation:** `tools/uninstall/relocate_saves.py` moves the player out of any carrier base (to the last real base, or the yard base) in all saves. Then those saves load in a lane built from the **unmodded** baseline (`prefix-dev-base-B`, no mod deployed) without crash.
- **Delete:** deleting a save in the load menu deletes its `.carrier.json` (save-delete hook; R5 §3.3).

---

## §CrashTriage

- **Signatures** (any one ⇒ CRASH):
  - the game process exits before `quit`;
  - `wine.log` matches `Unhandled exception|page fault|code=c0000005|starting debugger`;
  - a `dw15.exe` process appears;
  - a window titled `Fatal Crash` (FLUF CrashWalker) or `Freelancer has encountered` appears;
  - a new `*.dmp` appears in the user-data or SAVE dir.
- **Hang:** the process is alive, no `ev=hb` for 60 s, and not paused. Capture a minidump **through the guard**: `source tools/env.sh; WINEPREFIX=<lane> winedbg --minidump hang.mdmp <winpid>`, with the winpid from `winedbg --command "info proc"`. Then kill the lane.
- **Self-test:** the devbridge `debug crash` / `debug hang` verbs (W1-CORE, test-only) prove the detection works, in CI and once per soak.
- **Locate:**
  1. Faulting address − module base (from `+loaddll` lines in `wine.log`) = RVA.
  2. Look the RVA up in `/home/user/freelancer/refs/StarportKnowledgeBase/static/payloads/crash-offsets.json` (also `refs/starport-kb-payload/crash-offsets.json`). `harness/triage.py` does this automatically and prints known causes.
  3. For our DLL, symbolize with the DWARF debug info: build with `/Z7 -gdwarf`; `winedbg --gdb` (through the guard) or `llvm-symbolizer` on the RVA.
- **Analyze:** apply the **ten-explanations rule**:
  1. Write ≥ 10 distinct hypotheses consistent with all evidence into `$FLMOD_TESTRUNS/<run>/CRASH.md` (signature, scenario/seed, evidence paths, hypotheses). The orchestrator copies it into `state/CRASHES.md` (`state/**` is orchestrator-only).
  2. Choose the cheapest discriminating experiment.
  3. Record the result and the fix.
  4. Add a regression scenario reproducing the crash path.
- **Known hotspots to suspect first** (R4 §A1.4):
  - spawning with invalid ids;
  - destroying a just-spawned scripted NPC (SP-only crash 0x14661b);
  - base without solar at launch (server 0xab670, 0x14990);
  - ForceLand of a docked player;
  - capital death fuses (common 0x5da50/0x5e010);
  - loading a save with unknown nicknames (common 0xc22fe, 0x91f38);
  - per-system >10 jump objects (server 0x1b221);
  - calling pub:: from a non-main thread.

---

## §CI

`harness/ci.sh [--quick|--full] [--lanes N] [--only <stage>]` (CONVENTIONS §5). It writes `$FLMOD_TESTRUNS/<UTC stamp>-ci/summary.md`, which is the only file the orchestrator reads.

- Stages run in order and the script stops at the first failure, exiting non-zero.
- `public` is built in and always runs first.
- Every other stage is a drop-in `harness/ci.d/NN-<name>.sh`.
- A stage whose prerequisites don't exist yet reports **SKIP**, not FAIL.
- Quarantined scenarios report **SKIP(quarantined)**, and CI stays green.

| Order | Stage | Owner | What |
|---|---|---|---|
| — | `public` (built in) | P0-REPO | `tools/check_public.py` over `git ls-files -co --exclude-standard` (ignores only `.claude/worktrees/`, per CONVENTIONS §5; rejects files > 5 MB): no game files, extracts, `local/` content or secrets |
| 10 | build | P0-TOOLCHAIN | host (native clang++) and win32 (clang-cl i686) builds |
| 20 | host-tests | P0-TOOLCHAIN | doctest suites discovered under `tests/host/**` and `src/**/tests/` |
| 30 | pytest | P0-DATATOOLS | `$FLMOD_VENV/bin/python -m pytest` over the Python test dirs |
| 40 | data-validate | W1-DATA | `gen/run.py` against the pristine lane HDE dir, then validators (cross-refs, hash collisions, IDS index, level-gating patch applied to every market row) |
| 50 | import-check | P0-TOOLCHAIN | `toolchain/check_imports.py build/win32/*.dll` |
| 60 | scenarios-quick | W1-HARNESS | in-game smoke on 1 lane (boot → load `HARNESS_endgame_eagle` → `state` → `quit`), then the `ci`-tagged scenarios (skipped with `--quick`) |
| 70 | scenarios-full | W1-HARNESS | `--full` only: **all** `regression`-tagged scenarios on up to `--lanes` lanes |
| 80 | soak-smoke | W1-HARNESS | `--full` only: a 10-min mini-soak |

**Usage:**

| When | Run |
|---|---|
| Each merge into `main` | `ci.sh` (default = stages up to 60 with the `ci` subset) |
| Every gate | `ci.sh --full` |
| Authors during development | `ci.sh --quick` |

---

## §M1: Carrier v1 and copilot reflexes (bot playthrough #1)

Run by **M1-PLAYTEST** (playbot, input lane). Every step needs evidence. Fixture: `HARNESS_yard_Li01_07_Base` (Norfolk Shipyard) unless stated. Failures don't stop the playthrough (§Playbot 5).

1. **Level gating removed (D-2.1).**
   1. Load `HARNESS_lvl1_rich_fp9`, open the Ship Dealer by **synthetic click**, select the Eagle.
   2. Vision: the Buy button is enabled, with no level warning. Buy it.
   3. `state` shows `ship=ge_fighter6`.
   4. Repeat for a class-10 shield at an equipment dealer.
   5. Negative control: with rep below the requirement, the purchase is still blocked by reputation.
2. **Yard panel by input.**
   1. Click the **Carrier Yard** NavBar button (`ui.find yard.navbutton`).
   2. Vision rubric `yard_panel`: legible, FL-styled, lists ≥ 3 classes with prices, no overlap with the NavBar.
3. **Configure and buy.**
   1. Select Fleet Carrier and add one upgrade (hull plating).
   2. Type the name `Testudo` (synthetic keys) and confirm.
   3. Cash drops by exactly the shown price.
   4. `ev=carrier.state id=Testudo state=Stopped`.
   5. Undock and fly to the carrier by autopilot; a vision shot shows the carrier hull near the yard.
4. **Dock at the carrier.**
   1. Dock by request (target the carrier, dock key).
   2. `ev=docked`; the aboard base room loads (vision: battleship interior).
   3. The carrier menu is visible, with Travel, Status, Hold and Quartermaster.
5. **Docked multi-hop travel.**
   1. Order travel to a system two jumps away (e.g. Li01 → Li03 → Iw05 if reachable, or as the route planner offers).
   2. The progress text matches the "N systems out, arriving in M minutes" form (vision + `carrier.status`).
   3. A launch attempt is **blocked**, with a message (vision + `launch` returns `blocked=1`).
   4. Wait real time on the first leg and measure: within §Metrics.
6. **Re-route** (CONVENTIONS §9). While travelling, pick a different destination by input.
   1. The state stays `DockedTravel`, with no `Stopped` in between.
   2. `carrier.status` shows the new destination.
   3. The route list updates.
7. **Stop mid-route.**
   1. Click Stop. `ev=carrier.state state=Stopped` with a position on the route.
   2. `assert` it is a safe point (outside hazard buffers).
   3. Launch: the player appears beside the carrier (distance 300–1500 m; vision: carrier visible).
8. **Save/load in each state** (§SaveCompat subset): Stopped (aboard and in space), DockedTravel (aboard), and DockedTravel after a re-route. Each reload restores the state and position (drift within §Metrics), with no duplicate carrier.
9. **Retrofit.**
   1. Fly the carrier back within 10 km of Norfolk (docked travel).
   2. Install a turret upgrade; the carrier respawns with it (vision: turret visible, or `carrier.loadout <id> show` lists it).
   3. Retrofit at 15 km is refused, with a clear message.
10. **Fleet.**
    1. Buy a second carrier (Escort Carrier) at the same yard.
    2. `carrier.list` shows 2.
    3. Docking at each lands in the right interior and the menu shows the right name.
11. **Reflex.**
    1. Spawn hostiles (`spawn <outcast fighter d19> 4 near=player tag=h`) and take damage.
    2. The nanobot reflex fires at the threshold (`ev=reflex.use actor=player what=bots`).
    3. The voice line plays: `ev=reflex.voiceline played=1`, and the sidecar test-profile log shows playback to its null sink, or the FL sound event fires if voice lines go through FL.
    4. With the sidecar stopped, the reflex still works and the game is unaffected.
12. **Carrier auto-nanobots** (CONVENTIONS §9).
    1. Damage the **Stopped** carrier with spawned attackers. It enters `UnderAttack` (`ev=carrier.state … state=UnderAttack`), heals from its stock (`ev=reflex.use by=carrier`), and the stock decreases.
    2. After the attackers are destroyed or despawned, `Won` → `Stopped`.
    3. Then `reflex.damage carrier:<id> hull=0.4` with no attackers: it still heals, and stays `Stopped`.
13. **Encounter proof event** (W2-ENCOUNTER). With proof events enabled, `system Hi02` with `HARNESS_endgame_eagle`: the scouts spawn; winning sets the flag; the flag persists across save/load.
14. **Exploratory** 20 min (§Playbot 6); then a **60-min soak** (§Soak).

**M1 passes** when every step passes, or a degraded or quarantined step is documented and the gate procedure accepts it (BUILD_PLAN §7, CONVENTIONS §10).

## §M2: Danger and tiers (bot playthrough #2)

Run by **M2-PLAYTEST** (playbot). Fixtures: `HARNESS_hostile_frontier`, `HARNESS_friendly_frontier`, `HARNESS_ew06_space`, yard fixtures. Failures don't stop the playthrough.

1. **Ambush while aboard (D-9.5).**
   1. Docked travel through a high-exposure route (from deploy-time exposure data; e.g. Bw01/Bw02 Outcast/Corsair zones).
   2. Force the roll once (`ambush.force`). Separately, run **natural** rolls over ≥ 3 expected-ambush intervals (`time.skip`, with real-time spot checks): at least one natural ambush must occur (qualitative; §Metrics).
   3. Alert, forced stop, carrier in space with attackers nearby. The fight **holds while docked**: zero carrier damage.
   4. **Held-fight reload:** `save HARNESS_m2_held`, quit, relaunch, load. The solar exists before any launch, the attackers are holding, and the hull is unchanged.
   5. Launch, fight, win: `ev=enc.resolved outcome=win`, then the carrier returns to Stopped.
2. **Ambush while escorting.** Order escort travel (`carrier.escort`, or the in-space panel by input) from the player's ship within 10 km; force an ambush; a real fight on the spot; the carrier's reflex nanobots fire; win.
3. **Away ambush / paused distress.**
   1. Order docked travel, Stop, undock, order the carrier on (escort), then leave the system: the carrier goes Away.
   2. Force an ambush roll: a distress NN message, a waypoint and a log entry.
   3. Save and reload; it is still waiting.
   4. `time.skip 5400` (3 in-game days at 1800 s/day); still waiting, with no damage taken.
   5. Fly there and drop out of cruise within 8 km: the fight spawns within seconds (vision: "there it is, under fire").
   6. Leave mid-fight: AmbushWaiting again. Return: it resumes with the remaining attackers. Win.
   7. One-at-a-time: a second roll is impossible while waiting (`ambush.force` refused with a reason).
4. **Escort across 2 gates.**
   1. The escorted carrier flies to the gate, plays the effect, and appears on the far side when the player comes through.
   2. Repeat for a second gate (or a hole).
   3. Stuck detection never leaves an unrecovered stall; travel time is logged against §Metrics.
5. **Away and back.** Leave the escort mid-route; return later. The carrier is at the simulated position (±1 km of the model) and resumes.
6. **Border/Edge tier.** At Freistadt (or Freeport 9), buy a Border/Edge-tier carrier of a class not sold at Core. Its stats in `carrier.status` match `docs/design/CARRIERS.md`, and its services include the tier's extras.
7. **Nomad gate.**
   1. Gammu's yard refuses carrier sales before the flag (vision: the locked message).
   2. In Ew06, the boss group exists (`enc.list` / `nomad.state`).
   3. Engage regular Nomads (`nomad.engage_test`, and once by input): the boss group moves to intercept (`ev=nomad.seek dist=` shrinking over 60 s).
   4. Defeat the boss. Devbridge may weaken it for test time, but **one run must be unassisted** (godmode off, no `nomad.kill_boss`), measured against the §Metrics 5–12 min target.
   5. The flag **`nomad_gate_unlocked`** is set, persisted across save/load, and mirrored in the `.fl` (grep the save file).
   6. Buy a Nomad-tier carrier at Gammu (Osiris look; bar and equipment dealer aboard: vision of the interior).
8. **Boss respawn.** `time.skip 7200` (4 in-game days) and re-enter Ew06: the boss is back; the unlock is not re-triggered.
9. **Carrier destruction.**
   1. Fill the hold with mixed goods.
   2. Force a heavy ambush and let the carrier die (`loss.kill` once, and once by real attackers on a **Stopped** carrier: `UnderAttack → Destroyed`).
   3. Salvage pods drop (count ≤ the engine cap; total contents equal everything aboard, ±0 units after collecting all).
   4. The hangar auto-launch hook fires (empty hangar before Wave 4).
   5. The carrier is gone from `carrier.list`, and its base is no longer dockable.
   6. Buy another at full price.
10. **Ambush frequency** (§Metrics):
    1. Host Monte Carlo per region class × rep class, within the bands and within 3σ of the analytic expectation;
    2. the `ambush.simulate` determinism check against the host on 4 routes (Li01→Li04, Br01→Br04, Bw03→Bw02, Ew03→Hi02);
    3. the qualitative natural-ambush result from step 1.

    These go into the report; the orchestrator files them in `state/gates/M2.md`.
11. **Fleet plus loss interplay.** With two carriers, one is destroyed and the other is unaffected (state, position, inventory).
12. **M1 regression subset.** §M1 steps 1–7 and 11 re-run as their regression-tagged scenarios.
13. Exploratory 20 min, then a **2-h soak**.

## §M3: Crew, voice and endgame (bot playthrough #3)

Run by **M3-PLAYTEST** (playbot). It starts only after W4-ESCALATION-DESIGN and all its W4-ESC-* packages (or W4-ESC-FALLBACK) are merged or degraded. Failures don't stop the playthrough.

1. **Crew wingmen.**
   1. A new carrier has 2 crew (3 at Nomad tier). Launch with the player; they follow.
   2. Formation change by hotkey (input).
   3. "Attack my target" makes them engage it (`ev=wing.engage`).
   4. Retreat order.
   5. One crew wingman is destroyed; it is replaced after 1 in-game day (`time.skip 1800`).
2. **Hiring at a bar.**
   1. Open the hiring panel by input in a Liberty bar and in a pirate base bar: candidate pools differ by faction and region (vision + `hire.candidates`).
   2. Hire 3 pilots of different skill tiers. Fees are deducted and wages accrue daily (`time.skip 3600`, with cash checks).
   3. Unpaid for 3 days ⇒ the pilot quits (`HARNESS_poor`).
3. **Permadeath.** A hired wingman destroyed is gone from the roster forever, including after reload.
4. **Bays.**
   1. A carrier with N bays launches at most N wingmen from itself. Extra roster members can still follow the player from a normal base launch (uncapped).
   2. Roster assignment: guard carrier X / stay docked / follow player.
5. **Escort duty.** Wingmen assigned to guard a carrier travelling Away freeze with its ambush and spawn to fight on arrival.
6. **Auto-launch at ambush.** Docked hired wingmen launch when the ambush starts, and are never lost with the carrier.
7. **Voice and LLM.**
   1. *Fake-client suite:* NDJSON replay tests pass (grammar orders, policy clamps, staleness guard).
   2. *Real smoke* (the only real-brain step, CONVENTIONS §13): the real sidecar is running and the real Claude CLI (Opus 5.5, low effort) handles one free-form order and one banter line. Assert:
      - the brain sandbox: cwd `/home/user/freelancer/carrier-brain-cwd`, an allowlisted env;
      - zero tools and zero MCP servers in the stream-json `system/init`;
      - measured latency.
   3. *PTT:* press numpad period (XTEST synthetic key on the input lane) with a recorded WAV injected as mic input (sidecar `--mic-file`); the order is applied.
   4. *Real microphone:* not testable unattended. Mark it SKIP with the reason; Adam verifies after the build.
8. **Escalation.** Every stage and lever defined in `docs/design/ESCALATION.md` is demonstrated by its scenarios (`esc.*`): e.g. helping the Liberty Rogues raises their influence, and they take a target base after the threshold. Persistence holds across reload. With W4-ESC-FALLBACK, its three pillars are demonstrated instead.
9. **Army scale.** Re-run the S-PERF curve with real wingmen under the `--perf` lock: 10/25/50/100/200 followers. Record the warn threshold; the warning appears once, and nothing is capped.
10. Exploratory 30 min, then a **3-h soak**.

## §F: Final gate

**Run by the orchestrator itself** (CONVENTIONS §10). Evidence agents may run individual steps and report. Only the orchestrator writes `state/`, publishes the release and sets `COMPLETE`. Every step runs on the **release-candidate SHA**.

1. `ci.sh --full` green on main at the release-candidate commit.
2. §M1, §M2 and §M3 checklists re-run in condensed form: a regression-tagged scenario per step, plus one full playbot pass of §M1 steps 2–7 by input.
3. **6-h cumulative soak** clean (§Soak).
4. §SaveCompat full matrix green, including uninstall relocation into an unmodded lane.
5. **Fresh install from scratch:**
   1. Delete `prefix-carrier` if a previous attempt exists.
   2. Re-create it with `ship/install.sh` from Adam's untouched play prefix (reflink clone while `tools/play_prefix_busy.sh` reports it idle).
   3. Launch through `/home/user/freelancer/play-carrier.sh` with the sidecar.
   4. Load `HARNESS_endgame_eagle` (copied in for the test, then removed) and buy a carrier.
   5. Quit cleanly. The launcher stops the sidecar on exit.
   6. Remove test saves from `prefix-carrier` afterwards.
6. Adam's original install still launches:
   - a `play.sh`-equivalent smoke on a **reflink clone** of `/home/user/freelancer/prefix` (never the original), the same as before the build;
   - **`tools/play_prefix_manifest.sh verify`** reports UNCHANGED against `local/play-prefix-manifest.sha256`, which was captured at build start. It is read-only hashing; nothing is written to the prefix.
7. **Public repo audit:**
   - `tools/check_public.py` on the tracked tree;
   - `--release <dir>` on the release package;
   - a scan of the whole history (`git log -p`) with the same patterns, including the local blocklist.

   The release contains only our own work: **source only by default**, plus built DLLs only if FLSDK licensing permits (CONVENTIONS §11).
8. **Completion** (orchestrator):
   1. publish `v1.0.0` on the exact SHA F tested;
   2. write `docs/BUILD_REPORT.md` (package F spec) and `state/gates/F.md`;
   3. restore the display;
   4. set `BUILD_STATUS: COMPLETE`;
   5. send a push notification (fallback: `state/NOTIFICATIONS.md`).
