# W2-LOADOUT: Runtime carrier loadouts, hardpoint models, munition economy

- **Type:** impl
- **Wave:** 2 (sub-wave 2a, CONVENTIONS §8)
- **Depends on:** ARCH-1 (uses S-LOADOUT facts)
- **Unblocks:** W2-YARD (install effects), W2-CARRIER-GAME (solar loadout), W3-ESCORT (ship-form loadout), W3-LOSS (stocks to drop), M1-PLAYTEST

## Goal

A carrier's installed upgrades become its real in-game equipment:

- turrets, missile and torpedo launchers, shield generator, engine, plating;
- the same composition applies to its solar form and its ship form;
- hardpoints are added to copies of vanilla models where a class needs more mounts than the model has;
- the carrier's own munitions and nanobots are consumed in use, so "expensive to operate" is real (D-8.6).

## Requirements

- **REQ-W2-LOADOUT-1** (D-5.2, D-5.3): **loadout composer.** From (look, class, tier, installed upgrades), produce an equipment list mapped to hardpoints:
  - turrets by family and Mk;
  - launchers, shield generator, engine, plating (via `armor_scale` equipment or hit-point scaling);
  - FX equipment the vanilla capital loadouts carry (engines FX, `weapon_platform_tower1`, etc.).

  Slot rules come from `data/carriers` and `data/yards` (W1-CARRIER-DESIGN). The composer is engine-free and host-tested.
- **REQ-…-2:** **apply at runtime** with the mechanism S-LOADOUT proved, chosen in this order:
  1. **Runtime loadout creation.** FLUF `ResourceManager::CreateNewLoadout(nick, items)` on Track A, or the S-LOADOUT-proven Common.dll loadout construction on Track B. The new loadout id is used for the solar's and the ship's `loadoutId`.
  2. **Pre-generated variants** (BUILD_PLAN §8 fallback). `gen/models` plus a generator emit loadouts for the combinations the yards can produce, compressed by slot templates (each slot category × Mk). If the combination count exceeds the threshold S-LOADOUT recorded, limit retrofit to discrete per-slot packages and log a decision.
- **REQ-…-3** (D-4.4): **hardpoint models.** For each look × class that needs more mounts than the vanilla `.cmp` has, `gen/models/` produces a modified copy of the vanilla model at deploy time:
  - read from the local install with `tools/fltools` UTF read/write;
  - add `Hp*` hardpoint nodes (position and orientation on the hull surface, typed for turret, launcher or torpedo use, sized correctly);
  - write it into the overlay with a new archetype file reference.

  **Never commit model files** (check_public). Hardpoint layouts live in YAML under `gen/models/layouts/*.yaml`, which we author.
- **REQ-…-4** (D-8.6, D-4.2): **munition tracking.** The carrier's missiles and torpedoes are a finite stock in its inventory (W1-INVENTORY).
  - Every launch by a carrier launcher decrements the stock. Detect it with the S-LOADOUT-proven hook: guided-munition creation with owner = carrier, or a fire event.
  - At zero stock the launchers stop firing: equipment deactivation, or a loadout swap to "launchers empty" if deactivation isn't possible.
  - Resupply (W2-CARRIER-UI quartermaster, W2-YARD) re-enables them.
- **REQ-…-5** (D-8.1): **nanobot stock.** The carrier's nanobots are an inventory stock consumed by the W2-REFLEX carrier policy. This package exposes `consume(nanobots, n)` hooks and the healing amount per nanobot, consistent with the vanilla `ge_s_repair_01` heal value (read from data).
- **REQ-…-6** (D-8.2): **shield generator upgrade.** Mounts a capital shield on the solar and ship forms by the S-LOADOUT-proven method.
  - The shield value comes from data.
  - If S-LOADOUT proved capital shields impossible on NPC objects, implement shields as damage absorption in the damage hook (a shield pool regenerating over time), and log a decision.
- **REQ-…-7:** **validation.** Every produced loadout has an engine and valid equipment for its hardpoints, and passes the W1-DATA validator. Invalid combinations are refused at configure time (W2-YARD), never at spawn.
- **REQ-…-8:** **re-spawn on change.** A loadout change on a Stopped carrier triggers a despawn and respawn of its solar (via the W2-CARRIER-GAME executor), with the hull fraction preserved.
- **REQ-…-9:** devbridge (CONVENTIONS §4; registered by this package in the `carrier.*` namespace):
  - `carrier.loadout <id> show|apply`;
  - `carrier.loadout spawn_test look=<l> class=<c> tier=<t> [upgrades=<a,b>] form=solar|ship near=player|<x,y,z> tag=<t>`: **test-only**. Spawns a carrier-form object with the composed loadout through the W1-SPAWN service, with no carrier record. This lets this sub-wave-2a package test in game before W2-CARRIER-GAME (2b) exists.
  - `carrier.resupply <id|tag> <missiles|torpedoes|nanobots> <n>`: sets the stock; test and quartermaster backend.

  Events: `ev=loadout.applied`, `ev=loadout.munitions type= left=`, `ev=loadout.launchers enabled=0|1`.

## Context pack (read before writing code)

