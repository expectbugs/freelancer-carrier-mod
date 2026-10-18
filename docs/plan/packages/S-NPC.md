# S-NPC: Spike: capital NPC travel, gates, frozen systems, freeze/thaw, nanobots, damage, loot, Nomad spawns

- **Type:** spike
- **Wave:** Phase 0 (after G0a)
- **Depends on:** G0a, P0-DATATOOLS → **Unblocks:** G0b, W1-SPAWN, W2-ENCOUNTER, W2-REFLEX, W3-ESCORT, W3-NOMAD, W3-LOSS.

## Goal

Measure what the engine's AI and combat systems actually do for API-spawned ships in single player. The questions:

- How fast and how well a capital ship travels under our orders.
- How it handles gates, planets and fields.
- What happens to our ships when the player leaves the system.
- Whether a fight can be frozen and resumed.
- How to fire nanobots and batteries from code.
- How to observe damage and destruction.
- How to drop bundled loot.
- Whether Nomad capitals can be spawned outside missions without crashing.

Every later combat or escort feature is built on these facts.

## Requirements

- **REQ-S-NPC-1:** Build `s_npc.dll` on `spike_platform_<track>`, with devbridge verbs per experiment. Spike data (e.g. a global Nomad NPCShipArch) is generated into lanes by `spikes/s_npc/gen/`; never committed.
- **REQ-S-NPC-2: ship spawns.** Use FLSDK `ShipInfo` (R2 §1.2 field table):
  - `flag=1`, `system`, `shipArchetype`, `pos`, `orientation`, `loadout`;
  - `rep` from `pub::Reputation::Alloc` + `SetAffiliation(groupId)`, where `GetReputationGroup` returns UINT_MAX if invalid, so check it;
  - `pilotVoice`; `health = -1`; `level`.
  - Names via `FmtStr` mad-lib 16163 `"%s0 %s1"` with IDS names (R2 §1.2 step 2).
  - Then `pub::AI::SubmitState(id, SetPersonalityParams{ stateGraph = get_state_graph("CRUISER", TYPE_STANDARD), personality })`.
  - Get the personality from `pilots_population.ini` (`cruiser_default`, `battleship_default`; R2 §1.2 step 6). On Track A use `ContentHelper::GetPersonality`; on B, parse pilots_population.ini, or port FLHook 4.0 `PilotPersonalities.cpp` logic (GPL: reimplement).
  - Re-check the object exists right after spawn: a spawn can "succeed but instantly die" (R2 §1.2 step 4).
  - Templates: `li_n_dreadnought_d25` etc. (R2 §1.2 step 7; R3 §4.1/§8, VERIFIED HDE `npcships.ini`). Hull archetypes: `li_dreadnought`, `rh_battleship`, `ku_battleship`, `br_battleship`, `or_osiris`, `no_battleship`, `no_gunboat`.
- **REQ-S-NPC-3:** each experiment produces a `FINDINGS.md` entry: hypothesis, method, observation (numbers), verdict, evidence, and proposed `EF-NPC-<n>` facts.

## Experiments

### E1: Capital NPC spawn

- **Method:** spawn `li_dreadnought` with loadout `li_n_li_dreadnought` (10 turrets; R3 §4.2) near the player in Li01, faction `li_n_grp`.
- **Pass:** visible, with turrets on hardpoints (screenshot plus vision check); `GetHealth` = 69,300 max (R3 §4.1); persists for 10 minutes; no crash.

### E2: Point-to-point travel

- **Method:** `DirectiveGotoOp` to a point 25 km away (`Ops.hpp:117-150`; R2 §4.1). Run three variants:
  - (a) `gotoType 1` (pos), `range 500`, `thrust -1`, `goToCruise = true`;
  - (b) the same with `goToNoCruise = true`;
  - (c) `gotoType 2` spline with 4 waypoints.

  Sample position every 1 s for 5 minutes.
- **Observe:**
  - mean speed, max speed, and whether cruise speed (≈300 m/s for player-class engines; capital engines give ≈30 m/s impulse, R3 §4.1) was ever reached;
  - arrival accuracy and time to arrival;
  - stalls (speed under 1 m/s for 20 s while not arrived).
