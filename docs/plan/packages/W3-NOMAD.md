# W3-NOMAD: The Nomad gate (boss, unlock, Gammu yard)

- **Type:** impl
- **Wave:** 3 (sub-wave 3a, CONVENTIONS §8)
- **Depends on:** ARCH-2
- **Unblocks:** M2-PLAYTEST; the Nomad tier (W2-YARD reads the flag); W4-ESCALATION (Nomad resurgence builds on this)

## Goal

Planet Gammu, the robot planet in the "Unknown" system Ew06, won't build carriers until the player defeats a Nomad battleship with heavy support in that system. The fight:

- spawns somewhere in Ew06 while the boss is "up", and roams;
- turns to hunt the player when they start fighting Nomads there;
- comes back 4 in-game days after a defeat.

The first victory permanently unlocks the Nomad tier at the Gammu yard.

## Requirements

- **REQ-W3-NOMAD-1** (D-12.1, verbatim): "the robot planet won't build one until you defeat a Nomad battleship with heavy support at a set location in that system. Winning sets a flag on your character that unlocks the purchase."
  - Adam's refinement: "can be anywhere in the system but if the player is there fighting nomads, it will seek them out if it's up."
  - Flag `nomad_gate_unlocked` is persisted in the per-save JSON and **mirrored inside the `.fl`** (W1-CORE flag mirror, D-14.1). W2-YARD reads it.
- **REQ-…-2** (D-12.2): **group.**
  - Nomad battleship: shiparch `no_battleship`, 69,300 hp, `nomad = true`; loadout patterned on `MSN13_Nomad_Battleship` (15 × `nomad_turret01_mark01` on `Hp_1_xx`, `cloak_nomad_battleship`, `fx_Nomad_battleship_engine`).
  - 2 Nomad gunboats: `no_gunboat`, pattern `MSN12_Nomad_Gunboat` (6 Nomad turrets plus cloak).
  - 8 Nomad fighters: `fc_n_no_fighter_d19`.
  - The battleship and gunboat NPC definitions **must be new global** `[NPCShipArch]` entries plus pilots. Vanilla has them only in `MISSIONS/M10|M12|M13/npcships.ini` and `pilots_story.ini` (R3 §2.4).
  - W1-DATA owns the generator for global NPC definitions, and is specified to include "Nomad boss NPC definitions". **Verify they exist in the deployed overlay.**
  - If they're missing, add a generator plugin `gen/plugins/nomad/` (owned here). At **deploy time** it reads the local install's mission files (`MISSIONS/M12|M13/npcships.ini`, `pilots_story.ini`, `SHIPS/loadouts_special.ini`) and emits global `fcm_`-prefixed `[NPCShipArch]`, pilot and loadout entries into the overlay.
  - **Game-data hygiene (CONVENTIONS §12):** never copy their field values into committed YAML or code. Committed `data/encounters/nomad/*.yaml` references nicknames only.
  - Do **not** use the `d_n_battleship` solar (mission satellite); the boss must move.
- **REQ-…-3** (D-12.3): **spawn and roam.**
  - When the player is in Ew06 and the boss is up, spawn the group at a random safe point in Ew06 (W1-WORLD placement):
    - ≥ 12 km from the player's entry point;
    - outside the Gammu death zone (planet radius plus 2,100 m death zone, exclusion 5,000 m around `Ew06_robot_planet` at (20162, 0, 13301)), Primus (`Ew06_01_Base`, planet at (−11286, 0, 9603)) and other hazards;
    - inside the system's Nomad zone `Zone_Ew06_radiation` (sphere r = 50,000 at (463, 0, 485)).
  - The group roams between random waypoints in that zone (formation: escorts around the battleship).
  - Despawn and freeze when the player leaves Ew06, via the W2-ENCOUNTER freeze/thaw.
