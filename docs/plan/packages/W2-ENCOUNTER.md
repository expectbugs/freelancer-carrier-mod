# W2-ENCOUNTER: Shared encounter system

- **Type:** impl
- **Wave:** 2 (sub-wave 2a, CONVENTIONS §8)
- **Depends on:** ARCH-1
- **Unblocks:** W3-AMBUSH, W3-NOMAD, W4-ESCALATION-*, M1-PLAYTEST (proof event)

## Goal

One reusable system that answers "spawn this group of enemies here, under these conditions":

- it can freeze a fight (persisting it in the save) and thaw it later exactly as it was;
- it reports win or loss to outcome hooks.

Ambushes, the Nomad boss and endgame escalation all build on it. This package also ships one **first escalation proof event** that exercises the whole pipeline end to end.

## Requirements

- **REQ-W2-ENCOUNTER-1** (D-10.1): **definition.** "faction, ship list, loadouts and size of the group".
  - An `EncounterDef` in `data/encounters/*.yaml` gives:
    - id, faction rep group;
    - members, either as `{npc: <npcships nickname>}` or `{archetype, loadout, pilot, level}`, each with a count range;
    - level, formation hint, behavior (`attack_target`, `roam`, `guard_point`, `intercept_player`), optional leader.
  - A **generator** can derive members from vanilla data for a (faction, level, class mix):
    - `faction_prop.ini [FactionProps] npc_ship` lists;
    - `npcships.ini [NPCShipArch]` `npc_class` tags (`class_fighter`, `d<N>`, `CRUISER`, `battleship`);
    - encounter templates (`MISSIONS/ENCOUNTERS/*.ini`: `ship_by_class`, `formation_by_class`).

    The unused navy capitals `li_n_dreadnought_d25`, `li_n_cruiser_d22`, `br_n_battleship_d25`, `br_n_destroyer_d22`, `ku_n_battleship_d25`, `ku_n_destroyer_d22`, `rh_n_battleship_d25`, `rh_n_cruiser_d22` are available to it.
- **REQ-…-2** (D-10.2): **trigger.** "The condition that starts it, e.g. an ambush roll, entering a zone, an escalation stage."
  - Trigger types: `manual` (API call), `zone_enter` (player in zone or sphere), `system_enter`, `stage` (flag or predicate from the escalation model), `proximity_frozen` (player within R km of a frozen instance **and not in cruise**, D-9.6, default R = 8 km), `predicate` (callback).
  - Triggers are evaluated on the game-time tick, throttled to about 4 Hz.
- **REQ-…-3** (D-10.3): **placement.** "Where the group appears relative to the player or the carrier."
  - Anchors: player, an object id, a point, a carrier id.
  - Distance ring [min, max], bearing options (ahead, behind, random), and spread.
  - Every member position must be ≥ hazard buffer from planets, suns, fields, death and exclusion zones (W1-WORLD), and outside docking rings.
- **REQ-…-4** (D-10.4): **persistence.** "A saved, frozen state, so a fight can wait, as with paused distress calls."
  - A running instance can be **frozen**:
    1. snapshot every live member (def member id, archetype, loadout id, hull fraction, shield fraction if any, position relative to the anchor, orientation, alive flag);
    2. snapshot the protected object (carrier hull);
    3. despawn the members (Vanish);
    4. store the instance in the per-save JSON section `encounters`.
  - **Thaw** respawns the survivors at their relative positions with restored health, re-applies AI and attitudes, and resumes.
  - Destroyed members stay destroyed.
- **REQ-…-5** (D-10.5): **outcome hooks.** "What happens on a win or a loss, e.g. set the Nomad unlock flag or destroy the carrier."
  - **Win:** every hostile member destroyed, or fled more than 15 km for more than 30 s.
  - **Loss:** a protected object destroyed, or the player killed (configurable).
  - **Abandon:** the player leaves; this freezes the instance and is **not** a loss (D-1.5).
  - Hooks are registered by id and run on the next tick after the outcome.
- **REQ-…-6:** **lifecycle states** `Pending → Armed → Spawned ↔ Frozen → Resolved(win|loss)`.
  - Every transition emits `HARNESS … ev=enc.state id=… state=…`.
  - Spawning also emits `ev=enc.spawn id=… def=… n=…`.
  - Resolution emits `ev=enc.resolved id=… outcome=win|loss`. TESTING §Metrics measures fight duration from `ev=enc.spawn` to `ev=enc.resolved`.