- `CLAUDE.md`
- `CONVENTIONS.md` (all; §2 `fcm_` nicknames, §4 devbridge, §8 sub-waves and DEFERRED, §12 game-data hygiene)
- `DESIGN.md` §4, §5, §8
- `TESTING.md` §Scenarios, §Vision, §Metrics
- `state/ENGINE_FACTS.md`: all S-LOADOUT entries (runtime loadout, CMP hardpoints, shields on NPC, munition tracking, launchers)
- `docs/design/CARRIERS.md` and `data/carriers/`, `data/yards/` (W1-CARRIER-DESIGN)
- Contracts: inventory, carrier model, spawn service, platform (fire / guided events), data generator plugin interface (W1-DATA)
- `local/research/R3-game-data.md` §4.1–4.3 (capital shiparch, turret hardpoints per model: Liberty 10, Bretonia 12, Kusari 18, Rheinland 21, Osiris 8; solar archetypes; loadout names), §5 (nanobots `ge_s_repair_01`, price 200)
- `local/research/R3-data/capital_ships.json` (`capital_turret_guns`, collision groups)
- `local/research/R1-fluf.md` §2.6 (`CreateNewLoadout`)
- `local/research/R2-engine-api.md` §6 (`use_item`, health), §7
- `local/research/R4-lore-and-testloop.md` §A1.4 item 4 (collision groups and hardpoints crash), §A3.5 (Librelancer UTF tools)

## Ownership

- **Owns:** `src/game/loadout/`, `gen/models/`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/game/loadout/tests/`, `src/game/loadout/scenarios/`, and `gen/models/tests/` (pytest via `$FLMOD_VENV`).
- **Game-data hygiene** (CONVENTIONS §12): model copies and any values read from vanilla models or loadouts are produced at deploy time into the overlay or `$FLMOD_LOCAL`, never committed. Golden files derived from game models go in `$FLMOD_GOLDEN`.
- **Reads:** `src/contracts/`, `src/logic/economy/`, `src/logic/carrier/`, `data/`, `tools/fltools/`, `gen/framework/`
- **Must not touch:** everything else

## Contract

- **Consumes:** carrier data tables, the yard catalog, the inventory API, the spawn and executor services, platform fire/guided events, the generator plugin interface.
- **Provides:**
  - `LoadoutService`: compose, apply, current-loadout query, consume hooks;
  - the munition-depletion events;
  - the `gen/models` generator plugin;
  - the overlay files (deploy time).

## Tasks

1. Engine-free composer plus host tests.
2. The runtime apply path, or the variant generator (per S-LOADOUT).
3. `gen/models` hardpoint generator with authored layouts; round-trip tests (parse back, node count, transforms).
4. Munition tracking, depletion and re-enable.
5. Shield generator (native, or the absorption fallback).
6. Devbridge commands and scenarios.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:**
  - the composer for every class × tier × a sample of upgrade sets (no slot overflow, engine always present);
  - the hardpoint generator round-trip (UTF parse of the output, expected node names and transforms);
  - munition accounting.
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `loadout_turrets_fire` | `carrier.loadout spawn_test look=rh class=dreadnought tier=core form=solar …` with a maximal turret loadout, and hostile targets spawned (`spawn <npc_def> 4 near=… tag=h`). **Expect** turret fire events from ≥ 90 % of mounted turrets within 60 s (HARNESS counts); screenshot + vision: "turrets visible on the hull, no floating turrets far from the hull". |
  | `loadout_added_hardpoints` | For each look with generated hardpoints: spawn, screenshot from 3 angles. Vision rubric: turrets are attached to the hull surface; no turret is inside the hull or floating more than one hull-width away. |
  | `loadout_munitions_deplete` | `carrier.resupply <tag> missiles 10`, fight. **Expect** `ev=loadout.munitions type=missile left=0` and no further launches (0 guided objects with owner = carrier for 30 s); `carrier.resupply <tag> missiles 50` restores firing (`ev=loadout.launchers enabled=1`). |
  | `loadout_shield` | Install the shield generator. **Expect** incoming damage hits shields first (HARNESS damage events show the shield pool falling before hull). |
  | `loadout_change_respawn` | `DEFERRED(W2-CARRIER-GAME)`: needs a real carrier record and dock. `carrier.buy …` then `carrier.loadout <id> apply` after changing upgrades on the Stopped carrier. **Expect** the solar respawns, hull fraction preserved ±1 %, the dock still works. It runs in the wave-2 integration pass. |

- **Metrics:** with a maximal-loadout carrier in a fight, the frame-rate floor from TESTING §Metrics still holds. Measure under `harness/lane.sh acquire --perf` (CONVENTIONS §7); thresholds come from `harness/metrics_targets.yaml`. No new FLSpew errors.
- **Negative tests:**
  - an upgrade without a free slot (refused before spawn);
  - a missing model file in the overlay (deploy-time validator error, not a crash).

## Engine facts to rely on / verify

- S-LOADOUT decides: runtime loadouts (yes/no), CMP hardpoint additions work in game (yes/no), NPC munition consumption (yes/no), NPC shields (yes/no).
- R4 §A1.4: a collision group whose blown-off part lacks hardpoints crashes on dock or inventory. Don't add hardpoints to destructible sub-parts.

## Pitfalls

- An NPC loadout without an engine crashes (`server.dll 0x2247f`).
- Loadout and equipment hardpoint-type mismatches can crash. Validate `hp_type` compatibility from equipment data.
- Model copies must keep their original material and texture references; only hardpoint nodes are added.

## Fallbacks and degrade path

1. **Pre-generated variants** (REQ-2.2).
2. **Munitions:** model them as an operating-cost stock consumed per engagement minute, with launchers disabled by loadout swap when empty (BUILD_PLAN §8).
3. **Shields:** damage-absorption pool (REQ-6).
4. **Degraded:** upgrades change only stats (hull, hold, speed, bays), not visible mounts. Flag `loadout.visual_mounts = false`.

## Report (the agent's final message)

Per the template. Include, per look, the hardpoint count added, and which apply path you used.

## Gate-time addendum

Track, S-LOADOUT results, contract paths, lanes, attempt and prior notes.