- **REQ-…-4** (D-12.3): **seek.** "If the player engages Nomads in Ew06" (any damage exchanged between the player or the player's wingmen and an `fc_n_grp` ship in Ew06), the boss group switches to **intercept**:
  - Goto the player's position, refreshed every 10 s, closing at the group's speed.
  - Once within 6 km, attack.
  - Ambient Nomads from the vanilla `area_nomads` encounters count as engagement.
- **REQ-…-5** (D-12.4): **respawn.**
  - After a defeat (battleship destroyed), the boss is "down" for **4 in-game days** of game time, using `universe.ini [Time] seconds_per_day = 1800` (so 4 days = 7,200 s game time). Persist the timer.
  - Escorts left alive when the battleship dies stay hostile until killed or the player leaves.
  - Repeat victories don't re-unlock anything, and may grant a reward from data (W1-CARRIER-DESIGN optional).
- **REQ-…-6:** **unlock UX.** On the first victory:
  - an NN/popup message: "Planet Gammu's foundries answer your victory" (text-service string);
  - the flag is set and persisted (a save checkpoint is recommended);
  - the next Gammu dock shows the yard offers (W2-YARD REQ-7).
- **REQ-…-7** (D-6): **Gammu yard data.**
  - The Gammu yard catalog and classes live in `data/yards/` (W1-CARRIER-DESIGN).
  - This package verifies that Gammu (`Ew06_02_Base`) is configured as a yard and that its base-menu entry works there (planetscape room `Pl_09_pad`, bar `li_05_bar` THN, NPCs affiliated `fc_or_grp`; R3 §2.4).
  - If Gammu needs base-data additions (e.g. a missing room behavior), file them as `FIX` for W1-DATA.
- **REQ-…-8:** **access.** Ew06 is reachable only via `Hi02_to_Ew06_hole` (Hi02 at (24336, 0, −44216); arrival `Ew06_to_Hi02_hole` at (3882, 0, 19991)). No new links are created.
- **REQ-…-9:** **escalation hook.** Expose "Nomad boss defeated" events for W4-ESCALATION (Nomad resurgence) through the encounter outcome hooks.
- **REQ-…-10:** devbridge (CONVENTIONS §4, `nomad.*`):
  - `nomad.state`, `nomad.spawn_now`;
  - `nomad.engage_test`: deal 1 damage to the nearest `fc_n` ship;
  - `nomad.kill_boss` (test);
  - `nomad.set_down_until <gametime>`.

  Events: `ev=nomad.state state=up|down|spawned|seeking|defeated unlocked=0|1`, `ev=nomad.seek dist=<m>` (every 10 s while seeking), `ev=nomad.unlocked`.

## Context pack (read before writing code)

- `CLAUDE.md`, `CONVENTIONS.md` (all; §2 flag names, §4, §8, §12)
- `DESIGN.md` §4.1, §6, §12
- `TESTING.md` §Scenarios, §M2, §Vision, §Metrics (boss fight duration band)
- `state/ENGINE_FACTS.md`: S-NPC (Nomad battleship and gunboat spawn, capital AI), freeze/thaw
- Contracts (ARCH-2): Nomad boss, encounter (definition, triggers, behaviors, outcome hooks), flags, world placement, notifications
- `local/research/R3-game-data.md` §2.4 (Gammu and Ew06 evidence, coordinates, zones, boss assets), §4.1–4.2 (Nomad ships, loadouts), §8 (Nomads in free play)
- `local/research/R3-data/systems_full.json` (Ew06 objects and zones), `capital_ships.json`
- HDE data, read-only: `DATA/UNIVERSE/SYSTEMS/EW06/ew06.ini`, `DATA/MISSIONS/M13/npcships.ini`, `M12/npcships.ini`, `pilots_story.ini`, `SHIPS/loadouts_special.ini`

## Ownership

- **Owns:** `src/game/nomad/`, `data/encounters/nomad/`, `gen/plugins/nomad/`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/game/nomad/scenarios/`
- **Reads:** `src/contracts/`, `src/logic/encounter/`, `src/game/encounter/`, `src/game/*`, `data/`
- **Must not touch:** everything else

## Contract

- **Consumes:** the encounter API (definition, trigger `system_enter`/`predicate`, intercept behavior, freeze/thaw, outcomes), the flags service, damage events, the clock, notifications, world placement.
- **Provides:** the Nomad boss controller, the flag `nomad_gate_unlocked`, the events `nomad_boss_defeated` / `nomad_boss_respawned`, devbridge commands.

## Tasks

1. Encounter definition `data/encounters/nomad/boss.yaml` (+ NPC definitions if needed per REQ-2).
2. Controller: up/down timer, spawn-on-entry, roam waypoints, engagement detection, seek mode.
3. Outcomes: unlock, respawn timer, messages.
4. Verify the Gammu yard; scenarios.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:** the timer math (seconds_per_day 1800 × 4); the engagement-detection predicate; the placement constraints for Ew06 (fixture world).
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `nomad_spawn_roam` | Fixture `HARNESS_ew06_space` (endgame Eagle near the Hi02 hole arrival). **Expect** `ev=nomad.state state=spawned` at ≥ 12 km; the group moves (positions change over 60 s); **[vision]** at close range: "a large alien/organic-looking capital ship with escorts". |
  | `nomad_seek_on_engagement` | `nomad.engage_test` far from the boss. **Expect** `state=seeking`; `ev=nomad.seek dist=` decreases monotonically over 90 s; arrival within 6 km. |
  | `nomad_defeat_unlocks` | `nomad.kill_boss`. **Expect** `unlocked=1`, a message shown; save, reload → `unlocked=1`; the `.fl` contains the mirrored flag line; dock at Gammu → Yard offers visible. **[vision]** "the Carrier Yard lists carriers for sale". |
  | `nomad_respawn_4_days` | After defeat, `time.skip 7100` → still down; `time.skip 200` → up; re-enter Ew06 → spawns again; a second kill doesn't re-trigger the unlock message. |
  | `nomad_real_fight` | **Unassisted**: godmode off, no devbridge weakening. `HARNESS_ew06_space` (Nomad-gunned Eagle; wingmen if available) fights the boss for real (playbot flies via autopilot/attack orders). **Measure** fight duration and the player death rate over 3 runs (target band TESTING §Metrics / `harness/metrics_targets.yaml`: 5–12 min). The result is informational unless far outside the band; then propose tuning. |
  | `nomad_leave_freeze` | Leave Ew06 mid-fight. **Expect** the boss frozen with its damage preserved on return. |

- **Negative tests:** the player dies to the boss (the flag stays unset; the boss respawn rules are unaffected); saving during seek; entering Ew06 while the boss is down (nothing spawns).

## Engine facts to rely on / verify

- S-NPC: `no_battleship`/`no_gunboat` spawn validity outside missions (cloak equipment, Nomad material FX), capital AI pursuit.
- Nomad ships' `nomad = true` hull-hit effects (HDE changed shiparch Nomad hull-hit effects; R3 §9).

## Pitfalls

- Mission-only pilots and loadouts referenced from global NPC definitions must exist in global files, or they crash (invalid pilot or loadout). Validate with the W1-DATA validator.
- The Nomad cloak equipment may leave the battleship cloaked. Ensure it decloaks to fight (S-NPC check), or omit the cloak.
- Gammu's death zone is lethal. Never place or path through it.

## Fallbacks and degrade path

1. If `no_battleship` can't be spawned as a ship outside missions, use the closest valid Nomad capital form proven by S-NPC (e.g. the `d_n_battleship` solar plus mobile escorts) and log a decision. Seek is then done by the escorts only.
2. **Degraded:** a fixed spawn location (a set point in the Nomad zone) without seek behavior.

## Report (the agent's final message)

Per the template, with fight measurements and screenshots.

## Gate-time addendum

Contracts, S-NPC Nomad facts, data status of the Nomad NPC definitions, lanes, attempt and prior notes.