- **REQ-…-7** (R2 fact 2): **API-spawned NPCs do not despawn by distance.** Content's 2.5 km life rundown applies only to Content NPCs, so this system must itself freeze instances when the player leaves the system (SystemSwitchOut), and must never leak spawned ships. Use the W1-SPAWN ownership registry.
- **REQ-…-8** (R4 §A1.3): **enemy clamp awareness.** Vanilla `Act_PlayerEnemyClamp = 2, 2` (common.dll 0x18C754 / 0x18C758) limits how many enemies attack the player at once.
  - Attackers whose target is the carrier must be directed at the carrier: per-member attitude via `pub::Reputation::SetAttitude`, plus `pub::AI::submit_forced_target` if S-NPC showed it works.
  - Expose a config switch for the clamp only if S-PERF documented a safe patch.
- **REQ-…-9:** **validation.**
  - Every member resolves to a valid archetype, a loadout **with an engine**, a pilot and a faction **before** any spawn (crash causes `server.dll 0x2247f`, `0x17f38`).
  - An invalid definition is rejected at load with a clear log line and is never spawned.
- **REQ-…-10** (D-13 proof): **first escalation proof event** `proof_nomad_scouts`.
  - After the campaign-complete flag (W1-CORE) is set, entering Hi02 (Omicron Gamma) spawns a Nomad scout wing: 3–4 `fc_n_no_fighter_d19` at 6–8 km from the player.
  - Defeating it sets flag `proof_nomad_scouts_done`.
  - This is a pipeline test only, behind config `encounter.proof_events = true` (default off in shipped config, on in the test profile).
- **REQ-…-11:** devbridge commands (CONVENTIONS §4, `enc.*` namespace, owned by this package):
  - `enc.define <yaml file>`: load or replace a definition (test)
  - `enc.trigger <def> [anchor=player|carrier:<id>|<x,y,z>]`: manual trigger
  - `enc.list`
  - `enc.state <id>`
  - `enc.freeze <id>` / `enc.thaw <id>`: instance-level freeze/thaw, built on the W1-SPAWN `freeze`/`thaw` tag primitives. Instance members are spawned with `tag=<instance id>`.
  - `enc.resolve <id> win|loss`: test-only forced outcome, replacing `kill_all`

## Context pack (read before writing code)

- `CLAUDE.md`
- `CONVENTIONS.md` (all; §4 devbridge and events, §8 sub-waves, §12 game-data hygiene)
- `DESIGN.md` §9 (D-9.6, D-9.8), §10, §12, §13
- `TESTING.md` §Devbridge, §Scenarios, §Soak, §SaveCompat
- `state/ENGINE_FACTS.md`: S-NPC freeze/thaw, capital spawn, damage/destroy hooks, Nomad spawn; S-PERF clamp
- Contracts: spawn service (validated spawn, registry, freeze/thaw primitives), AI helpers, persistence, clock, events (damage, destroy, system switch), world (placement checks)
- `local/research/R2-engine-api.md` §1 (ShipInfo fields, spawn sequence, Reputation::Alloc, SubmitState with state graphs FIGHTER/GUNBOAT/CRUISER), §4.1 + §4.4 (directives, attack-by-rep), §5 (off-screen behavior), §6, §9
- `local/research/R3-game-data.md` §3 (zones, encounter templates, NPC selection chain), §8 (capital-fielding factions, CD carriers)
- `local/research/R3-data/encounter_templates.json`, `factions.json`
- `local/research/R4-lore-and-testloop.md` §A1.1 content.dll rows, §A4.7
- Reference code: `/home/user/freelancer/refs/FLHook-4.0-locked/plugins/npc_control/NPCControl.cpp` (190–285 spawn, `CheckNpc`), `/home/user/freelancer/refs/DiscoveryFLHook/Plugins/Public/dronebays/` (attack by rep)

## Ownership

