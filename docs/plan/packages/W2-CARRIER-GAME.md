# W2-CARRIER-GAME: Carrier in the engine (solar, base binding, launch control, docking, load restore)

- **Type:** impl
- **Wave:** 2 (sub-wave 2b, CONVENTIONS §8)
- **Depends on:** W2-CARRIER-LOGIC, W2-LOADOUT (both merged), ARCH-1
- **Unblocks:** W2-CARRIER-UI integration, W3-ESCORT, W3-AMBUSH, W3-LOSS, M1-PLAYTEST

## Goal

Make the carrier model real in Freelancer:

- a battleship-model solar appears where the model says the carrier is Stopped;
- the player can dock with it and lands in the carrier's interior;
- undocking puts the player beside it;
- launching is impossible while the carrier is "in warp";
- docking is refused unless the carrier is Stopped;
- every save loads back into exactly the same situation, without the known "base without a solar" crashes.

This package executes the side-effect requests produced by W2-CARRIER-LOGIC.

## Requirements

- **REQ-W2-CARRIER-GAME-1** (D-7.6, D-7.11): a Stopped carrier in the player's current system is represented by **one runtime solar**:
  - the archetype and loadout come from the carrier's look, class and tier (W1-DATA / W2-LOADOUT);
  - its nickname is unique, `fcm_carrier_<id>`;
  - it docks to the base chosen by the base plan (REQ-4).

  No solar exists for a carrier in any other state, except while UnderAttack (W3-AMBUSH decides the form).