- **Expected (UNVERIFIED):** `LargeShipBehavior` calls `SetCruiseLock(0,3)`, so capitals never cruise (R2 fact 12).
- **Deliverable:** numbers for D-7.13 (escort-mode feasibility: at ≈30 m/s a 30 km leg takes about 17 minutes) and a recommendation for our own kinematic movement when unobserved (BUILD_PLAN §8 fallback).

### E3: Obstacle avoidance

- **Method:** goto routes that pass (a) within 2 km of Planet Manhattan's death zone and (b) through an asteroid field in Li01 (pick from `world.json` hazards).
- **Observe:** does it deflect, stall, collide or take damage? Planet death zones damage and destroy ships.
- **Pass/refute:** record whether waypoint lists from the W1-WORLD planner are mandatory.

### E4: Gate approach and jump

- **Method:**
  1. Order a goto to `Li01_to_Li02` (jumpgate; docking sphere `jump`, radius 225; R2 §4.3).
  2. Option (a): `DirectiveDockOp{DockSpaceObj = gate}`. This op has no usage example anywhere (R2 §4.1: `x18=-1, x20=200, x24=500`; UNVERIFIED). Observe whether the ship docks and what happens on DockComplete (R2 expects it to just sit there).
  3. Option (b): within 1,500 m of the gate, call `pub::SpaceObj::JumpIn(ship, CreateID("Li02_to_Li01"))`. It removes the ship and re-adds it at the destination gate's arrival point, with the jump-in effect (R2 fact 7, VERIFIED-decomp).
  4. The player follows through the gate. Is the ship in Li02? Is the jump effect visible?
- **Pass:** a reliable gate transition recipe exists for escort mode (D-7.7).
- **Evidence:** screenshots before and after, positions.

### E5: NPC-locked links

- **Method:** repeat E4 on `Li01_to_Li05` (npc-locked: initialworld `[locked_gates] npc_locked_gate`; R3 §2.2, VERIFIED) and on a jump hole.
- **Observe:** DockOp refused? JumpIn works anyway?
- **Deliverable:** a fact for escort routing (D-7.9 allows links not locked for the player).

### E6: Frozen systems

- **Method:** spawn our capital in Li01 at a known position, moving. The player jumps to Li02, waits 120 s of game time, and returns.
- **Expected:** the ship is exactly where it was when the player left, and frozen (R2 fact 1, VERIFIED-decomp `IServerImpl.cpp:4064-4125`: only systems with an active player are stepped).
- **Also:** a vanilla encounter NPC near the player despawns beyond 2.5 km (R2 fact 2), while ours persists.
- **Deliverable:** confirms the "Away = simulated on paper" architecture.

### E7: Freeze and thaw a fight

- **Method:**
  1. Spawn our carrier ship plus 4 hostile fighters (e.g. `fc_ou_grp` npcships at d10). Let them fight for 20 s.
  2. Snapshot each object: archetype, loadout, pos, rot, `GetRelativeHealth`, shield health, target.
  3. Despawn all with `pub::SpaceObj::Destroy(id, DestroyType::Vanish)`.
  4. Wait 30 s, then respawn from the snapshot (set health via `SetRelativeHealth`) and re-issue attack orders (rep `SetAttitude`; R2 fact 11).