- **Owns:** `src/logic/encounter/`, `src/game/encounter/`, `data/encounters/`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/logic/encounter/tests/` and `src/game/encounter/scenarios/`.
- **Game-data hygiene** (CONVENTIONS §12): committed YAML references vanilla NPCs **by nickname only**. Lineup tables derived from `faction_prop`/`npcships`/encounter templates are generated at deploy time into `$FLMOD_LOCAL/gen/encounter_tables.json`, via a W1-DATA generator plugin under `gen/plugins/encounter/`. They are never committed, and host-test goldens built from them live in `$FLMOD_GOLDEN`.
- **Also owns:** `gen/plugins/encounter/`.
- **Reads:** `src/contracts/`, `src/logic/world/`, `src/game/spawn/`, `src/game/ai/`, `src/game/core/`, `$FLMOD_RESEARCH/R3-data/` (absolute path; reference only)
- **Must not touch:** everything else; `data/encounters/nomad/` is reserved for W3-NOMAD

## Contract

- **Consumes:** spawn service, AI helpers, events (`OnShipDestroy`, damage, `SystemSwitchOut`, `JumpInComplete`, cruise state), persistence, world placement, clock, flags.
- **Provides:** the encounter API (define, spawn, freeze, thaw, query, outcome-hook registry, trigger registry), the persistence section `encounters`, the definition YAML schema (its home is `docs/spec/data_schemas.md`, owned by the ARCH packages; propose additions in your report), the lineup generator API (faction, level, class mix → members), used by W3-AMBUSH.

## Tasks

1. Definition schema and loader with validation; lineup generator from vanilla data (via the deploy-time `$FLMOD_LOCAL/gen/encounter_tables.json` produced by your `gen/plugins/encounter/` plugin).
2. Instance state machine and trigger evaluation.
3. Placement solver with hazard checks.
4. Spawn: allocate a rep group per instance (or use the faction group) and apply attitudes; then freeze and thaw.
5. Outcome detection, and the hook registry on the next tick.
6. Persistence section, save/load reconstruction, cleanup on load (despawn stale objects).
7. Devbridge commands; the proof event.
8. Scenarios.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:**
  - YAML schema validation, including bad definitions;
  - the generator picks d-level-appropriate ships for `fc_c_grp` d17, `li_n_grp` capital mix and `fc_n_grp`;
  - the placement solver avoids every hazard in fixture worlds;
  - the state machine for all transitions;
  - outcome rules;
  - freeze snapshot round-trip.
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `encounter_spawn_and_win` | Fixture `HARNESS_endgame_eagle`, `launch`, `godmode on`. `enc.trigger <fc_rh test def> anchor=player`, then `enc.resolve <id> win` (and once by actually killing them). **Expect** `ev=enc.resolved outcome=win` and the hook fired. |
  | `encounter_freeze_thaw` | Spawn 4 attackers, damage 2 to 50 %, `enc.freeze <id>`. **Expect** members despawned (registry empty). Save, reload, move away 20 km, return to within 8 km and drop cruise. **Expect** `state=Spawned` with 2 at ≈50 % hull (±2 %) and positions within 300 m of the snapshot. |
  | `encounter_leave_system_freezes` | Spawned instance, player jumps out. **Expect** `state=Frozen` and no leaked objects (registry count 0). |
  | `encounter_capital_lineup` | Spawn a generated lineup with a `rh_n_battleship_d25`. **Expect** capital visible (screenshot + vision "a capital warship is visible") and it attacks a designated target (HARNESS damage events). |
  | `encounter_proof_event` | Fixture `HARNESS_endgame_eagle` (post-campaign), `system Hi02`, with proof events on. **Expect** the scouts spawn; win sets the flag; the flag persists across save/load. |
  | `encounter_invalid_def` | Malformed definition. **Expect** a load-time rejection log and no spawn, no crash. |

- **Soak:** 20 freeze/thaw cycles plus 10 save/load cycles in one session; no crash, no object leak, steady address space (§Soak metrics).
- **Negative tests:**
  - thaw while the anchor carrier was destroyed;
  - thaw inside a hazard (placement must relocate);
  - F1 pause during an active fight.

## Engine facts to rely on / verify

- R2 fact 1: systems without the player aren't simulated.
- R2 fact 2: API NPCs don't time out.
- R4 pitfall 4: an NPC destroyed right after spawn with script logic attached crashes in single player (`Freelancer.exe 0x14661b`), so never destroy within the spawn tick.
- Verify the hostility semantics of `pub::Reputation::SetAttitude` per member (S-NPC).

## Pitfalls

- Every faction in a vanilla *patrol encounter* must exist in the base's `[BaseFaction]`. We spawn via the API, not vanilla encounters, so this doesn't apply, but don't add vanilla zone encounters.
- Formations above 17 ships crash vanilla encounters; we don't use vanilla formations, but keep group sizes sane (≤ 20 per instance by default; larger only in escalation, with S-PERF data).
- Loot from API NPCs isn't filtered by lootprops (R2 fact 9). Attackers should carry sane cargo: strip mission-only items, keep vanilla-like drops.

## Fallbacks and degrade path

- If thaw positioning relative to a moving anchor misbehaves, thaw at the anchor's current position plus the stored offsets, re-solving placement.
- **Degraded:** no partial-fight freeze. A frozen instance restarts with its full original lineup; flag `encounter.partial_freeze = false`.

## Report (the agent's final message)

Per the template. Include the YAML schema, and a list of generator choices per faction with tested levels.

## Gate-time addendum

Track, contract paths, ENGINE_FACTS ids (S-NPC freeze/thaw, clamp), lanes, attempt and prior notes.