- **REQ-…-2** (D-7.6): **docking is allowed only while Stopped.**
  - A dock request (server `RequestEvent` eventType 0, vtable +0xF0; the platform contract's suppressible dock-request event) targeting a carrier object in any other state is denied.
  - The player sees an explanation: an NN message or toast, e.g. "Carrier is under way; docking denied".
- **REQ-…-3** (D-7.3): **undock is blocked while in DockedTravel.**
  - Client side: the launch-permission check (`Freelancer.exe 0x4422B0`; platform `OnLaunchRequested` suppress) refuses the launch with a message.
  - Server backstop: suppress `PlayerLaunch` (vtable +0xC0), which forces a re-dock (FLUF semantics; Discovery's "Can't undock while carrier is in hyperspace transit" precedent).
  - The block lifts **only after** the solar exists and the base binding (REQ-4) points at it.
- **REQ-…-4** (D-7.3, D-14.2): **base binding.** Implement the plan chosen at Gate 0b (named in the gate addendum). Implement the other plan as a compile-time-switchable fallback only if the addendum says so.
  - **Plan A, re-point.**
    - One `[Base]` per interior look (from W1-DATA).
    - At dock time, and again after every save load, set the shared `Universe::IBase` record's `systemId` and `spaceObjId` (FLSDK `include/FLCore/Common/Universe/IBase.hpp`) to the docked carrier's current system and solar id.
    - Common.dll is shared by client and server in single player (R5 §1.1), so one write affects both. Universe data is reloaded from INI on load, so the re-point must be **re-applied after every load before any launch can occur**.
    - Track "which carrier am I aboard" in the model (several carriers can share one look's base).
  - **Plan B, proxy per system.**
    - Generated `[Base]` per (system, look) from W1-DATA; the solar's `dockWith` is the proxy for its current system.
    - When a Stop happens in a system other than the docked proxy's system, perform the **arrival reload**:
      1. `pub::Save` to a dedicated slot;
      2. rewrite `[Player] system=` and `base=` in that `.fl` to the destination proxy (plain-text saves, R5 §3.1);
      3. load it, showing "Arriving…".

      This mirrors Discovery's offline-character rewrite (R2 §2.2).
    - Never leave a save naming a proxy whose system has no carrier solar.
- **REQ-…-5** (D-7.3): **undock position override.**
  - On launch from a carrier base, the platform's launch-position hook (server.dll RVA `0x8420C`, FLUF `OnServerShipUndock` returning a transform) places the player beside the carrier solar.
  - Use a bay exit point if the model has one, else `carrierPos + carrierUp × offset` (offset ≈ 600 m, tunable). Orientation faces away from the hull.
  - The override applies to carrier bases only.
- **REQ-…-6** (D-14.2, R4 §A1.4): **the base must have its solar before any launch or warp.** Never allow a launch when the docked carrier base has no live solar in the player's system. Known crash offsets for violations:
  - `server.dll 0x14990` (no valid undock point);
  - `server.dll 0xab670` (warp to a base whose solar isn't in space);
  - `common.dll 0x4fe6c` (client/server base nickname mismatch at launch);
  - `Freelancer.exe 0x13d55a` (dock to a solar the client doesn't have).

  Every path that reaches launch is guarded and tested.
- **REQ-…-7** (D-14.1–14.3): **load restore.**
  - On load (CharacterSelect, vtable +0x50, or the platform load event), first reconstruct the model from the per-save JSON.
  - Then, if the player is docked at a carrier base:
    1. block launch;
    2. spawn the solar for that carrier (if Stopped) or keep it absent (if DockedTravel);
    3. re-apply the base binding;
    4. unblock as the state allows.
  - A pre-mod save (no JSON) loads normally with an empty fleet.
  - **Aboard during a held fight** (state UnderAttack with the player docked, D-9.5):
    1. spawn the carrier solar first;
    2. call the contract hook `RestoreHeldFight(carrier)` (provided by W3-AMBUSH; a no-op stub until then), which thaws the held attackers;
    3. only then allow launch.
  - **Missing carrier record** (corrupt JSON, with the player docked at a carrier base). **Never `ForceLand` a docked player:** ForceLand only works in space (R2 fact 6), and a docked base without a solar is a known crash class (REQ-6). Recover in this order:
    1. **Preferred:** recreate a minimal Stopped carrier record (class and look from the base nickname, full hull, empty hold), spawn its solar at a safe point in the base's current system, re-apply the binding, and unblock launch, with a notification "Carrier records were damaged; your carrier was restored at <place>".
    2. **Otherwise:** the arrival-reload mechanism. Save to a dedicated slot, rewrite `[Player] base=` / `system=` in that `.fl` to a real base in that system (or the carrier's yard base), and load it, with a notification.
- **REQ-…-8:** **solar visibility and dockability.** Use the spawn path that S-BASE proved visible in single player:
  - FLUF builder with the packet fix;
  - `ResourceManager::CreateSolarSimple`;
  - or raw `pub::SpaceObj::CreateSolar` without the `server.dll+0x2A62A` packet patch.

  Fill `SolarInfo` correctly (R2 §1.3): `flag = 4`, valid `archId`, `systemId`, `pos`/`orientation`, `loadoutId`, costume, `rep` from `Reputation::Alloc` + `SetAffiliation`, `dockWith` = base id, `hitPointsLeft`, unique `nickName`.

  If S-BASE showed the "spawned solars are not dockable" glitch, re-apply `SetRelativeHealth(id, current)` on a 5 s timer, as FLHook 4.0 `solar_control` does (R2 §2.4).
- **REQ-…-9** (D-7.12, D-3.1): **fleet.**
  - When the player enters a system, spawn solars for every Stopped carrier located there.
  - When the player leaves, despawn them (Vanish), or keep them if S-BASE showed persistence is harmless. Pick per ENGINE_FACTS and record the choice.
  - Report the fleet capacity of the chosen base plan to W2-YARD through the contract, as **measured by S-BASE's fleet-scale experiment** (≥ 8 carriers, including 2 of the same look in one system under Plan B; ENGINE_FACTS). Never report a capacity that wasn't measured.
- **REQ-…-10** (CLAUDE.md §3, R5 §2): every engine mutation is **deferred one tick** via the W1-CORE next-tick queue when triggered inside an engine callback: spawn, destroy, relocate, ForceLand, binding writes, save/load triggers. All of it runs on the main thread.
- **REQ-…-12** (CONVENTIONS §9): **attack and hull watcher for live carrier objects.**
  - Hostile damage to a carrier's solar (or ship form) emits `Attacked` to the model (Stopped/EscortTravel → UnderAttack) when not already in a formal encounter.
  - For such non-encounter attacks, `Won` is emitted when no hostile has damaged the carrier for 30 s and none is within 10 km.
  - Hull reaching 0 emits `HullZero` (→ UnderAttack → Destroyed in one tick).
  - In Wave 2 the Destroyed cleanup is minimal: despawn the object, release the binding, keep the record for W3-LOSS. W3-LOSS adds loot and full cleanup.
  - Ambush fights (W3-AMBUSH) report their own outcomes through encounter hooks, and this watcher defers to them while an encounter instance owns the fight.
- **REQ-…-11:** devbridge commands (CONVENTIONS §4, `carrier.*` namespace), registered in this package:
  - `carrier.list`
  - `carrier.status <id|name>`: state, system, pos, base, hull, stock
  - `carrier.buy class=<c> tier=<t> name=<n> [at=<base>]`: **test-only** creation without payment or UI (W2-YARD owns the real purchase via `yard.*`)
  - `carrier.travel <id> <dest> [docked|escort]`
  - `carrier.stop <id>`
  - `carrier.teleport_model <id> <system> <x,y,z>`: test-only model move
  - a resolver so the W1-CORE `base` verb accepts `base carrier:<name|id>` (instant dock for tests)

  State changes emit `HARNESS … ev=carrier.state id=… state=… system=… pos=… base=…`. Denials and blocks emit `ev=carrier.dock_denied reason=…` and `ev=carrier.launch_blocked reason=…`.

## Context pack (read before writing code)

- `CLAUDE.md`
- `docs/plan/CONVENTIONS.md` (all; §4 devbridge, §8 sub-waves, §9 state machine)
- `docs/plan/DESIGN.md` §3, §7, §14
- `docs/plan/TESTING.md` §Devbridge, §Fixtures, §Scenarios, §SaveCompat, §CrashTriage
- `state/ENGINE_FACTS.md`: all S-BASE entries (spawn path, visibility, dockability, base plan, launch block, launch position, save/load hooks)
- Contracts: platform (dock-request, launch-request, launch-position, load, save events), spawn service, persistence, carrier model, world (safe stop), text/notifications
- `local/research/R2-engine-api.md` §0 facts 3–6, 13–15; §1.3 SolarInfo; §2.1–2.6 (Discovery POB, mobile docking, '88 Flak proxy bases, solar_control)
- `local/research/R5-sp-architecture.md` §3.4–3.5 (save/load hooks, missing-base behavior), §4.1–4.3 (room UI, `PlayerData.baseId` +0x3EC, launch block), §9 table
- `local/research/R1-fluf.md` §2.2–2.6, §3.3 (if Track A)
- `local/research/R4-lore-and-testloop.md` §A1.4 (base crash causes)
- Reference code:
  - `/home/user/freelancer/refs/DiscoveryFLHook/Plugins/Public/mobiledocking_plugin/Main.cpp` (720–908: launch/dock handling, transit block)
  - `…/base_plugin/Main.cpp` (LaunchPosHook 1838–1875, land redirect 1131–1170)
  - `/home/user/freelancer/refs/FLHook-4.0-locked/plugins/solar_control/SolarControl.cpp` (261–357 spawn, 613–625 health re-apply)
  - `/home/user/freelancer/refs/FLHook-88Flak/FLHook/trunk/src/source/HkCbIServerImpl.cpp` (240–420 undock, 1702–1830 jump chain)

## Ownership

- **Owns:** `src/game/carrier/`
- **Test assets:** per the BUILD_PLAN §6 ownership conventions: `src/game/carrier/scenarios/*.yaml` (or `harness/scenarios/carrier/`), schema per TESTING §Scenarios. The runner discovers them.
- **Reads:** `src/contracts/`, `src/logic/carrier/`, `src/game/platform/`, `src/game/core/`, `src/game/spawn/`, `src/game/ui/kit/`, `src/game/text/`, `data/`, `gen/` outputs
- **Must not touch:** everything else

## Contract

- **Consumes:** the carrier model (side-effect requests), the platform events listed above, the spawn service (validated solar spawn/despawn), persistence (load/save hooks), notifications, world (safe stops, system ids).
- **Provides:**
  - an executor for carrier side-effects;
  - a base-binding service, used by W3-ESCORT and W3-LOSS;
  - `CarrierObjectRegistry` (carrier id ↔ object id), used by W2-CARRIER-UI, W3-*, W2-REFLEX (carrier auto-nanobots);
  - devbridge commands.

## Tasks

1. Implement the side-effect executor, with the per-tick deferral queue.
2. Solar spawn/despawn for Stopped carriers via the S-BASE-proven path, plus the dockability timer if needed.
3. Base binding for the chosen plan (A or B), including the post-load re-apply or the arrival reload.
4. Dock-request filter, launch block (client and server), launch-position override.
5. Load-restore sequence and the safe-recovery path for corrupt or missing carrier records.
6. Fleet presence on system enter/leave.
7. Devbridge commands and HARNESS lines.
8. Scenarios (below), then iterate until green on two lanes.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:**
  - executor ordering, using a mocked platform;
  - binding-plan selection logic;
  - corrupt-record recovery decision table.
- **Build checks:** i686 build; import check; `harness/ci.sh` green.
- **In-game scenarios** (each run on 2 lanes; FLSpew diff clean; no crash):

  | Scenario | Steps and expected result |
  |---|---|
  | `carrier_spawn_visible` | Fixture `HARNESS_endgame_eagle`, `launch`. `carrier.buy class=fleet tier=core name=T1 at=Li01_07_Base`, fly within 3 km. **Expect** `ev=carrier.state id=T1 state=Stopped`; screenshot; vision: "a large capital ship is visible near screen centre". |
  | `carrier_dock_undock` | Dock (`base carrier:T1`, then once via a real dock request with autopilot on the input lane). **Expect** `state=docked base=<carrier base>`; interior screenshot (vision: battleship deck or bar interior); `launch` → **expect** player within 1.5 km of the carrier solar, facing away. |
  | `carrier_dock_denied_when_not_stopped` | With T1 Stopped and the player in space nearby: `spawn <hostile npc_def> 2 near=x,y,z tag=h` next to the carrier, so it is attacked (`Attacked` → UnderAttack, CONVENTIONS §9). Dock request → **expect** `ev=carrier.dock_denied reason=not_stopped`; player still in space. `despawn h` → `Won` → Stopped → docking is allowed again. (The escort-form denial is W3-ESCORT's scenario.) |
  | `carrier_docked_trip` | Aboard, `carrier.travel T1 Li03 docked`. `launch` → **expect** `blocked=1` and `ev=carrier.launch_blocked`, no crash, still docked. `time.skip` to arrival → `ev=carrier.state id=T1 state=Stopped system=Li03`. `launch` → player spawns in Li03 next to the carrier. |
  | `carrier_reroute` | Aboard and travelling, `carrier.travel T1 Li02 docked` (new destination). **Expect** state stays DockedTravel and the route is recomputed from the current position (`carrier.status` shows the new destination). |
  | `carrier_stop_midroute` | During the trip, `carrier.stop T1` → Stopped at a safe point (assert distance to hazards ≥ buffer from the `carrier.status` pos vs world data); `launch` OK. |
  | `carrier_save_load_each_state` | For each of Stopped, DockedTravel (aboard), Stopped in a foreign system: save, quit, relaunch with `--save-file`. **Expect** identical `carrier state` lines, ±1 % progress; for the aboard cases launch still blocked/allowed correctly. |
  | `carrier_corrupt_json_recovery` | Corrupt the JSON while aboard, reload. **Expect** per TESTING §SaveCompat: `.bad-<ts>` kept, `.bak` used if present. With no usable record, the REQ-7 recovery runs (restored carrier, or base rewrite + reload), with a notification, no crash, and **no ForceLand while docked**. |
  | `carrier_premod_save` | A vanilla HDE save loads with an empty fleet and no errors. |
  | `carrier_fleet_two` | Two carriers in different systems; dock at each in turn (Plan A re-point or Plan B proxies). **Expect** the correct interior and undock position each time. |

- **Metrics:** dock-to-interior < 5 s; launch-block decision < 1 frame; save/load restore drift ≤ 1 % route progress.
- **Negative tests:**
  - F1 pause during a trip;
  - alt-tab (keep-running patch);
  - player death while a carrier is in DockedTravel (impossible: the player is aboard; assert the state is unaffected);
  - a load during an active arrival reload (Plan B).

## Engine facts to rely on / verify

- S-BASE: spawn path visibility, `dockWith` dockability, Plan A/B result, launch block, launch position, save/load hook addresses.
- R2 fact 6: `pub::Player::ForceLand` only works while the player is in space.
- R5 §1.1: client and server share common.dll in single player.

## Pitfalls

- **Never `pub::Player::ForceLand` a docked player** (it only works in space; docked base without solar = crash class).
- Never destroy a carrier solar while the player is docked at its base, unless the binding is handled. Never let launch run when the base's solar is missing (REQ-6 offsets).
- Duplicate solar nicknames create duplicate object ids. Always check `pub::SpaceObj::ExistsAndAlive` before re-spawning.
- An invalid solar archetype is a null-deref crash (`server_pub.cpp` CreateSolar), so validate through the spawn service.
- FLUF restores its own vtable slots on shutdown, so don't hand-patch slots that FLUF owns (Track A).
- The console.dll SP-chat and save hooks (`0x5AB231`, `0x6D275`, `0x6A177`) already exist; chain them, don't overwrite.

## Fallbacks and degrade path

1. If the chosen plan fails in production scenarios, switch to the other plan (both are specified above). Log a decision and request an ARCH note.
2. If the solar is invisible via every spawn path: keep a hidden pre-placed carrier object per system and per look in the data, and move it by respawn (BUILD_PLAN §8).
3. **Degraded:** docked travel completes only at the destination (no mid-route Stop). Flag `carrier.midroute_stop = false`.

## Report (the agent's final message)

Per the template. Include which plan you implemented and the exact hook path for each event.

## Gate-time addendum

Track, base plan (A/B), spawn path (from S-BASE), contract paths, ENGINE_FACTS ids, lanes, attempt and prior notes.
