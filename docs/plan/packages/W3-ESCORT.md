# W3-ESCORT: Escort travel (the carrier as a real NPC capital ship)

- **Type:** impl
- **Wave:** 3 (sub-wave 3a, CONVENTIONS §8)
- **Depends on:** ARCH-2
- **Unblocks:** M2-PLAYTEST, W4-WINGMEN (escort duty), W3-AMBUSH escort path (runtime integration)

## Goal

Ordered from the player's own ship nearby, the carrier undocks from its parked state and **flies as a real NPC capital ship** along its route while the player escorts it:

- it approaches jump gates, plays the activation and appears on the far side as the player comes through;
- when the player leaves, it switches to simulation and keeps travelling on paper;
- when the player returns, it reappears where the math says;
- Stop turns the moving ship back into a dockable base.

## Requirements

- **REQ-W3-ESCORT-1** (D-7.4, verbatim): "ordered from your own ship nearby, it flies as a real NPC capital ship using normal AI movement, and you escort it."
  - Accept `OrderTravel(dest, Escort)` from the in-space command panel (W2-CARRIER-UI) only within 10 km.
  - Form swap Solar → Ship (ARCH-2 carrier-forms):
    - despawn the solar;
    - spawn the ship at the same transform: our carrier shiparch for the look and class (W1-DATA / W2-LOADOUT), the same loadout composition, the hull fraction preserved, `state_graph = CRUISER` (or the S-NPC-proven graph), and a never-flee personality (`flee_when_hull_damaged_percent` ≈ 0; R2 §4.2);
    - a per-carrier rep group allied with the player.
- **REQ-…-2:** **movement.**
  - Follow the route legs from W2-CARRIER-LOGIC with `pub::AI::SubmitDirective` `DirectiveGotoOp`: `gotoType` 1 to points, or 2 with a spline through waypoint sets, `range`, `thrust`.
  - Use `goToCruise` if S-NPC showed capitals can cruise; R2 §4.3 notes `LargeShipBehavior` sets a cruise lock, so likely impulse only.
  - Waypoints come from W1-WORLD (hazard-avoiding, no trade lanes).
  - Speed: the class's escort speed from data. **Target (D-7.13):** crossing a system while escorting takes ≤ 2× the docked-travel time of that class. If engine impulse is too slow, propose the engine-force or cruise change for W1-CARRIER-DESIGN's data in the report. The orchestrator routes it as a FIX, or the tuning override `data/tuning/escort.yaml`, which this package owns.
- **REQ-…-3:** **model sync.** The live ship's position feeds back into W2-CARRIER-LOGIC (progress follows reality while live), so switching to Away continues from the real position.
- **REQ-…-4** (D-7.7, verbatim): "it flies near the gate, plays the activation, then teleports to the far side. When you're escorting, it appears as you come through."
  - At the gate or hole, the ship approaches to within the jump radius (jumpgate docking sphere 225 m, hole 150 m; R3 §2.2) and triggers the activation (S-NPC-proven: `DockRequest` on the gate, or `JumpIn` effect).
  - Then it is despawned (Vanish) and marked "beyond gate", with the model updated to the arrival point of the destination system.
  - When the player completes the jump into that system (`JumpInComplete`), spawn the ship ahead of the player near the arrival object, continuing its route.
  - If the player doesn't follow within the configured time, the carrier is Away (simulated) in the next system.
  - API NPCs don't auto-jump after docking with a gate (R2 §4.3). Never leave a ship "docked" at a gate.
- **REQ-…-5** (D-7.9): **locked links.**
  - The route must avoid player-locked links (W1-WORLD).
  - For `npc_locked_gate` links (R3 §2.2: Li01↔Li05, Bw05↔Ku06/Rh01, Rh02↔Rh04 hole b, Br03/04/05 holes…), escort mode does not rely on vanilla AI pathing. Our own gate-transition protocol (REQ-4) handles every link, so AI locks don't matter. Verify on one npc-locked link.
- **REQ-…-6** (D-7.5): **Away hand-off.** "Once you leave, it switches to simulation and keeps traveling on paper."
  - Triggers: the player leaves the system, or is > 25 km from the carrier for > 60 s (config).
  - Despawn the ship and send `PlayerLeft` to the model (→ Away).
  - When the player enters the carrier's current system (`JumpInComplete` / `SystemSwitch`) **and** comes within escort range (or any distance if config `escort.respawn_on_system_enter`), spawn the ship at the model's computed position and send `PlayerReturned` (→ EscortTravel).
  - Engine fact: systems without the player are frozen (R2 fact 1), so the model is authoritative.