- **Pass:** the fight resumes with health preserved within 1%; 10 cycles; no crash.
- **Watch:** "an NPC destroyed right after spawn while scripted crashes **SP only**", Freelancer.exe 0x14661b (R4 §0.1 #4). Never vanish an object in the same tick it was spawned; defer.

### E8: Scripted nanobots and batteries

Three methods for the **player**:

- (a) `IObjAffect::use_item(u16 sId, unsigned amount, int)`, vtable +88, on the player ship's IObj, where `sId` is the cargo slot of `ge_s_repair_01` / `ge_s_battery_01` (`FLHookSDK/include/FLCore/IObj/Base.hpp:144`; R2 §6). No proven example exists; FLUF's `OnServerShipUseItem` observes it.
- (b) Emulate `IServerImpl::SPRequestUseItem(SSPUseItem, client)` (FLHookSDK-v4 vtable).
- (c) Raise the client key command `USER_REPAIR_HEALTH` / `USER_REPAIR_SHIELD`, which exist in `DATA/INTERFACE/keymap.ini` (VERIFIED, R6 §3.2).

For an **NPC carrier:**

- (a) carry nanobots and batteries as cargo; the pilot's `RepairUse` block (`use_hull_repair_at_damage_percent`; FLSDK `Personality.hpp:126-138`) uses them automatically;
- (b) `SetRelativeHealth(+Δ)` plus decrementing our own stock.

- **Pass:** hull rises by the vanilla nanobot amount (find it in `misc_equip.ini [RepairKit]`) and the cargo count drops by 1 for each player method that works. Record which methods work.
- **Deliverable:** the reflex mechanism for D-11.1 / D-8.1.

### E9: Damage and destroy events

- **Method:** apply damage to our ship and to a test solar. Use devbridge `damage <id> <hp>` (`pub::SpaceObj::SetRelativeHealth`) and real weapon fire from the hostiles in E7.
- **Pass:**
  - hull-damage events fire with attacker ids (Track A: `OnServerShipHullDmg`/`OnServerSolarHullDmg`; Track B: polling, or the FLHook-style IEngine hooks noted for W1-PLATFORM);
  - destroy events fire with the killer;
  - a capital death runs its fuse and explosion without crashing, 5 times for `li_dreadnought` and 5 for `o_osiris`. Capital death and fuses are a crash hotspot: common.dll 0x5da50 / 0x5e010 (R4 §0.1 #5).

### E10: Loot bundling

- **Method:**
  - (a) Kill an API-spawned NPC carrying 200 units of a commodity plus 50 nanobots. Observe the vanilla drop: at most 6 crates per item, split by `units_per_container`; API NPCs bypass lootprops filtering (R2 fact 9, VERIFIED-decomp).
  - (b) Suppress the vanilla drop (Track A: `OnServerShipDropAllCargo`; Track B: spawn without lootable cargo, or hook the drop path) and spawn our own bundles:
    - `Server.MineAsteroid(systemId, pos, crateArchId, goodId, count, clientId)` (one crate with `count` units; FLHook 4.0 `loot_tables` / `cargo_drop` examples, R2 §7);
    - and/or `pub::SpaceObj::CreateLoot(id, LootInfo{…})` (FLSDK :850-880).
- **Pass:** a crate with 5,000 units of a commodity can be tractored. Record what happens when the player's hold is smaller than the crate. Measure frame time with 6 crates vs 60 crates, **under the exclusive `--perf` lock** (CONVENTIONS §7), so other lanes don't skew the numbers.
- **Deliverable:** the D-8.4 recipe.

### E11: Nomad capitals in free play

- **Method:**
  1. The spike generator adds global `[NPCShipArch]` entries to the lane's `MISSIONS/npcships.ini` via the patch framework:
     - `fcm_spk_no_battleship`: `no_battleship`, loadout `MSN13_Nomad_Battleship`, `state_graph = CRUISER`, pilot per the M13 file;
     - `fcm_spk_no_gunboat`: `no_gunboat`, loadout `MSN12_Nomad_Gunboat`;
     - fighters `fc_n_no_fighter_d19`.

     Nomad battleship and gunboat NPCShipArchs exist only in mission files today (R3 §2.4, VERIFIED). **The generator reads** their field values at deploy time from the lane's `MISSIONS/M10|M12|M13/npcships.ini` and `pilots_story.ini`, and writes the patch into the lane only.
     - **Never paste those values into committed code or YAML** (CONVENTIONS §12). Committed sources may only name the source nicknames, e.g. "clone `MSN13_Nomad_Battleship` from M13".
     - The same rule binds W1-DATA's production version.
  2. From `HARNESS_endgame_crete`, jump via `Hi02_to_Ew06_hole` (`24336,0,-44216`; R3 §2.4) into Ew06, and spawn the group (1 battleship, 2 gunboats, 8 fighters) near Gammu (`20162,0,13301`), faction `fc_n_grp`.
  3. Let the group fight the player (godmode allowed: Console's `godmode` takes effect on the next load, R4 §B6; or our own `SetInvincible`). Kill each capital 5 times.
- **Pass:** valid spawns; Nomad turrets fire; capital deaths don't crash; the Nomad cloak equipment doesn't break anything.
- **Deliverable:** D-12.2 data, validated.

### E12: Who attacks the player

- **Method:** with 10 hostiles near the player, count how many engage at once. The default `Act_PlayerEnemyClamp` is 2,2 (common.dll 0x18C754 / 0x18C758; R4 §A1.3). Note only; S-PERF tests the patch.

### E13: Capital docking physics

- **Method:** the player docks at a large moving vs. stationary capital ship or solar.
- **Observe:** collision spin and "banging about" (R2 §4.3 forum lore).
- **Deliverable:** input to "docking only while Stopped" (D-7.6), which avoids the moving case entirely.

## Context pack

- `docs/plan/CONVENTIONS.md` §1, §2 (`fcm_`), §4, §7, §12 (authoritative)
- `docs/plan/DESIGN.md` §7 (D-7.4–7.8), §8, §9 (D-9.6 paused fights), §10, §11.1, §12
- `docs/plan/TESTING.md` §Metrics, §Scenarios, §Vision, §CrashTriage
- `$FLMOD_RESEARCH/R2-engine-api.md`: **all**
- `$FLMOD_RESEARCH/R3-game-data.md` §2.4, §4, §5 (nanobot goods), §8
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §A1.1, §A1.3, §A1.4
- `refs`:
  - `FLUF/vendor/FLSDK/include/FLCore/{FLCoreServer.h, Common/AI/Ops.hpp, Common/AI/Personality.hpp, IObj/*}`
  - `FLHookSDK-v4/include/FLCore/*`
  - `FLHook-4.0-locked/plugins/{npc_control,solar_control,loot_tables,cargo_drop,npc_spin_protection}`
  - `DiscoveryFLHook/Plugins/Public/dronebays/`
  - `Freelancer-Decomp/src/{Server,Common,Content}/*`
  - `Librelancer/src/LibreLancer/Server/*`

## Ownership

- **Owns:** `spikes/s_npc/`.
- **Must not touch:** `spikes/track_*`, `harness/`, `docs/plan/`, `state/`.

## Contract

- **Provides:** `FINDINGS.md` and proposed `EF-NPC-*` facts, including the gate-jump recipe, the nanobot recipe, the freeze/thaw recipe, the loot recipe, and measured capital speeds.

## Tasks

E1 → E2 → E3 → E4 → E5 → E6 → E7 → E8 → E9 → E10 → E11 → E12 → E13.

## Acceptance

Every experiment has a verdict with numbers and evidence. Reviewers re-run E4, E7, E8 and E11.

## Engine facts to rely on / verify

- **Verify:** cruise lock; DockOp; JumpIn visuals in SP; `use_item`; damage-hook availability on the track; the loot cap; Nomad spawn validity.
- **Rely on:** frozen systems (verify cheaply); spawn validation rules.

## Pitfalls

- Invalid archetype, loadout, IFF or pilot crashes the server. **Validate first.**
- A loadout without an engine crashes at server.dll 0x2247f.
- Defer spawn and destroy work out of engine callbacks.
- Spawned objects leak unless released (FLHook master note, R2 §1.5). Track and despawn everything at scenario end.

## Fallbacks and degrade path

| Problem | Fallback |
|---|---|
| Capital AI is unusable | Kinematic movement: `pub::SpaceObj::Relocate` same-system steps while unobserved, and slow direct steering while observed (BUILD_PLAN §8). Measure the visual quality of each. |
| Player nanobot methods fail | (c) key simulation via the client command path |
| Our own loot bundling fails | Vanilla drops with the cargo split into the fewest goods possible |

## Report

AGENT_BRIEF_TEMPLATE format plus a `FINDINGS.md` summary with all the numbers.

## Gate-time addendum

(Orchestrator: track, lane(s), attempt, commit trailer.)
