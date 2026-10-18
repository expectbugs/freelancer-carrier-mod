# P0-TRACK-A: Platform bake-off, Track A (FLUF on HDE minus forbidden DLLs)

- **Type:** spike
- **Wave:** Phase 0 bake-off
- **Depends on:** P0-TOOLCHAIN, P0-HARNESS → **Unblocks:** G0a. If A is chosen: S-* spikes, W1-PLATFORM.

## Goal

Prove or disprove, with automated in-game evidence, that a FLUF module can deliver every platform capability the mod needs on Adam's HD Edition under Wine. Run the 13-item checklist from BUILD_PLAN §4. Leave behind a reusable static library, `spike_platform_a`, implementing the common spike API (below), so the S-* spikes can build on it if A wins.

The same checklist runs in P0-TRACK-B. G0a compares the two. Be rigorous and honest: a fair comparison matters more than a win.

## Requirements

- **REQ-P0-TRACK-A-1:** Build `spike_a.dll` as a FLUF combined module (`FlufCombinedModule`) using P0-TOOLCHAIN's `flmod_fluf_module()`. It covers every ABI must-match item in R1 §5.3–5.4.
  - Deploy into a lane cloned from `prefix-dev-base-A` with `harness/deploy.sh --fluf-module spike_a.dll`.
  - It links a static lib `spike_platform_a` (in `spikes/track_a/platform/`) that implements **exactly** the common API header below, plus the devbridge core from `harness/devbridge/`.
- **REQ-P0-TRACK-A-2: common spike API.** File `spikes/track_a/include/spike_platform.hpp`. The content must be identical in Track B; both specs carry this text verbatim. Additions are allowed only as clearly marked track-local extensions in a separate header.

```cpp
#pragma once
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>
namespace sp {
struct Vec3 { float x, y, z; };
struct Mat3 { float m[3][3]; };                 // same layout as FL Matrix
struct Transform { Vec3 pos; Mat3 rot; };
struct Cmd { std::string id, verb; std::vector<std::string> args; };
struct CmdResult { bool ok = true; std::string kv; std::string err; };

// devbridge / logging (main thread)
void Harness(const std::string& kv);                                   // emits "HARNESS t=.. wall=.. <kv>"
void RegisterCommand(const std::string& verb, std::function<CmdResult(const Cmd&)> fn);
double GameSeconds();                                                  // server game time (pub::GetRwTime)
bool Paused();                                                         // F1/Esc pause (Freelancer.exe IsPaused 0x42D740)
void Defer(std::function<void()> fn);                                  // run on next tick, main thread

// per-frame tick, main thread; dtGame = delta of GameSeconds (0 while paused)
void OnTick(std::function<void(double dtGame, bool paused)> fn);

// server events (single player: client id is always 1)
void OnBaseEnter(std::function<void(uint32_t baseId)> fn);
void OnBaseExit(std::function<void(uint32_t baseId)> fn);
void OnLaunchComplete(std::function<void(uint32_t baseId, uint32_t shipId)> fn);
void OnJumpInComplete(std::function<void(uint32_t systemId, uint32_t shipId)> fn);
void OnSystemSwitchOut(std::function<void(uint32_t shipId)> fn);
void OnDockRequest(std::function<bool(uint32_t requesterShip, uint32_t targetObj)> fn); // return false = deny
void OnObjectDestroyed(std::function<void(uint32_t objId, uint32_t killerId)> fn);      // ships and solars
void OnSaveWritten(std::function<void(const std::string& saveFileAbsPath)> fn);         // after FL wrote the .fl
void OnSaveLoaded(std::function<void(const std::string& saveFileAbsPath)> fn);          // after a save was loaded

// control
void SetLaunchBlocked(bool blocked);                                   // client refusal + server backstop
void SetUndockOverride(std::function<std::optional<Transform>(uint32_t shipId, uint32_t baseId)> fn);

// UI
void OnOverlay(std::function<void()> fn);                              // Dear ImGui calls valid only inside
bool AddBaseNavButton(const std::string& nick, const std::string& iconMesh,
                      const std::string& tooltip, std::function<void()> onClick);

// queries
uint32_t PlayerShip();   // 0 if docked/none
uint32_t PlayerSystem();
uint32_t PlayerBase();   // 0 if in space
}
```