- **REQ-…-7** (D-7.6, verbatim): "Stop also turns a moving real ship back into a dockable base."
  - `OrderStop` → the ship halts (`DirectiveCancelOp` plus hold), the model snaps a safe stop, then form swap Ship → Solar at the snapped point (move the ship there first if it's within 2 km; else despawn and spawn the solar at the snap point).
  - Docking is allowed again. Arrival does the same automatically.
- **REQ-…-8:** **stuck detection and own steering** (BUILD_PLAN §8; thresholds = TESTING §Metrics, the single source).
  - The escorted carrier must progress ≥ 300 m per 30 s along its route, unless in combat or turning at a waypoint. Emit `ev=escort.progress` every 30 s.
  - A 90 s stall (or heading oscillation, i.e. spin) ⇒ `ev=escort.stuck` and recovery. First re-issue the directive with a re-planned waypoint.
  - On a second stall, switch to **own steering** for that leg: the ship is moved kinematically by `pub::SpaceObj::Relocate` same-system beams in small steps at the class speed, only while the player is > 10 km away; else keep re-issuing directives.
  - Log every stall with position.
  - Also mitigate collision spin (R4 §A1.4 item 9): keep waypoints ≥ 2 km from large objects.
- **REQ-…-9:** **escort ambush integration** (D-9.5). Expose an "escort live" status to W3-AMBUSH (sub-wave 3b, built after this package), and a combat mode: on attack, cancel movement and fight (turrets engage); on win, resume the route.
  - Any hostile attack on the live ship already triggers combat mode through the `Attacked` edge (CONVENTIONS §9), so this is testable here without W3-AMBUSH.
- **REQ-…-10:** **save/load during escort.** The ship form is never saved. On load, the model state (EscortTravel or Away) is restored; if the player is in range, the ship respawns at the computed position after load.
- **REQ-…-11:** devbridge (CONVENTIONS §4):
  - Escort orders use **`carrier.escort <id> <dest>`**, registered here in the `carrier.*` namespace and listed in CONVENTIONS.
  - `escort.state <id>`
  - `escort.teleport_player_ahead <id>` (test helper)
  - `escort.force_stall <id>` (test)

  Events: `ev=escort.progress id= leg= pos= speed= mode=directive|steer`, `ev=escort.stuck id=`, `ev=escort.jump id= gate=`, `ev=escort.arrived id=`.

## Context pack (read before writing code)

- `CLAUDE.md`, `CONVENTIONS.md` (all; §4, §8, §9)
- `DESIGN.md` §7 (all, incl. D-7.13 escort speed), §9.5, §11.8
- `TESTING.md` §Scenarios, §Metrics (escort speed, stall rate), §M2, §Vision
- `state/ENGINE_FACTS.md`: S-NPC capital travel (speed, cruise), gate approach + JumpIn visuals, npc_locked links, frozen systems + respawn on return, spin/stall observations
- Contracts (ARCH-2): escort controller, carrier forms, carrier model, AI helpers, world waypoints, events
- `local/research/R2-engine-api.md` §0 facts 7–8, 12; §3 (moving table: `Relocate`, `JumpIn`, `InstantDock`); §4.1–4.3 (directives, op types, capital behavior); §5
- `local/research/R3-game-data.md` §2.2 (gate and hole kinds and radii, `npc_locked_gate` list), §4.1 (capital mass, drag, engines)
- Reference: `/home/user/freelancer/refs/FLHook-4.0-locked/plugins/npc_control/NPCControl.cpp` 455–495 (goto, follow), `/home/user/freelancer/refs/Freelancer-Decomp/src/Common/common_largeshipbehavior.cpp` 96–110, `common_pathfind.cpp`, `/home/user/freelancer/refs/Librelancer/src/LibreLancer/Server/ServerWorld.cs` 297–327 (vanilla jumpers)

## Ownership

- **Owns:** `src/game/escort/`
- **Also owns:** `data/tuning/escort.yaml`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/game/escort/scenarios/`, `src/game/escort/tests/`
- **Reads:** `src/contracts/`, `src/logic/*`, `src/game/spawn/`, `src/game/ai/`, `src/game/carrier/`, `src/game/loadout/`, `data/`
- **Must not touch:** everything else; propose W2 changes as `FIX-*`

## Contract

- **Consumes (ARCH-2):** escort controller, carrier forms (implements the Ship form if ARCH-2 assigned it here), model commands and queries, AI helpers, world waypoints, platform events (JumpInComplete, SystemSwitchOut, cruise), spawn service.
- **Provides:** the escort service, live-status queries, devbridge commands.

## Tasks

1. Ship-form spawn and despawn with the loadout and hull carry-over.
2. Leg following with directives and model sync.
3. The gate-transition protocol (with the player following or not).
4. Away hand-off and return respawn.
5. Stop conversion back to a solar.
6. Stall detection and the own-steering fallback.
7. Ambush combat-mode hooks.
8. Scenarios and metrics.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:** waypoint following math, the stall detector, the hand-off decision table (player distance and system matrix).
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `escort_in_system` | Carrier Stopped in Li01; player within 5 km orders escort to `Li01_to_Li02` (the gate). **Expect** the ship spawns at the solar position (±50 m), moves (speed ≥ 80 % of the data speed after acceleration), no stall for 10 min. **[vision]** "a capital ship moving through space with engine glow" at 2 checkpoints. |
  | `escort_through_two_gates` | Route Li01 → Li02 → Iw03 (or another two-gate route); the player follows through each gate. **Expect** at each gate `escort … mode=jump` then, after the player's `JumpInComplete`, the ship appears within 3 km ahead of the player; **[vision]** "a capital ship visible near the jump gate after arrival". |
  | `escort_player_does_not_follow` | The player stays behind at a gate. **Expect** the carrier becomes Away in the next system; later the player jumps in → the carrier is at the computed position along its leg (±1 km vs the model), state EscortTravel. |
  | `escort_leave_and_return` | Mid-route the player docks at a base in the same system. **Expect** Away after 60 s; after an undock 5 min later, the carrier has advanced 5 min × the sim speed (±5 %). |
  | `escort_stop_to_base` | Stop. **Expect** a solar at the safe snap point; docking works. |
  | `escort_stall_fallback` | `escort.force_stall <id>`. **Expect** `ev=escort.stuck`, a re-plan, then `mode=steer` with the player > 10 km away, and progress resumes. |
  | `escort_attacked_combat_mode` | `spawn <hostile npc_def> 3 near=<carrier> tag=e`. **Expect** `ev=carrier.state … state=UnderAttack`, movement cancelled, turrets engage; `despawn e` → `Won` → the route resumes (EscortTravel). |
  | `escort_dock_denied` | Dock request at the moving ship. **Expect** `ev=carrier.dock_denied reason=not_stopped` (D-7.6). |
  | `escort_npc_locked_link` | A route across one `npc_locked_gate` link. **Expect** the transition succeeds via our protocol. |

- **Metrics** (TESTING §Metrics / `harness/metrics_targets.yaml`):
  - escort stuck-detection rule (no unrecovered stall);
  - escort crossing time ≤ 2× docked-travel time for the class (D-7.13);
  - the frame-rate floor with the carrier ship live, measured under `--perf`.
- **Negative tests:** save/load mid-escort in both live and Away; F1 pause mid-gate; player death during escort (→ Away).

## Engine facts to rely on / verify

- S-NPC: capital speed, cruise behavior; gate activation visuals; `JumpIn` behavior in single player; Relocate client sync for NPCs in the player's system; spin.

## Pitfalls

- A ship spawned with an invalid loadout or engine crashes (`server.dll 0x2247f`). Validate via the spawn service.
- Never relocate the ship while the player is within visual range (> 10 km rule), except the initial spawn.
- Followers dock with their leader's dock target (R2 fact 8). Don't put the carrier ship in a Follow relationship with the player.

## Fallbacks and degrade path

1. Own steering for whole routes when directives are unreliable (log a decision).
2. **Degraded:** escort travel in-system only; system changes go through simulated docked-style travel (`escort.cross_system = false`).

## Report (the agent's final message)

Per the template, with measured speeds per class, stall counts, and gate-transition screenshots.

## Gate-time addendum

Contracts, S-NPC facts, the carrier ship archetypes in data, lanes, attempt and prior notes.
