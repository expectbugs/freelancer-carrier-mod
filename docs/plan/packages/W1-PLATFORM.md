# W1-PLATFORM: production platform layer (chosen track)

- **Type:** impl
- **Wave:** 1
- **Depends on:** ARCH-0 (sub-wave 1a, CONVENTIONS §8; runs in parallel with W1-HARNESS, W1-DATA, W1-WORLD, W1-CARRIER-DESIGN, W1-SIDECAR, W1-INVENTORY) → **Unblocks:** every package that touches the game (W1-CORE, W1-SPAWN, W1-UI and all of Waves 2–5)

## Goal

Turn the winning Phase-0 bake-off spike (`spikes/track_a/` or `spikes/track_b/`) into the production implementation of `src/contracts/platform.hpp`. Every other package then reaches the game only through this one stable, tested layer.

- It owns every raw hook, patch address and FLUF call.
- Nothing outside `src/game/platform/` may include FLUF headers or patch memory.
- When the layer is missing a capability, other packages report it to the orchestrator; they never work around it.

**This spec covers both tracks.** The orchestrator deletes the half that G0a did not choose, in the gate addendum.

**Testing before W1-HARNESS merges.** The YAML scenario runner (`harness/scenario.sh`) belongs to W1-HARNESS, a sibling in sub-wave 1a.

- Until it merges, run every in-game check below with the Phase-0 tooling: P0-HARNESS's `harness/run.sh` command-file mode, through the Phase-0 devbridge core.
- Write the YAML scenarios anyway (TESTING §Scenarios schema), and mark their runner form `DEFERRED(W1-HARNESS)`. The orchestrator re-runs them in the wave integration pass (CONVENTIONS §8).

## Requirements

- **REQ-W1-PLATFORM-1: Events.** Implement every event in the ARCH-0 platform contract, delivered on the game main thread with SP client id 1. At minimum:
  - base enter/exit (filter the main-menu intro bases `Intro1_Base`…`Intro99_Base` — R1 §2.3 gotcha);
  - launch requested (cancelable); launch complete;
  - undock transform override (`optional<Transform>`);
  - dock request (cancelable);
  - jump-in complete; system switch-out;
  - trade-lane enter/exit; target change;
  - ship and solar damage (hull/shield, with a modifiable amount); ship, solar and loot destroyed;
  - ship drop-all-cargo (cancelable); ship use-item (nanobot/battery);
  - goods buy/sell; cargo add/remove;
  - save written (file path), save loaded (file path); new game; SP server start/stop (reset state).

  This serves D-7.3, D-7.6, D-8.4 and D-14.1.
- **REQ-W1-PLATFORM-2: Two ticks.**
  - `OnFrame(realDt, paused)` comes from the frame function `Freelancer.exe` 0x5B2890. It runs in menus, docked and in space.
  - `OnGameTick(gameDt)` advances only while the SP server advances: server `ElapseTime` (vtable +0x30) or a `pub::GetRwTime` delta. It stops in the F1/Esc pause and runs while docked (R5 §1.3, VERIFIED disasm).
  - Never use wall-clock timers for game logic. This serves D-7.13 and D-1.5.
- **REQ-W1-PLATFORM-3: Launch control.**
  - Block or allow launch from both sides: the client check 0x4422B0, and server `PlayerLaunch` suppression or re-dock as a backstop.
  - Override the undock position (server.dll RVA 0x8420C `LaunchPosition`).
  - Deny docking at a chosen solar, with the vanilla "access denied" response.
- **REQ-W1-PLATFORM-4: Overlay UI surface.**
  - An ImGui context that draws over the game in windowed and fullscreen modes at 1280×720 through 4K, with the mouse cursor drawn on top.
  - Input routing so ImGui windows take mouse and keyboard when focused, and the game keeps them otherwise.
  - Hidden during cutscenes and loading screens; working while docked and in space.
- **REQ-W1-PLATFORM-5: Native controls.** A factory to create vanilla-style buttons in the base NavBar and receive their clicks, using the proven method from S-UI / the spike.
- **REQ-W1-PLATFORM-6: Key input.**
  - Register named keys, with press and release events, read through FL's key dispatch, so chat typing and menus suppress them.
  - The default copilot push-to-talk is numpad period, VK 110 (D-11.3).
  - Also expose raw `GetAsyncKeyState` polling for keys that FL's keymap doesn't know.