- **REQ-P0-TRACK-A-3: implementation mapping** (all VERIFIED in FLUF source unless marked; R1 §1.3, §2, §3, §9).
  - **Ticks.** `OnTick` maps to `OnClientUpdate(f32)` and `OnClientFixedUpdate(1/60, gamePaused)`.
    - `OnServerTick` **never fires in single player** (R1 §2.4, VERIFIED `Fluf.cpp:782-801`).
    - `GameSeconds()` = `pub::GetRwTime(double&)` (server RVA 0x7E8B0). It advances while docked and stops only in the F1 menu (R5 §1.3, VERIFIED disassembly).
  - **Base events.** `OnBaseEnter`/`OnBaseExit` map to `AfterServerBaseEnter` / `AfterServerBaseExit`. **Filter the intro bases `Intro1_Base`…`Intro99_Base`, which fire at the main menu** (R1 §2.3, VERIFIED `ServerHook/Base.cpp:13-38`).
  - **Space events.** `OnLaunchComplete` maps to `OnServerPlayerLaunchComplete`, `OnJumpInComplete` to `OnServerJumpInComplete`, and `OnSystemSwitchOut` to `OnServerSystemSwitchOutComplete`.
  - **Docking.** `OnDockRequest` maps to `BeforeServerRequestDock` + `SuppressEventCall(SuppressionType::SuppressFunctionCall)` when denying; FLUF sends RequestCancel.
  - **Destruction.** `OnObjectDestroyed` maps to `OnServerShipDestroy` / `OnServerSolarDestroy`.
  - **Saves.** `OnSaveWritten`/`OnSaveLoaded`: FLUF has no SP save hook in its API. Implement our own:
    - Detour the entry of **`PlayerData::save` at server.dll RVA 0x6C800** (thiscall `(const CHARACTER_ID&, const wchar_t* desc, uint ids)`). Call the original, then emit `OnSaveWritten`. The path is GetUserDataPath + `\Accts\SinglePlayer\` + `CHARACTER_ID.charFilename`, a char[512] at offset 0 (R5 §3.4, VERIFIED disassembly).
    - adoxa Console patches **inside** this function at +0xA75 (0x6D275), not at the entry, so the two coexist. Console stays loaded on A: it's not on FLUF's forbidden list.
    - For load, use `BeforeServerCharacterSelect`/`After…` if FLUF's `IServerImpl` hook for `CharacterSelect` (vtable +0x50) fires in SP. R1 §2.4 says `OnServerCharacterSelect` is FLServer-only, but the vtable hook entry `CharacterSelect` (0x050) is in FLUF's patched table; verify. Otherwise use the FLUF `story_enhancements` read path, or our own detour.
    - Exe 0x5AB231 is owned by Console; chain only if unavoidable.
  - **Launch control.**
    - `SetLaunchBlocked` maps to `OnClientLaunchRequested()` + `SuppressEventCall(SuppressAll)` on the client (hook at 0x4422B0; R1 §3.3, R5 §4.3), plus `BeforeServerPlayerLaunch` suppression as the server backstop ("forcibly redocked", R5 §4.3).
    - `SetUndockOverride` maps to `OnServerShipUndock(ShipId, const CShip&, const Transform&, int dock) → std::optional<Transform>`, which patches server.dll+0x8420C.
  - **Overlay.** `OnOverlay` maps to `OnUiRender()`. Use FLUF's exported ImGui via dllimport, with the macros from R1 §5.4. Never compile your own ImGui on A.
  - **Native button.** `AddBaseNavButton` uses a subclass of `AbstractVanillaInterface` that catches the `"NavBar"` control in `OnUpdate`, creates a child with `CreateButtonControl` (0x5A0C90), handles `OnExecuteButton` by name, and nulls pointers in `OnTerminate`. Register it via `FlufClient::GetHudManager()->RegisterHud(...)`. The pattern comes from `refs/FLUF/modules/ship_dealer_enhancements/Source/ShipDealerInterface.cpp`. Position and icon are found empirically (R1 §3.2, UNVERIFIED).
  - **Queries.** `PlayerShip`/`PlayerSystem`/`PlayerBase` map to `FlufClient::GetPlayerShipId()`/`GetPlayerSystemId()`/`GetPlayerBaseId()`.
  - **Deferral.** `Defer` uses a queue drained in `OnTick`. Use it for any spawn, destroy or ForceLand triggered inside a server callback (R5 §2 re-entrancy pitfall).
- **REQ-P0-TRACK-A-4: devbridge verbs.** Required by the harness, on top of the core verbs, with semantics identical in Track B:
  - `state`, `load <pattern>` (A: FLUF debugger's `quick_load`-style path, or the exe `LoadGame` 0x5b2c70 with a `CHARACTER_ID`, per adoxa console `cmdLoad`, VERIFIED source), `save <desc>` (`Players.playerdata->save(cid, desc, 0)`, per adoxa `cmdSave`), `quit`, `shot <name>`, `vmstat`, `perf <s>`;
  - spike helpers:
    - `forceland <baseNick>` → `pub::Player::ForceLand(1, CreateID(nick))`, in space only; R2 fact 6;
    - `launch` → programmatic launch. Study adoxa console `cmdLaunch` (`refs/adoxa-plugins/console/console.cpp:1633`): it jumps into Freelancer.exe at 0x440f94 inside the navbar launch routine. Reimplement equivalently, or press the Launch control via FLUF vanilla UI `Execute()`;
    - `instantdock <objNick>` → `pub::SpaceObj::InstantDock(ship, CreateID(nick), 1)`. On a jump gate or hole it completes the dock, which jumps (R2 §3, VERIFIED-decomp);
    - `block_launch 0|1`, `undock_offset <dx> <dy> <dz>`, `deny_dock <objNick|*> 0|1`, `nav_button add|remove`, `overlay show|hide`.
- **REQ-P0-TRACK-A-5: the checklist** (BUILD_PLAN §4). Each item is an automated scenario in `spikes/track_a/scenarios/*.yaml`, run with `harness/run.sh`, with evidence in the run dir.
  1. **Boot:** lane boots to the main menu. `state=menu`; fluf.log shows FLUF loaded plus the modules (`debugger`, `delay_display`, `story_factions`, `story_enhancements`, `FLUF.CrashWalker`, `spike_a`). No "not allowed to load alongside FLUF" MessageBox (screenshot plus `xdotool search --name`).
  2. **Load:** `--save-file=HARNESS_endgame_eagle` → `state=docked base=li01_01_base`.
  3. **Hooks fire in SP**, each producing a HARNESS event line:
     - `launch` → `ev=base_exit base=…` and `ev=launch_complete`;
     - `forceland li01_01_base` → `ev=base_enter`;
     - launch again, then `instantdock Li01_to_Li02` → `ev=system_switch_out` and `ev=jumpin system=li02`.
  4. **Game-time tick:** `GameSeconds()` advances while docked and in space; freezes while the F1 menu is open; `paused=1` is reported. Evidence: three `tick` samples.
     - Open the menu with real XTEST input under the input lock: `xdotool windowactivate --sync <wid>; xdotool key F1`, then `key Escape`. **Never `xdotool key --window`**, whose XSendEvent events the game doesn't see (CONVENTIONS §7).
  5. **Overlay:** an ImGui window with text, a button and a progress bar renders while docked. Screenshot plus a **vision check** (TESTING §Vision): the rubric "a window titled 'Spike A' with a button 'Click me' and a progress bar is visible and legible". Clicking the button (xdotool under the input lock) produces `ev=overlay_click`.
  6. **Native NavBar button:** appears beside the vanilla room buttons at a base (screenshot plus vision check); clicking it produces `ev=nav_click`. Test at Manhattan (`Li01_01_Base`) and at a battleship base (`Li01_03_Base` Missouri), whose navbar may differ.
  7. **Launch block:** `block_launch 1`, then try to launch (devbridge `launch` **and** a real Launch click under the input lock) → still docked; a message shown. `block_launch 0` → launch works.
  8. **Undock override:** `undock_offset 0 500 2000` → after launch the player is within 50 m of the base pos + offset (devbridge `state` reports pos).
  9. **Save hook writes JSON, load hook reads it:**
     - `save HARNESS_s9` → `OnSaveWritten` writes `<save>.carrier.json` containing `{"spike":"a","n":<counter>}`;
     - quit, relaunch with `--save-file=HARNESS_s9` → `OnSaveLoaded` reads it → `ev=json_loaded n=<same>`.
  10. **60-minute soak:** a scripted loop of launch, fly via `instantdock` to the gate, jump, forceland at a base in the new system, save, load, repeat. Crash-free and no hang (verdict PASS); report the number of cycles.
  11. **No new FLSpew ERROR lines** versus `harness/baseline/spew_allow_A.txt` across all of items 1–10.
  12. **Address-space headroom:** run the shared scenario `harness/scenarios/bakeoff_vmstat.yaml` (written identically by both tracks; whichever lands first commits it, and the other reuses it verbatim):
      - load `HARNESS_endgame_eagle`;
      - launch, `instantdock Li01_to_Li02`, fly about 5 km toward Los Angeles;
      - `vmstat`.

      PASS if **`va_largest_free_mb ≥ 300`** (CONVENTIONS §4 key names). The scenario's `verdict.json` carries the numbers, so G0a compares tracks on identical evidence.
      - Measure with: FLUF as shipped; FLUF with the LAA flag set on `Freelancer.exe` (header bit 0x0020; byte-verified, lane copy only); FLUF debug-stripped (`llvm-strip --strip-debug` copies). Report all three.
      - Choose the mitigation for baseline A. If it changes `prefix-dev-base-A`, report the exact steps; P0-HARNESS's `baseline.sh` gets a follow-up.
  13. **HDE fixes lost:** the evidence is the file `spikes/track_a/LOST_FEATURES.md` (no game run; its "verdict" is the table itself). List every feature of the removed DLLs (`jflp.dll`, `FLSharp.dll` + `FLSharp.ini` options, `DelayDisplay.dll`, `MP3codec.dll`, `storyfactions.dll`, `callsign.dll`). Mark each "replaced by FLUF (module/patch)", "lost (impact: …)" or "unknown". Sources:
      - `$HDE/EXE/FLSharp.ini`; `refs/FLSharp/README*` and `src/*`;
      - HDE `JFLP/` docs and `FLDOCS/`; `refs/freelancer-hd-edition/CHANGELOG.md`;
      - FLUF `docs/content/user/core-features.mdx` and `modules/*`.

      Expected highlights (R1 §3.4): FLSharp `save_crash_fix`, `alchemy_crash_fix`, `dynamic_solar_infocards`, `waypoint_fixes`, `better_resolutions`, `flight_controls_fix`; JFLP widescreen and fixes.
- **REQ-P0-TRACK-A-6: results file.** Write `spikes/track_a/RESULTS.md`: a table of items 1–13 with PASS/FAIL/PARTIAL, evidence paths (run dirs under `$FLMOD_TESTRUNS`, absolute), notes, and timings (e.g. cycles completed in the soak).
  - Item 13 is scored PASS if `LOST_FEATURES.md` is complete. Its *content* (what's lost) is weighed by G0a, not the PASS.
  - G0a reads this file and your saved report (`state/reports/P0-TRACK-A-a<n>.md`, saved by the orchestrator).

## Context pack

- `docs/plan/CONVENTIONS.md` (authoritative: §1 paths, §4 devbridge names, §5 run output, §6 fixtures, §7 locks/input, §15 wine)
- `docs/plan/BUILD_PLAN.md` §4 (the checklist and decision rule); `docs/plan/TESTING.md` §Lanes, §Devbridge, §Scenarios, §Vision, §Soak, §CrashTriage
- `$FLMOD_RESEARCH/R1-fluf.md`: **all**, especially §1.2–1.4, §2 (SP mechanism, hook list, what doesn't run in SP), §3 (UI), §4 (facilities), §6 (install), §8 (gaps), §9 (cheat sheet)
- `$FLMOD_RESEARCH/R5-sp-architecture.md` §1–4 (SP flow, pause, tick options, save hooks, launch control, docking UI), §8 (HDE hook map; avoid collisions)
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §B6–B7, §B10
- `/home/user/freelancer/refs/FLUF/` source: `FLUF/Include/Server/FlufServerModule.hpp`, `FLUF/Include/Client/*`, `modules/ship_dealer_enhancements`, `modules/debugger`, `modules/story_enhancements`, `modules/load_limit` (launch refusal example), `modules/patch_notes` (ImGui window example)
- `/home/user/freelancer/refs/adoxa-plugins/console/console.cpp` (`cmdLaunch`, `cmdSave`, `cmdLoad`, `LoadGame` 0x5b2c70)
- The P0-TOOLCHAIN and P0-HARNESS deliverables (`toolchain/README.md`, `harness/README.md`, `harness/devbridge/PROTOCOL.md`)

## Ownership

- **Owns:** `spikes/track_a/` (platform lib, spike module, scenarios, RESULTS.md, LOST_FEATURES.md, NOTES.md), plus `harness/scenarios/bakeoff_vmstat.yaml`, which is shared with P0-TRACK-B (whoever commits first; the content must be identical).
- **Reads:** everything.
- **Must not touch:** `harness/` (propose fixes via the report), `toolchain/`, `prefix-dev-base-*` (lanes only), `docs/plan/`, `state/`.

## Contract

- **Provides:** `spike_platform_a` (static lib + the header above); `RESULTS.md`; the address-space mitigation recommendation.
- **Consumes:** P0-HARNESS lanes, deploy, run and devbridge core; P0-TOOLCHAIN presets.

## Tasks

1. Build an empty `spike_a` module and deploy it. Item 1.
2. Implement the platform lib incrementally, item by item. Commit after each item passes.
3. Measure and mitigate address space (item 12) early. It can invalidate everything else.
4. Run the soak last, after all items pass individually.
5. Write `RESULTS.md` and the lost-features list.

## Acceptance

`RESULTS.md` is complete, and each item has a scenario run with `verdict.json` and evidence. "Complete" means honest results, not all PASS. Reviewers re-run items 2, 3, 7, 8 and 9.

## Engine facts to rely on / verify

- **VERIFIED:**
  - FLUF event hooks fire in SP with client 1;
  - no `OnServerTick` in SP;
  - the intro-base BaseEnter quirk;
  - the forbidden list;
  - FLUF ImGui is exported and must be dllimported;
  - the builder's solar packet is MP-only (not needed here).
- **UNVERIFIED, settled here:**
  - the D3D8 ImGui hook under dxwrapper→ReShade→DXVK;
  - native NavBar button placement;
  - CharacterSelect hook in SP;
  - `--save-file` with FL's own switch parser;
  - address-space headroom.

## Pitfalls

- FLUF restores its saved vtable entries when it is destroyed (SP⇄MP). Never patch a `Server` vtable slot that FLUF owns; use FLUF events (R5 §2).
- In SP, spawning or destroying from inside server callbacks can re-enter: use `Defer`.
- `FLUF.yml` `clientConfig.modules` is an unordered set; don't rely on module load order.
- A minor-version mismatch between headers and FLUF.dll only warns. Build against the exact pinned package.
- FLUF replaces FL's cursor with an ImGui one (R1 §3.1). Note any visual issues in screenshots.

## Fallbacks and degrade path

- **Overlay doesn't render:**
  1. Try FLUF stable 2.0.
  2. Try a native-controls-only UI (`FlTextControl` + buttons).
  3. Report PARTIAL on item 5.
- **The CharacterSelect hook doesn't fire:** use the `story_enhancements` content.dll read path (`content.dll+0xA8497`) or exe `LoadGame` instrumentation.
- **The nightly is unstable:** repeat the failing items on stable 2.0 and report both.

## Report

AGENT_BRIEF_TEMPLATE format. Include the `RESULTS.md` content inline (the table).

## Gate-time addendum

(Orchestrator: lane assignment, attempt number, commit trailer.)
