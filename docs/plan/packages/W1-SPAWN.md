# W1-SPAWN: validated spawning, ownership registry, freeze/thaw, AI helpers

- **Type:** impl
- **Wave:** 1
- **Depends on:** W1-PLATFORM, W1-HARNESS (sub-wave 1b, CONVENTIONS §8; contracts `spawn.hpp`, `ai.hpp` from ARCH-0) → **Unblocks:** W2-ENCOUNTER, W2-CARRIER-GAME, W2-LOADOUT, W3-*, W4-WINGMEN, W4-ESCALATION

## Goal

The only code path that creates, tracks, moves, freezes and removes runtime objects (ships, solars, loot) and gives orders to NPC AI.

Invalid spawns are a top crash class in Freelancer (R2 §1.5, R4 §A1.4 item 6), so every spawn is validated first. Every object we create is owned and tracked, and is cleaned up on system change, load and shutdown. Fights can be frozen and thawed: the "fights wait for you" rule (D-1.5, D-9.6, D-10.4) depends on that.

## Requirements

- **REQ-W1-SPAWN-1: Validation before every spawn.** Every ID must exist:
  - ship or solar archetype (`Archetype::GetShip/GetSolar`);
  - loadout (`Loadout::Get`), and it must include an engine for ships (missing engine → crash at server.dll 0x2247f);
  - reputation group (`pub::Reputation::GetReputationGroup` ≠ UINT_MAX);
  - pilot/personality;
  - base (for `dockWith`);
  - voice and costume;
  - system;
  - a unique nickname for solars (an empty one → CreateSolar returns −4).

  Validation failure returns an error and logs it; it never calls the engine.
