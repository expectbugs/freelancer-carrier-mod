# W1-CORE: game clock, events, next-tick queue, persistence, config, logging, devbridge

- **Type:** impl
- **Wave:** 1
- **Depends on:** W1-PLATFORM, W1-HARNESS (sub-wave 1b, CONVENTIONS §8; parallel with W1-SPAWN and W1-UI) → **Unblocks:** all feature packages; W1-HARNESS (devbridge); every scenario

## Goal

Build the services every subsystem stands on:

- **A game clock** that matches Freelancer's own time: it runs while docked and stops in the F1 pause.
- **A typed event bus** and a **next-tick task queue**.
- **Versioned per-save JSON persistence** that survives every save, load, new game and delete path.
- **Config and logging.**
- **The devbridge**, the file-based command channel that lets the harness and the playbot drive and observe the game with no keyboard input.

If any of these is wrong, every later wave's tests lie. So it is built with exhaustive tests.

## Requirements

- **REQ-W1-CORE-1: Game clock** (`clock` contract). It provides:
  - game time in seconds (double), advanced only by `Platform::OnGameTick(gameDt)`;
  - in-game days (`universe.ini [Time] seconds_per_day = 1800` → one game day = 1800 game seconds; read the value from data, don't hardcode it);
  - timers and alarms keyed on game time.

  It must survive save/load: persist the game time and restore it. Serves D-7.13, D-11.5 (daily wages) and D-12.4 (respawn after 4 in-game days).
- **REQ-W1-CORE-2: Event bus** (`events` contract).
  - Typed, synchronous, single-threaded publish/subscribe on the main thread.
  - Re-entrancy safe: publishing inside a handler queues the event until after the current dispatch.
  - Subscription handles, and per-subscriber exception isolation (one bad handler logs and continues).
  - Re-publishes all platform events plus mod events defined in the contract.
- **REQ-W1-CORE-3: Next-tick queue.**
  - `Core::Defer(fn)` and `Core::After(gameSeconds, fn)`, built on `Platform::Defer` / `OnGameTick`.
  - Runs outside engine callbacks: the R2/R5 rule that spawns, destroys and ForceLand inside callbacks are deferred one tick.
- **REQ-W1-CORE-4: Persistence** (`persistence` contract). Serves D-14.1–D-14.3.
  - Subsystems register a serializer: name, schema version, `save() → json`, `load(json, version)` with migrations, and `reset()`.
  - On every save (manual, auto and mission saves), write `<save basename>.carrier.json` beside the `.fl` atomically: write a temp file, fsync, rename, keep the previous file as `.bak`.
  - Corrupt-file handling follows TESTING §SaveCompat, which wins (CONVENTIONS §3):
    - **Missing JSON** (a pre-mod save): call `reset()` on every subsystem, log `HARNESS persist=fresh`, and show a warning toast once.
    - **Unparseable JSON:** rename it to `*.carrier.json.bad-<ts>`, then load the last good `*.carrier.json.bak` (one rolling backup is kept). If that fails too, start with empty state. Log `HARNESS persist=recovered source=bak|empty` and notify the player once.
    - **A migration error in one subsystem:** use that subsystem's section from `.bak`, else reset just that subsystem. Never crash.
  - Delete the JSON when the game deletes the save.
  - Reset all subsystem state on new game, on SP server start/stop, and before every load.
- **REQ-W1-CORE-5: Mirror flags.** Persist a small set of critical flags (`nomad_gate_unlocked`, `campaign_complete`, `mod_version`; names per CONVENTIONS §2) **also** inside the `.fl` using the S-BASE-proven method (`[mPlayer]` extra keys via the content.dll writer/reader hook, or FLUF `story_enhancements`). On load, if the JSON is missing but mirrored flags exist, restore those flags. D-14.1.
- **REQ-W1-CORE-6: Config.**
  - `carrier_mod.yml` in the install's mod folder; defaults are written if missing.
  - Typed accessors; hot reload via the devbridge `config reload`.
  - Unknown keys are warned about, not fatal.
  - Holds every tunable later packages need (they register their sections).
- **REQ-W1-CORE-7: Logging.**
  - `[carrier] <subsystem>: …` lines to the mod log file (`carrier.log` in the user-data dir, or `SAVE/` when `save_in_directory`), rotated per session, plus FLSpew passthrough where available.
  - Levels: trace, debug, info, warn, error.
  - `HARNESS key=value …` lines go to the devbridge log (REQ-8) **and** the mod log.
- **REQ-W1-CORE-8: Devbridge** (TESTING §Devbridge and `docs/spec/devbridge.md` from ARCH-0 are the authority for the exact grammar).
  - **Wire protocol (canonical, unchanged from Phase 0):** this package *promotes* the Phase-0 devbridge core (`harness/devbridge/devbridge_core.*`, protocol in `harness/devbridge/PROTOCOL.md`, copied to `docs/spec/devbridge.md` by ARCH-0, P0-HARNESS REQ-12) into production code. The harness, the Python client `harness/devbridge.py` and every scenario already speak it, so **do not change the wire format**:
    - It is enabled only when `<exe dir>\devbridge.enabled` exists, and is shipped absent in `prefix-carrier`.
    - Directory `<exe dir>\..\SAVE\devbridge\`. The harness writes `cmd-<seq>.txt` files, each holding one line `<id> <verb> <args…>`. The game polls every 10 frames on the main thread, processes files in seq order, deletes them, and remembers the last seq, because Wine delete can lag (R4 §B10).
    - Output is the append-only `log.txt`: `HARNESS t=<game s> wall=<unix ms> <key=value…>`. Every command emits `HARNESS ack id=<id> ok=1|0 [err="…"]` plus its data lines.
  - **Verb ownership follows CONVENTIONS §4.**
    - The core built-ins `ping`, `echo`, `sleep_frames` and `seq` move with the core.
    - `state`, `load`, `save`, `quit`, `shot`, `vmstat` and `perf` stay owned by W1-PLATFORM. Don't duplicate them. Add `state` fields (room, pos, shield, docked, in_cruise, rank, mission, fps) through the platform's state-field provider hook.
  - **Core verbs (this package):**
    - `wait_in_space`, `wait_docked [base]`, `wait_menu`, `wait_event ev=<e> [k=v…]`: all with timeouts.
    - `pause on|off`, `time`.
    - `time.skip <game s>`: advances the mod's own clock (scheduler, travel, wages, respawn timers) without waiting. Emits `ev=time skipped=`.
    - `time.scale <x>`: answers `err=unsupported` unless an ENGINE_FACT proves ElapseTime scaling.
    - `config get|set|reload`, `log level`, `log <text>` (marker line).
    - `assert <expr>`, `rng.seed <n>`, `help`.
    - `perf.sample` / `mem.sample`: an immediate `ev=perf` / `ev=mem`.
    - `debug crash`: a deliberate access violation, for triage tests.
    - `debug hang <s>`: blocks the main thread, for hang-detection tests. This is additive; ARCH-1 records it in `docs/spec/devbridge.md`.
  - **Test-only cheats** (never in normal play): `base <nick>`, `system <nick> [x,y,z]`, `pos x,y,z`, `rep <faction> <v>`, `cash <n|+n|-n>`, `give <good> <n>`, `take <good> <n>`, `equip <good> <hp>`, `godmode on|off`, `launch` (honours launch blocks; prints `blocked=1 reason=` if blocked).
  - **Periodic events** (CONVENTIONS §4):
    - `ev=hb` every 10 s of wall time while the game loop runs;
    - `ev=perf fps_avg= fps_p1= ships= window_s=10` every 10 s;
    - `ev=mem va_free_mb= va_largest_free_mb= heap_mb=` every 60 s.
  - **Extension API:** other packages register verbs with help text through the same `DevbridgeRegister` API as Phase 0. `help` lists them all.
- **REQ-W1-CORE-9: Campaign-complete detection** (D-13.1). On load and on mission-state change, decide `campaign_complete`:
  - the save's `[StoryInfo] Mission = Mission_13` and `MissionNum` ≥ 41/42 and the M13 state is succeeded;
  - **or** HDE Open-SP is detected (newplayer and m13 files are the `m13_opensp_*` variant);
  - **or** our mirrored flag is set.

  Then set the persistent flag. Expose `IsCampaignComplete()`.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§1 paths, §2 flags, §3 JSON library, §4 devbridge, §8 sub-waves, §13 test profile)
- `docs/plan/DESIGN.md` §1, §7 (D-7.13), §11.5, §12.4, §13.1, §14
- `docs/plan/TESTING.md` §Devbridge, §Fixtures, §Scenarios, §SaveCompat, §Layers
- `state/ENGINE_FACTS.md`: save/load hooks, pause, game time
- `src/contracts/{platform,clock,events,persistence}.hpp`, `docs/spec/devbridge.md`, `docs/spec/persistence.md`
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R5-sp-architecture.md` §1.3 (tick and pause; `pub::GetRwTime`; `IServerImpl::ElapseTime` accumulates into server VA 0x6D8FB28), §3 (save system: location, plain-text format, `[Player]`/`[mPlayer]`/`[StoryInfo]` fields; unknown keys dropped; options; hook sites), §6 (campaign end: M13 `the_end_end`; adoxa PostStoryDiff MissionNum 42; HDE Open-SP)
  - `/home/user/freelancer/carrier-mod/local/research/R3-game-data.md` §7 (story/campaign state, Open-SP file swaps)
  - `/home/user/freelancer/carrier-mod/local/research/R4-lore-and-testloop.md` §B6 ("Getting from launch to a known game state"), §B10 (devbridge design sketch, fltest.sh), §A1.4 item 5 (save crash causes)
  - `/home/user/freelancer/carrier-mod/local/research/R1-fluf.md` §4 (`story_enhancements` save flags: `SetCustomSaveFlag`, never cleared between loads, so we must clear them)
- Reference: `/home/user/freelancer/refs/adoxa-plugins/console/console.cpp` (sidecar save file `.fls`, save/delete/load hooks) and `/home/user/freelancer/refs/FLUF/modules/story_enhancements/Source/StoryEnhancements.cpp` (mPlayer keys)

## Ownership

- **Owns:**
  - `src/logic/core/`: engine-free clock math, event bus, scheduler, JSON schema/migration helpers, devbridge command parser, with `tests/`.
  - `src/game/core/`: adapters to platform, file I/O, config, logger.
  - `src/game/devbridge/` and `harness/devbridge/` (the Phase-0 core and `PROTOCOL.md` move here; the wire format is unchanged).
  - Scenarios in `harness/scenarios/core/` (or `src/game/core/scenarios/`; both are discovered).
- **Reads:** `src/contracts/`, `docs/spec/`, `src/game/platform/` (API only).
- **Must not touch:** contracts, platform internals, harness.

## Contract

- **Provides:** `clock.hpp`, `events.hpp`, `persistence.hpp` implementations; `Core` services (Defer/After, Config, Log); the devbridge registry API (`RegisterCommand(name, help, handler)`).
- **Consumes:** `platform.hpp` (ticks, save/load events, memory report, screenshot hook).

## Tasks

1. **Engine-free core** in `src/logic/core/` with doctest tests:
   - clock (advance, day rollover, alarms, persistence round-trip);
   - event bus (ordering, re-entrancy, exception isolation);
   - scheduler;
   - a JSON helper on nlohmann/json (single header from `$FLMOD_VENDOR`; CONVENTIONS §3), on both tracks;
   - devbridge grammar parser.
2. **Game adapters:** wire the clock to `OnGameTick`, the bus to platform events, persistence to save/load/new-game/delete events.
3. **Atomic JSON writer:** temp file, flush, `MoveFileExW(MOVEFILE_REPLACE_EXISTING)`, keep `.bak`. Under Wine, rename is atomic on the same filesystem (R6 §2.1, UNVERIFIED); test it.
4. **Mirror flags** via the S-BASE-proven mechanism.
5. **Devbridge** file loop, built-in commands, test cheats and `help`.
6. **Campaign-complete detector** and fixtures for the three cases.
7. **Config** with defaults and hot reload.
8. **Scenarios** in the TESTING §Scenarios schema, using the `HARNESS_*` fixtures (CONVENTIONS §6). W1-HARNESS (already merged, since it's your dependency) owns the runner and the fixture generator. Coordinate through `docs/spec/devbridge.md`.

## Acceptance

- **Host tests** (`src/logic/core/tests/`):
  - `clock_pause_semantics`
  - `clock_day_rollover_1800s`
  - `clock_persist_roundtrip`
  - `events_reentrant_publish_queued`
  - `events_handler_throw_isolated`
  - `scheduler_after_order`
  - `persist_migration_v1_to_v2` (a dummy subsystem)
  - `persist_corrupt_json_falls_back_per_subsystem`
  - `devbridge_parse_quoting`
  - `campaign_detector_cases` (story-incomplete, Mission_13 succeeded, OSP)
- **In-game scenarios:**
  1. `core_devbridge_smoke`: load `HARNESS_endgame_eagle` → `ping` → ack ok=1; `state` prints every field; `vmstat` prints `va_free_mb= va_largest_free_mb=`; `ev=hb` lines arrive every 10 s; `quit` → clean process exit (no dump). `debug crash` in a separate run is detected as CRASH by the harness.
  2. `core_clock`: in space, `time`, wait 30 s real, `time` → delta of 30 s ±2. Pause 15 s → no advance. Docked 30 s → +30.
  3. `core_persist_roundtrip`: a test subsystem stores a counter. Increment, `save P1`, increment, `load P1` → counter equals the saved value; the JSON file exists beside the `.fl`; `.bak` is created on the second save.
  4. `core_persist_autosave`: trigger an autosave (dock at a base with autosave, or a mission save) → JSON written (proves the autosave path goes through the hook; R5 §3.4 marks this UNVERIFIED).
  5. `core_presave_mod`: load `HARNESS_new_story` (a vanilla save with no JSON) → `HARNESS persist=fresh`, no errors.
  6. `core_corrupt_json`: replace the JSON with garbage → load → a `.bad-<ts>` file exists; `HARNESS persist=recovered source=bak` (or `empty` when no `.bak` exists); player notified once; game fine.
  7. `core_delete_save`: delete the save via the game's load menu (input lock) or a devbridge-driven delete → the JSON is removed.
  8. `core_mirror_flags`: set `nomad_gate_unlocked`, save, delete the JSON and its `.bak`, load → the flag is restored from the `.fl`.
  9. `core_new_game_resets`: with state set, start a New Game (input lock) → all subsystems are reset (`HARNESS persist=reset`).
- **Soak:** 30 minutes alternating save/load every 60 s plus random devbridge commands. No crash, no JSON corruption, file count stable.

## Engine facts to rely on / verify

- **Save path:** `GetUserDataPath()`, overridden by flplusplus (`save_in_directory=true` on lanes, so `<HDE>/SAVE/Accts/SinglePlayer/`).
- **Save chokepoint:** `PlayerData::save` (server RVA 0x6C800) covers manual and mission saves. Autosave via 0x6C430 is UNVERIFIED (R5 §3.4); scenario 4 must settle it.
- Unknown `.fl` keys are not preserved, so mirror flags must be re-written on every save (R5 §3.2).

## Pitfalls

- flplusplus regenerates `Restart.fl` every launch. Never store fixtures there.
- Wine file deletion lag on `cmd-<seq>.txt` (R4 §A5): the core remembers the last processed seq.
- Never block the main thread on disk: the JSON is small, but writing must be bounded and must not wait on anything external.
- The FLUF `story_enhancements` flag map is never cleared between loads (R1 §4). Clear it ourselves before each load.

## Fallbacks and degrade path

1. If the autosave doesn't pass through the save hook, also write the JSON on every base enter and every 5 game minutes to `<save>.carrier.json` for the current autosave slot name. Document the gap.
2. If mirror flags inside the `.fl` can't be written, use a hidden-faction reputation flag store (R5 §3.3 option 3) for the 2–3 booleans.
3. If file-based devbridge latency is too high (over 500 ms), add a TCP devbridge on 127.0.0.1 alongside it, keeping the file mode.

## Report

Use the standard report. Include the devbridge command table (name, args, output line format) and the persistence file layout.

## Gate-time addendum

The orchestrator fills:

- the track;
- the ENGINE_FACTS IDs for save, load, autosave and mirror flags (S-BASE);
- the JSON library choice (ARCH-0);
- the userdata path on lanes;
- the contract file list;
- lanes;
- attempt notes;
- the commit trailer.