- **REQ-W1-PLATFORM-7: Lifecycle safety.**
  - Re-arm content.dll and server.dll hooks on every SP server start.
  - Survive SP⇄MP switches (MP is out of scope: just disable everything cleanly while MP is active).
  - Restore patches on shutdown without clobbering other plugins' patches.
- **REQ-W1-PLATFORM-8: Patch hygiene.** Every byte patch:
  - verifies the expected original bytes first (HDE bytes, see `FLDOCS/BinaryEdits.txt`);
  - logs `[carrier] platform: patch <name> @<module>+<rva> ok|SKIPPED(mismatch)`;
  - degrades the dependent feature instead of crashing on mismatch.
- **REQ-W1-PLATFORM-9: Deferred work.**
  - Provide `Defer(fn)`, which runs at the next `OnFrame` outside any engine callback.
  - Assert (debug log) when a spawn, destroy or relocate API is called from inside a server callback.
- **REQ-W1-PLATFORM-10: Address-space hygiene.** Report free virtual address space (VirtualQuery walk: total free and largest free block) via the API, for the devbridge `vmstat` command and W1-CORE's periodic `ev=mem`. The keys are exactly `va_free_mb` and `va_largest_free_mb` (CONVENTIONS §4). On Track A this includes the FLUF debug-strip / LAA decision from G0a.
- **REQ-W1-PLATFORM-11: Devbridge verbs** (CONVENTIONS §4). Use the stable Phase-0 devbridge core API (`DevbridgeRegister`); W1-CORE later promotes the core without changing the API or the wire format.
  - **Phase-0 verbs, now owned here:** `state`, `load`, `save`, `quit`, `shot`, `vmstat`, `perf`. Keep their output keys. `state` exposes a field-provider hook so other packages (W1-CORE first) can add fields.
  - **New `platform.*` verbs:**
    - `platform.caps`: the capability matrix, event × supported;
    - `platform.time`: `game_t=` plus `real_t=`;
    - `platform.launch_block on|off`;
    - `platform.undock_offset <x,y,z>|off`;
    - `platform.demo_window`, `platform.demo_button`: test widgets.
  - **Event lines** (`ev=<name>`, names per `docs/spec/events.md` from ARCH-0; these are the defaults if it is silent):
    - `ev=docked base=<nick>`, `ev=undocked base=<nick>`, `ev=launched`, `ev=launch.blocked reason=<r>`, `ev=jump.in system=<nick>`, `ev=system.out`
    - `ev=save path=<file>`, `ev=load path=<file>`, `ev=newgame`, `ev=sp.start`, `ev=sp.stop`
    - `ev=ui.click id=<id>`, `ev=key name=<n> state=down|up`

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§1 paths, §4 devbridge, §7 locks/XTEST input, §8 sub-waves, §14 ownership)
- `docs/plan/BUILD_PLAN.md` §2 and §4
- `docs/plan/DESIGN.md` §7, §8, §14, §15
- `docs/plan/TESTING.md` §Layers, §Lanes, §Devbridge, §CrashTriage
- `state/ENGINE_FACTS.md`: all platform entries
- `state/gates/G0a.md`: the bake-off results; why this track won and which checklist items were weak
- The winning spike: `spikes/track_a/` or `spikes/track_b/`, including its `NOTES.md`
- `src/contracts/platform.hpp`, plus `docs/spec/` written by ARCH-0 (especially `devbridge.md`, `events.md`, `ui.md`)
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R5-sp-architecture.md` §1 (process layout, call flow, pause, ticks), §2 (hooking server.dll from client DLLs; pitfalls: thread, re-entrancy, hook ownership), §3.4 (save/load hooks: `PlayerData::save` server RVA 0x6C800, `CharacterSelect` vtable +0x50, Console's 0x5AB231/0x6D275/0x6A177), §4 (NavBar, launch blocking, launch position), §8 (HDE hook-point table: avoid or chain)
  - `/home/user/freelancer/carrier-mod/local/research/R1-fluf.md` §2 (IServerImpl entries and offsets, what does NOT run in SP), §3 (UI: ImGui backend, `AbstractVanillaInterface`, `CreateButtonControl` 0x5A0C90), §3.4 (HDE graphics chain: dxwrapper d3d8to9 → ReShade d3d9 → DXVK), §5.4 (ABI must-match list), §9 (cheat sheet)
  - `/home/user/freelancer/carrier-mod/local/research/R2-engine-api.md` §9 (hook catalog), §2.1 (Discovery land redirect server+0x2c24c)
- Reference code:
  - `/home/user/freelancer/refs/FLUF/FLUF/Source/Server/FlufServer.cpp` and `Include/Server/Internal/IServerHook.hpp` (vtable offsets)
  - `/home/user/freelancer/refs/FLUF/FLUF/Source/Client/Ui/UiManager.cpp` (D3D8 hook)
  - `/home/user/freelancer/refs/FLUF/modules/ship_dealer_enhancements/Source/ShipDealerInterface.cpp` (NavBar button)
  - `/home/user/freelancer/refs/adoxa-plugins/console/console.cpp` (save hooks, chat)
  - `/home/user/freelancer/refs/FLSharp/src/*.cpp` (how HDE patches; avoid collisions)
  - `/home/user/freelancer/refs/Freelancer-Decomp/src/Server/IServerImpl.cpp` (behavior reference)
  - FLUF is AGPL; study it rather than copying. If verbatim code is ever needed, attribute it and keep the repo AGPL (it already is).

## Ownership

- **Owns:** `src/game/platform/` (including its `CMakeLists.txt`, `NOTES.md` and tests under `src/game/platform/tests/`), and `src/module/` (the DLL entry; ARCH-0 skeleton → this package, CONVENTIONS §14). Scenarios live in `harness/scenarios/platform/`.
- **Reads:** `spikes/`, `src/contracts/`, `docs/spec/`, refs, research.
- **Must not touch:** `src/contracts/` (frozen; propose diffs in the report), other `src/game/*`, `harness/` (except `harness/scenarios/platform/`), `toolchain/`, the root `CMakeLists.txt`/`cmake/` (discovery is by glob).

## Contract

- **Provides:** the full `src/contracts/platform.hpp` (events, ticks, launch/dock control, overlay, native controls, keys, defer, memory report). One `Platform& GetPlatform()` accessor and init/shutdown entry points called from `src/module/`.
- **Consumes:** FLUF (Track A) or raw Win32 plus FLSDK headers (Track B); the module entry from ARCH-0.

## Tasks

1. **Port the spike.** Re-read the spike and its `NOTES.md`. List every spike shortcut (hard-coded values, missing checks) and fix each one.
2. **Track A (FLUF) variant.** Implement `platform.hpp` over FLUF:
   1. A `FlufCombinedModule` subclass forwards `Before*/After*` server hooks and `OnClientFixedUpdate`/`OnClientUpdate` to platform events. Listed under `clientConfig.modules` (Freelancer.exe ignores `serverConfig.modules`, R1 §6).
   2. **Game tick:** FLUF has **no server tick in SP** (R1 §2.4, VERIFIED). Detour `IServerImpl::ElapseTime` (vtable +0x30) yourself, or sample `pub::GetRwTime` each `OnClientFixedUpdate` and emit the delta. FLUF's `Timer` uses wall clock (R5 §1.3); don't use it for game time.
   3. **UI:** FLUF ImGui (`OnUiRender`) and `HudManager` + `AbstractVanillaInterface` for NavBar buttons (R1 §3.2). Build with the ImGui defines in R1 §5.3 step 4 (`IMGUI_USE_WCHAR32`, `IMGUI_API=__declspec(dllimport)`, …).
   4. **Launch block:** `OnClientLaunchRequested` + `SuppressEventCall`. **Undock position:** `OnServerShipUndock`.
   5. **Save/load:** FLUF's `story_enhancements` save-flag hook covers the mirror flags only. The JSON save hook needs `PlayerData::save` (server RVA 0x6C800) or the S-BASE-proven method. Do not take a vtable slot FLUF owns: FLUF restores its saved `oldProc` on destruct (R5 §2).
3. **Track B (own DLL, HDE intact) variant.** Implement `platform.hpp` with our own hooks in a dacom `[Libraries]` DLL:
   1. **Server vtable:** patch the `Server` object's vtable (exported by server.dll) for exactly the events the contract needs. Offsets per `IServerHook.hpp` / FLHookSDK `FLCoreServer.h` (e.g. BaseEnter 0x08C, BaseExit 0x090, PlayerLaunch 0x0C0, LaunchComplete 0x0C4, JumpInComplete 0x0C8, SystemSwitchOutComplete 0x0BC, RequestEvent 0x0F0, GFGoodBuy 0x0B4, ReqAddItem 0x078, CharacterSelect 0x050, SaveGame 0x0E8, ElapseTime 0x030). Chain to the original. Re-patch on every SP server start.
   2. **Damage and destroy:** reimplement the engine hooks FLUF/FLHook use (`IEngine` damage entry, ship destroyed, LaunchPosition server+0x8420C), citing the FLHook-4.0 install table (`/home/user/freelancer/refs/FLHook-4.0-locked/source/HkInit.cpp`) for addresses. Verify the bytes against HDE.
   3. **Frame tick:** detour 0x5B2890. **Launch check:** 0x4422B0.
   4. **Overlay:** take over the bake-off's D3D hook through HDE's chain (`EXE/d3d8.dll` dxwrapper stub → d3d8to9 → `EXE/d3d9.dll` ReShade → DXVK). Draw ImGui last in the frame, and handle device reset.
   5. **Native controls:** use FL's control factory 0x59DB20 and `CreateButtonControl` 0x5A0C90 (addresses are facts; the implementation is ours).
   6. **Coexist with HDE plugins:** Console owns 0x5AB231/0x6D275/0x6A177; flplusplus detours `GetUserDataPath` and server 0x69012; FLSharp patches the hotspots listed in R5 §8.2. Chain where we share a site, never overwrite.
4. **Logging and patch verification** (REQ-8) for every patch site. Write `src/game/platform/PATCHES.md`, a table of every patch: site, original bytes, new bytes, purpose, who else touches it.
5. **Defer queue** and the callback-context assertion (REQ-9).
6. **Memory report** (REQ-10).
7. **Host-buildable unit tests** for pure helpers (event fan-out ordering, defer queue, key-state edge detection) under `src/game/platform/tests/` with fakes.
8. **In-game scenarios** (below), with an extended version of the spike's checklist.

## Acceptance (all automated; run them and attach evidence)

- **Host tests:**
  - `platform_defer_runs_next_frame`
  - `platform_event_fanout_order` (subscribers called in registration order, exceptions isolated per subscriber)
  - `platform_key_edges` (press and release edges from polled state)
- **Build:** `harness/ci.sh --quick` green (CI CLI per TESTING §CI; stages in `harness/ci.d/`). The import check passes (FLUF/common/server/dalib/msvcp140 family only, plus Win32).
- **In-game scenarios** (`harness/scenarios/platform/*.yaml`, TESTING §Scenarios schema; executed with Phase-0 `harness/run.sh` until W1-HARNESS merges, their YAML-runner form `DEFERRED(W1-HARNESS)`):
  1. `platform_events`: load fixture `HARNESS_endgame_eagle` (docked at Manhattan, CONVENTIONS §6). Undock, fly to the Li01→Li02 gate, jump, dock at Los Angeles, save, load.
     - Expect `ev=undocked`, `ev=launched`, `ev=jump.in system=li02`, `ev=docked base=li02_01_base`, `ev=save path=…`, `ev=load path=…`, in order.
     - No `Intro*_Base` events after the main menu.
  2. `platform_tick_pause`: in space, sample `platform.time` (`game_t=`) for 10 s, open the F1 menu for 10 s with the input lock (`lane: input`, Esc via XTEST, CONVENTIONS §7), then close it.
     - Game time advances about 10 s, not 20 s.
     - While docked, game time advances.
  3. `platform_launch_block`: docked. `platform.launch_block on`, then press Launch (input lock).
     - Still docked; `ev=launch.blocked`.
     - `platform.launch_block off` then Launch → `ev=launched`.
  4. `platform_undock_pos`: `platform.undock_offset 2000,0,0` (+2000 m on X of the base solar). Launch.
     - `HARNESS pos=` within 150 m of the target.
  5. `platform_overlay`: docked and in space. `platform.demo_window` → screenshot.
     - **Vision rubric:** "a framed window with the title 'Carrier platform demo' is visible over the game, readable, not clipped; mouse cursor drawn above it".
     - Run at 1280×720 and 2560×1440 (PerfOptions size).
  6. `platform_navbar`: docked at Manhattan. `platform.demo_button` → screenshot (vision: "an extra button appears in the base menu bar alongside the vanilla ones, no overlap"). Click it via the input lock → `ev=ui.click id=demo`.
  7. `platform_keys`: press numpad period (VK 110) with the input lock, using real XTEST input (`xdotool windowactivate --sync` then `xdotool key KP_Decimal`; never `--window`, CONVENTIONS §7) → `ev=key name=copilot_ptt state=down` then `state=up`. With the chat box open, no event.
  8. `platform_lifecycle`: load save A → main menu → load save B → new game. No duplicate events (counts per load equal 1) and no crash.
- **Soak:** 30 minutes of `platform_events` looped (via repeated `harness/run.sh` runs, or `harness/soak/soak.sh` if W1-HARNESS has merged). Criteria per TESTING §Soak: no crash, no new FLSpew ERROR lines versus the baseline, `va_free_mb` never below 300, and no `va` growth trend above 20 MB/h after warm-up.
- **Negative:** corrupt one expected-bytes table entry in a test build → the patch is SKIPPED, logged, and the game still boots.

## Engine facts to rely on / verify

- SP server runs on the main thread, once per frame; only the F1 menu pauses (R5 §1.3, VERIFIED disasm). Re-verify with the tick-pause scenario.
- FLUF `OnServerTick`, server timers and TaskScheduler never fire in SP (R1 §2.4, VERIFIED source).
- In SP, base-enter fires for intro bases (R1 §2.3).
- Whether FLUF's `OnServerCharacterSelect` fires in SP is contradictory in the research: R1 says FLServer-only, while R5 shows the vtable +0x50 is called on SP load. Settle it with `platform_lifecycle` and record it in ENGINE_FACTS.

## Pitfalls

- Hook-slot ownership conflicts: FLUF vtable restore; Console's save/load call patches; flplusplus and FLUF both detouring `GetUserDataPath` (R5 §8).
- Calling pub:: from the IPC worker thread is forbidden; marshal through Defer.
- A client DLL loads before content.dll exists. Don't touch content.dll until SP server start.
- ImGui under d3d8to9 + ReShade: device reset on resolution change; ReShade's own overlay hotkey (Home). The cursor is drawn by FL; FLUF NOPs 0x41F33E..0x41F6E9 to draw its own (R1 §3.1).
- Wine: `WINEDEBUG=-all` hides missing-DLL errors. Lanes use `+seh,+loaddll` (R4 pitfall 12).

## Fallbacks and degrade path

1. If the overlay can't be made reliable, keep native controls plus popups for menus (BUILD_PLAN §8 row 1). Expose `Platform::HasOverlay() == false` so UI packages switch to the native-only path.
2. If a specific event can't be hooked, mark it unsupported in the capability query (`Platform::Supports(Event)`). The owning feature package must then use a polling fallback (e.g. compare `pub::Player::GetBase` each frame).
3. If a native NavBar button fails, use a hotkey plus the overlay window ("Carrier menu" key, default F7).

## Report

Use the AGENT_BRIEF_TEMPLATE report format. Include `PATCHES.md`, a capability matrix (event × supported), and the memory baseline numbers.

## Gate-time addendum

The orchestrator fills:

- the chosen track (delete the other track's task block);
- the G0a evidence path;
- FLUF debug-strip / LAA decision;
- ARCH-0 contract file list;
- `ENGINE_FACTS` IDs for save/load and overlay;
- lanes;
- attempt number and prior notes;
- the commit trailer.