- **REQ-W1-SPAWN-2: Ship spawn.** `pub::SpaceObj::Create` with `ShipInfo`. Field layout per R2 §1.2:
  - `flag` = 1;
  - system, shipArchetype, pos, orientation, loadout;
  - `rep` from `pub::Reputation::Alloc(rep, scanner FmtStr, pilot FmtStr)` + `SetAffiliation`;
  - `pilotVoice`, `health = -1`, `level`.

  Then `pub::AI::SubmitState` with `SetPersonalityParams` (state graph FIGHTER, TRANSPORT, GUNBOAT or CRUISER, via `pub::StateGraph::get_state_graph`; personality from content's builder or a parsed `pilots_population.ini`/`pilots_story.ini`).

  After the spawn, re-check `ExistsAndAlive`, because a spawn can succeed and die instantly (FLHook master note). Names come from the IDS pools; FLUF's default pool is IDS 197808–197828.
- **REQ-W1-SPAWN-3: Solar spawn.**
  - Use the **S-BASE-proven SP-visible path**: raw `pub::SpaceObj::CreateSolar` without FLUF's 0x2A62A packet suppression, or FLUF `CreateSolarSimple`, per ENGINE_FACTS.
  - `SolarInfo` per R2 §1.3: `flag` 4, `archId`, `systemId`, pos/orientation, `loadoutId`, costume and voice for comms, `rep`, `dockWith` = base id when dockable, `hitPointsLeft`, unique `nickName`.
  - Then `SetRelativeHealth`. Re-apply relative health periodically if S-BASE confirms the "spawned solars not dockable" glitch (R2 §1.5, FLHook re-applies every 5 s).
- **REQ-W1-SPAWN-4: Loot spawn.**
  - `pub::SpaceObj::CreateLoot(LootInfo)`, or `Server.MineAsteroid(system, pos, crateArch, good, count, client)`, whichever S-NPC proves.
  - Supports one crate holding many units (bundling, D-8.4) and a per-call crate cap.
- **REQ-W1-SPAWN-5: Ownership registry.**
  - Every spawned object is recorded: id, kind, owner subsystem, spawn spec (for respawn), tags, created_at.
  - Lookups by id, owner and tag.
  - Destruction (FUSE: explosion; VANISH: silent) through `pub::SpaceObj::Destroy`, or `SetRelativeHealth(0)` for an explosion when the destroy-hook path requires it.
  - Notifications when an owned object dies or despawns, via platform destroy events. Discovery notes that health=0 kills don't notify, so emulate the notification.
  - Never leak a registry entry. Mismatches are reported via the devbridge `spawn audit`.
- **REQ-W1-SPAWN-6: Lifecycle.** Owned objects in a system the player leaves are, per owner policy:
  - (a) despawned and recorded for respawn; or
  - (b) left frozen (the engine stops simulating systems without the player: R2 fact 1, VERIFIED-decomp).

  The default is (a), for deterministic state. On load, new game and SP stop, clear everything (objects from a previous session don't exist).
- **REQ-W1-SPAWN-7: Freeze/thaw** (D-9.6, D-10.4). `Freeze(groupTag)`:
  - snapshots each living member: spawn spec, pos, orientation, relative hull, shield fraction where readable, current target;
  - despawns them with VANISH;
  - returns a serializable `FrozenGroup` (JSON through `persistence`).

  `Thaw(frozen, placementTransform)` re-spawns the members with their stored health relative to a new anchor (e.g. around the carrier when the player arrives). Members dead at freeze time stay dead.
- **REQ-W1-SPAWN-8: AI helpers** (contract `ai`). Build ops per FLSDK `Common/AI/Ops.hpp`:
  - `GotoPoint(ship, pos, range, cruise=true|false, thrust)`: `DirectiveGotoOp` type 1.
  - `GotoObject`: type 0.
  - `FollowPath(waypoints)`: a chain of goto points driven by arrival checks each tick. Spline type 2 where it helps.
  - `Follow(ship, leader, maxDistance, offset)`: `DirectiveFollowOp` (`dunno2` = 400 per examples).
  - `Stop / Cancel`: `DirectiveCancelOp`.
  - `AttackTarget(npc, target)`: per Discovery dronebays, using reputation, not directives. Allocate a per-NPC rep (`Reputation::Alloc`), `SetAttitude(npcRep, targetRep, -1)` and back, and release with 0. Optionally `pub::AI::submit_forced_target` if S-NPC verifies it.
  - `JumpThrough(ship, gate)`: fly to the gate, then `pub::SpaceObj::JumpIn(ship, destGate)` when within the docking sphere range (jumpgate 225 m, jumphole 150 m, R2 §4.3), or vanish and respawn on the far side when the far system is unobserved.
  - `SetPersonality(ship, pilotNick)`; `SetInvincible(id, bool)`.
  - `Relocate(obj, system, pos, ori)`: `pub::SpaceObj::Relocate`. For the player ship, also send `FLPACKET_SERVER_LAUNCH` per R2 §3, or use the S-NPC-proven method.
- **REQ-W1-SPAWN-9: Stuck detection.** For moving owned ships, sample progress each 10 game seconds. If no progress over 60 s while not in combat, emit `ai.stuck` with position and target. Callers use it to nudge (re-issue goto, sidestep waypoint) or to relocate kinematically when no player is within 10 km (BUILD_PLAN §8 row 4).
- **REQ-W1-SPAWN-10: Main-thread and deferral discipline.** All APIs assert they run on the main thread outside engine callbacks; otherwise they enqueue via `Core::Defer`.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§2 nicknames, §4 devbridge, §6 fixtures, §8 sub-waves)
- `docs/plan/DESIGN.md` §1.5, §8, §9.6, §10, §11
- `docs/plan/TESTING.md` §Scenarios, §Metrics (AI stuck, FPS), §CrashTriage
- `state/ENGINE_FACTS.md` (S-BASE, S-NPC, S-LOADOUT, S-PERF facts: spawn path visibility, relative-health glitch, JumpIn visuals, loot cap, capital speed, cruise behavior, attitude-based attack)
- `src/contracts/{spawn,ai,platform,events,persistence}.hpp`
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R2-engine-api.md` §0 (all 15 facts), §1 (signatures, ShipInfo/SolarInfo layouts, canonical sequence, destroy, crash pitfalls), §3 (moving things table), §4 (AI ops, personalities, capitals, the wingmen recipe), §5 (off-screen simulation), §6 (combat helpers), §7 (loot)
  - `/home/user/freelancer/carrier-mod/local/research/R1-fluf.md` §2.6 (FLUF `ResourceManager`, builder SP caveat)
  - `/home/user/freelancer/carrier-mod/local/research/R4-lore-and-testloop.md` §A1.4 (spawn crash causes: server.dll 0x2247f, 0x17f38; Freelancer.exe 0x14661b SP-only "NPC destroyed right after spawn while scripted")
- Reference code:
  - `/home/user/freelancer/refs/FLHook-4.0-locked/plugins/npc_control/NPCControl.cpp`
  - `.../plugins/solar_control/SolarControl.cpp`
  - `/home/user/freelancer/refs/DiscoveryFLHook/Plugins/Public/dronebays/`
  - `/home/user/freelancer/refs/FLUF/FLUF/Source/Server/ResourceManager.cpp`
  - `/home/user/freelancer/refs/FLUF/vendor/FLSDK/include/FLCore/FLCoreServer.h` and `Common/AI/Ops.hpp`
  - `/home/user/freelancer/refs/Freelancer-Decomp/src/Server/server_pub.cpp` (Create, CreateSolar, JumpIn, Relocate, ForceLand)

## Ownership

- **Owns:** `src/game/spawn/`, `src/game/ai/` (each with `tests/` and `scenarios/`), and `harness/scenarios/spawn/`.
- **Reads:** contracts, platform API, core API, research, refs.
- **Must not touch:** contracts, data generation (if a spawn needs a new archetype or loadout, ask W1-DATA through the report).

## Contract

- **Provides:** `spawn.hpp` (`SpawnShip`, `SpawnSolar`, `SpawnLoot`, `Destroy`, `Registry`, `Freeze`/`Thaw`) and `ai.hpp` (helpers above, stuck events).
- **Consumes:** `platform.hpp` (events, defer), `core` (clock, events, persistence, devbridge), the IDS name pools from the text service (W1-UI) through the contract.

## Tasks

1. Validation module, with a table of the engine lookup functions used and their failure values.
2. Ship, solar and loot spawn using the ENGINE_FACTS-proven paths, with post-spawn verification.
3. Registry, destroy, notifications and audit.
4. Lifecycle policies and a reset on load or new game.
5. Freeze/thaw, with a JSON round-trip test.
6. AI helpers (goto, path follow, follow, cancel, attack-by-rep, jump-through, relocate, invincible, personality).
7. Stuck detector.
8. Devbridge verbs (CONVENTIONS §4 names; TESTING §Devbridge spellings accepted as aliases):
   - `spawn <npc_def|arch:loadout> [n] [near=player|x,y,z] [tag=<t>] [rep=<grp>]`, with aliases `rel=<x,y,z>`, `at=<obj>` and `id=<label>`. Emits `ev=spawn ok=<n> tag=<t>` or `ev=spawn err=<reason>`.
   - `despawn <tag|id>`, `freeze <tag>`, `thaw <tag>`.
   - Additive verbs, which ARCH-1 records in `docs/spec/devbridge.md`:
     - `kill <label|target> [fuse|vanish]`, `target <label|nick>`;
     - `spawn.solar <arch> <loadout> x,y,z [dock=<base>]`, `spawn.loot <good> <count> [crates=<n>]`;
     - `spawn.list [tag]`, `spawn.audit`;
     - `ai.goto|ai.follow|ai.attack|ai.stop|ai.jump <args>`.
   - Events: `ev=owned.destroyed tag= n=`, `ev=ai.stuck id= pos=`.
9. In-game scenarios and soak (below).

## Acceptance

- **Host tests:**
  - `validate_rejects_missing_engine` (fake lookup tables)
  - `registry_no_leak_on_reset`
  - `freeze_json_roundtrip`
  - `stuck_detector_thresholds`
  - `attitude_pairs_released`
- **In-game scenarios** (each with screenshots and HARNESS assertions; TESTING §Scenarios):
  1. `spawn_ship_fighters`: from `HARNESS_endgame_eagle` launched in Li01, `spawn li_n_li_elite_d6 5 near=player rep=li_n_grp tag=t1` → 5 alive (`ev=spawn ok=5 tag=t1`); they fly. Kill them via the player with godmode on → `ev=owned.destroyed tag=t1 n=5`; `spawn.audit` is clean.
  2. `spawn_capital`: `spawn li_n_dreadnought_d25 1 near=player` → alive and visible (screenshot, vision "a large capital warship is visible"); `ai.goto` 10 km → arrives within tolerance, or a stuck event is logged with details.
  3. `spawn_solar_visible`: spawn the carrier-candidate solar (`l_dreadnought`-derived test archetype from W1-DATA, or vanilla `l_dreadnought_nodock` before data exists) 3 km ahead → visible to the player (screenshot plus vision; `pub::SpaceObj` lookups OK on the client) → leave the system and return → re-spawned per policy.
  4. `spawn_invalid_inputs`: 12 malformed requests (missing loadout, no engine, bad rep, empty nickname, duplicate nickname, bad system, bad base, …) → 12 `ev=spawn err=…` and **no crash**.
  5. `freeze_thaw_fight`: spawn 4 hostiles around a friendly gunboat, let them fight 20 s → `freeze` → hulls recorded → fly 20 km away → `thaw` near the player → same members and hulls ±2 %, fighting resumes.
  6. `ai_jump_through`: spawn a friendly cruiser near the Li01→Li02 gate, `ai.jump` → it disappears with the jump effect. Fly through yourself → `thaw`/respawn on the Li02 side is visible (screenshot).
  7. `attack_by_rep`: spawn a friendly fighter, target an enemy, `ai.attack` → the enemy takes damage from the friendly within 30 s; release → it stops.
  8. `relocate_player_same_system`: relocate the player 5 km → the client view updates, no desync (`state` position equals the server position).
- **Soak:** 30 minutes of the random spawn/kill/freeze/thaw/system-change loop (`harness/scenarios/spawn/spawn_soak.yaml` under `harness/soak/soak.sh`, 2–40 objects alive). `spawn.audit` must be clean every minute, and the TESTING §Soak crash-free criteria hold.
- **Metric:** spawn latency per object, recorded as `HARNESS metric=spawn_latency_ms` (informational; no target in `metrics_targets.yaml`).

## Engine facts to rely on / verify

- API NPCs persist until destroyed and freeze with their system; Content NPCs despawn beyond 2.5 km (R2 facts 1–2).
- A runtime solar may be invisible if spawned through FLUF's builder in SP (R2 fact 4, R1 §2.6). Use the S-BASE answer.
- `JumpIn` removes the ship and re-adds it at the arrival location with a jump-in effect (VERIFIED-decomp). The SP client effect is per S-NPC.
- An API-spawned NPC drops all lootable cargo (up to the 6-crate cap) because Content's `PrepareLoot` is skipped (R2 fact 9).

## Pitfalls

- An NPC destroyed right after spawning while "scripted" crashes in SP only (Freelancer.exe 0x14661b). Never destroy within 1 s of spawning; defer.
- Duplicate solar nickname = duplicate object id. Generate nicknames as `fcm_<owner>_<seq>_<gameTimeMs>` (CONVENTIONS §2).
- `InstantDock` indexes docking spheres unchecked (R2 §1.5). Never pass a port number you haven't checked against the archetype.
- Capital-ship death fuses are a crash hotspot (R4 pitfall 5). Use the vanilla fuse of the archetype, and never `destroy_root` a dockable base.

## Fallbacks and degrade path

1. If attack-by-rep doesn't make NPCs engage reliably, add `submit_forced_target`, then periodic re-targeting.
2. If `JumpIn` misbehaves in SP, use vanish plus respawn at the arrival point on the far side with the jump-in effect (FxManager on Track A, or the vanilla jump effect archetype).
3. If freeze/thaw shield values can't be read, thaw with full shields and record the gap.

## Report

Use the standard report. Include the validation table, the policy defaults, the devbridge command reference, and the measured spawn latencies.

## Gate-time addendum

The orchestrator fills:

- ENGINE_FACTS IDs for the solar spawn path, the relative-health glitch, the loot path, JumpIn, attack-by-rep and capital speed;
- the test archetypes available from W1-DATA;
- lanes;
- attempt notes;
- the commit trailer.
