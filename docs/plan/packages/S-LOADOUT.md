# S-LOADOUT: Spike: runtime loadouts, added hardpoints, capital shields, munition depletion

- **Type:** spike
- **Wave:** Phase 0 (after G0a)
- **Depends on:** G0a, P0-DATATOOLS, S-BASE (E7 retrofit-while-docked uses S-BASE's dockable-solar and base-binding recipe; run E1–E6 in parallel with S-BASE, then E7 once S-BASE has merged) → **Unblocks:** G0b, W1-CARRIER-DESIGN, W2-LOADOUT, W2-YARD.

## Goal

The Carrier Yard sells upgrades that change a carrier's weapons, hull, engines and shields, both at purchase and as a later retrofit (DESIGN §5). Carrier classes need more turrets, missile launchers and torpedo launchers than some vanilla models have hardpoints for (D-4.4). Operating costs need missiles, torpedoes and nanobots to deplete in use (D-8.6).

Prove which of these the engine allows:

- composing a loadout at runtime;
- mounting weapons on newly added hardpoints;
- giving a capital a shield;
- tracking and enforcing munition use by an NPC carrier.

## Requirements

- **REQ-S-LOADOUT-1:** Build `s_loadout.dll` on `spike_platform_<track>` plus a lane generator `spikes/s_loadout/gen/` using P0-DATATOOLS (`fltools.utf`, `fltools.patch`). Generated models and INIs exist only in lanes.
- **REQ-S-LOADOUT-2:** Write a `FINDINGS.md` entry per experiment (hypothesis, method, observation, verdict, evidence, proposed `EF-LOAD-<n>` facts). Recommend an upgrade-implementation strategy with a decision table.

## Experiments

### E1: Runtime loadout creation

Create a new loadout at runtime: id `crr_test_loadout_1`, items = engine `ge_rb_engine_01` + 6 turrets on existing `HpTurret_R1_*` / `R2_*` hardpoints of `rh_battleship` (R3 §4.2: R1×4, R2×4, R3×6, R4×7, VERIFIED).

- **Track A:** `ResourceManager::CreateNewLoadout(nick, items)` (R1 §2.6).
- **Track B:** study FLUF's implementation (`refs/FLUF/FLUF/Source/Server/ResourceManager.cpp`) and reimplement it against the common.dll `Loadout` API. FLSDK headers: `Loadout::Get` etc.

Spawn a ship **and** a solar with this loadout.

**Pass:**

- the turrets are visible on the hardpoints (screenshot plus vision);
- the turrets fire at a hostile;
- server and client agree (no invisible turrets);
- no crash;
- it survives leaving and re-entering the system, and save/load. Respawn is our job; check that the loadout id still exists after load. If it doesn't, recreate loadouts on game start.

### E2: Pre-generated loadout fallback

The generator writes 50 loadout variants into an overlay `loadouts` file added through `freelancer.ini [Data] loadouts = …` (append).

**Pass:** all 50 spawn correctly. Measure the load-time impact. This is the BUILD_PLAN §8 fallback if E1 fails.

### E3: Added hardpoints

`fltools.utf.add_hardpoint` adds 6 `HpTurret_X_01..06` (revolute; axis, min and max copied from an existing turret hardpoint) and 2 `HpTorpedo_X_01..02` (fixed) to a **copy** of `rh_battleship.cmp`, at positions on the hull surface. Pick positions by mirroring existing hardpoints with offsets, read via `list_hardpoints`.

Add a new shiparch entry, e.g. `fcm_spk_rh_battleship` (`fcm_` prefix, CONVENTIONS §2), and a solararch entry pointing `DA_archetype` at the copied model in a **lane-only overlay folder generated at deploy time** (`$FLMOD_LOCAL/gen/…` → lane). The modified `.cmp` is derived from game data: never commit it. Spawn it with a loadout that mounts turrets on the new hardpoints.

**Pass:**

- turrets render at the new positions, on the hull rather than floating (vision rubric: "turrets sit on the hull surface");
- they fire;
- they take damage;
- the explosion on death doesn't crash.

R4 §A1.4 #4: collision groups whose blown-off parts lack hardpoints crash on dock or inventory. Keep the new hardpoints on the **root** part.

### E4: Capital shield

1. Mount a shield generator on a capital ship and on a solar. Find a large shield in `DATA/EQUIPMENT/st_equip.ini`/`misc_equip.ini`. If none suits, define a new `[ShieldGenerator]` with a large `max_capacity` in an overlay equipment file, and a matching `hp_type` on the hardpoint.
2. Vanilla capitals have no `hp_type` entries for player equipment (R3 §4.1). Add one in the spike shiparch copy.

**Pass:** the shield bubble renders, absorbs damage (`GetShieldHealth`), regenerates, and survives save/load respawn.

### E5: NPC munition tracking

Give an NPC carrier a missile launcher or turret. Capital missile turrets exist on cruisers (R3 §4.2: `li_cruiser` has "2 missile turrets").

1. Detect each munition fired by **that** carrier:
   - Track A: FLUF `OnCommonCGuidedInit` / Guided hooks, with the owner id (R1 §1.3).
   - Track B: poll for new CGuided objects owned by the carrier, or hook the guided create path. Study `refs/FLUF/FLUF/Source/*Guided*`.
2. Count the launches.
3. When our stock reaches 0, stop the launcher. Try, in order:
   - (a) deactivate the equipment (`IObjRW` activate-equip false);
   - (b) swap to a loadout without launchers (respawn);
   - (c) remove the launcher's ammo from cargo.

**Pass:** launches are counted exactly against an independent count from screenshots or logs, and the launcher stops when the stock is exhausted.

Also check whether NPC launchers consume ammo items from cargo by themselves: count the cargo before and after.

### E6: Torpedo launchers on a capital

Mount a player torpedo launcher on a capital hardpoint, either vanilla or one added in E3. Find torpedo equipment in `weapon_equip.ini`.

**Pass:** the NPC AI fires it at a large target, e.g. a hostile gunboat or cruiser. Record whether the AI's gun-use logic triggers torpedoes at all.

### E7: Retrofit timing

Change a Stopped carrier's loadout by despawning and respawning the solar at the same position with the new loadout, while the player is (a) undocked nearby and (b) docked aboard.

**Pass:** no crash, and the player sees the change. When docked, the base must stay valid, because Stopped solars are the dock target. Use S-BASE's FINDINGS recipe for the dockable solar and base binding, read from `state/reports/S-BASE-a<n>.md` / `spikes/s_base/FINDINGS.md`. Never relocate or ForceLand the docked player (known crash class).

## Context pack

- `docs/plan/CONVENTIONS.md` §1, §2, §12 (authoritative; game-data hygiene)

- `docs/plan/DESIGN.md` §4 (D-4.2–4.5), §5 (D-5.2, D-5.3), §8 (D-8.6)
- `$FLMOD_RESEARCH/R3-game-data.md` §4 (capital shiparch, loadouts, turret counts, solar archetypes), §5
- `$FLMOD_RESEARCH/R2-engine-api.md` §1 (spawning), §6 (combat helpers)
- `$FLMOD_RESEARCH/R1-fluf.md` §2.6 (ResourceManager)
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §A1.4 #4, #6, and §A3.5 (Librelancer tools)
- The P0-DATATOOLS deliverables (`tools/fltools/README.md`)
- `refs/FLUF/FLUF/Source/Server/ResourceManager.cpp`, `refs/Freelancer-Decomp/src/Common/*` (Loadout, EquipDescList)

## Ownership

- **Owns:** `spikes/s_loadout/`.
- **Must not touch:** `tools/fltools/` (report bugs; don't fix them here), `spikes/track_*`, `harness/`, `docs/plan/`, `state/`.

## Contract

- **Provides:**
  - `FINDINGS.md`;
  - an upgrade-strategy recommendation: runtime loadouts vs pre-generated variants vs discrete per-slot packages;
  - the hardpoint-addition recipe, with constraints;
  - the munition-enforcement recipe;
  - proposed `EF-LOAD-*` facts.

## Tasks

E1 → E2 → E3 → E4 → E5 → E6 → E7.

## Acceptance

Every experiment has a verdict and evidence, and the strategy recommendation is justified. Reviewers re-run E1 (or E2), E3 and E5.

## Engine facts to rely on / verify

- **Verify:** runtime loadout creation on the track; client rendering of added hardpoints; capital shields; munition tracking.
- **Rely on:**
  - loadouts must exist before spawn;
  - an engine is required in NPC loadouts;
  - archetype init order matters for MP only: append files after existing ones (R3 §1.1).

## Pitfalls

- A loadout referencing a hardpoint the model lacks is a crash class. Validate with `fltools.validate`.
- Bad loadout crashes: server.dll 0x17f38, common 0x9143 (R4 §A1.4 #6).
- Never edit original `.cmp` files. Copies only, in lanes.

## Fallbacks and degrade path

| Experiment fails | Fallback |
|---|---|
| E1 | E2 (pre-generated variants). If the combinatorics explode, discrete per-slot packages (BUILD_PLAN §8). |
| E3 | Use only models with enough native hardpoints; classes needing more mounts get a different look |
| E5 | Model munitions as an operating-cost stock consumed per engagement minute, and disable launchers via a loadout swap when empty (BUILD_PLAN §8) |
| E4 | No shield upgrade; record DEGRADED scope |

## Report

AGENT_BRIEF_TEMPLATE format plus `FINDINGS.md` and the strategy table.

## Gate-time addendum

(Orchestrator: track, lane(s), attempt, commit trailer.)
