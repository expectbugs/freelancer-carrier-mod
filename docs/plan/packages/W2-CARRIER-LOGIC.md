# W2-CARRIER-LOGIC: Carrier state machine, fleet and travel simulation (engine-free)

- **Type:** impl
- **Wave:** 2 (sub-wave 2a, CONVENTIONS §8)
- **Depends on:** ARCH-1
- **Unblocks:** W2-CARRIER-GAME, W2-CARRIER-UI, W2-YARD (fleet model), W3-AMBUSH, W3-ESCORT, W3-LOSS, M1-PLAYTEST

## Goal

Every carrier the player owns is driven by one deterministic, engine-free C++ model. The model holds a 7-state machine, the orders, a travel simulation on game time, and a versioned persistence schema, and it compiles natively on Linux so it can be tested exhaustively. Game adapters (W2-CARRIER-GAME, W3-ESCORT, W3-AMBUSH) only translate engine events into commands for this model, and the model's outputs into engine actions.

The player experiences it as: order a trip, read "two systems out, arriving in 4 minutes", stop anywhere, and find the carrier where the math says it is.

## Requirements

- **REQ-W2-CARRIER-LOGIC-1** (D-7.11): implement exactly these states: `Stopped`, `DockedTravel`, `EscortTravel`, `Away`, `AmbushWaiting`, `UnderAttack`, `Destroyed`.
  - Design text: "Every mode returns to Stopped, the only dockable state."
- **REQ-…-2** (D-7.11, CONVENTIONS §9): implement **exactly** the canonical edge table in `docs/plan/CONVENTIONS.md` §9 (it supersedes the design-doc summary), with these model commands:

  | From | To | Command (trigger) |
  |---|---|---|
  | Stopped | DockedTravel | `OrderTravel(dest, mode=Docked)` while the player is docked aboard this carrier |
  | Stopped | EscortTravel | `OrderTravel(dest, mode=Escort)` from the player's ship within 10 km (D-7.4) |
  | DockedTravel | DockedTravel | `OrderTravel(dest)` while travelling = **re-route** from the current interpolated position |
  | DockedTravel | Stopped | `Arrived` or `OrderStop` |
  | DockedTravel | UnderAttack | `AmbushRolled` (forced stop; the fight holds until the player launches, D-9.5) |
  | EscortTravel | Stopped | `Arrived` or `OrderStop` |
  | EscortTravel | Away | `PlayerLeft` (left the system, or beyond escort range for the configured time) |
  | EscortTravel | UnderAttack | `AmbushRolled` or `Attacked` |
  | Away | EscortTravel | `PlayerReturned` (same system and within escort range) |
  | Away | Stopped | `Arrived` while the player is elsewhere ("reappears at the computed spot… like any other base") |
  | Away | AmbushWaiting | `AmbushRolled` |
  | AmbushWaiting | UnderAttack | `PlayerArrived` (dropped out of cruise within 8 km; D-9.6) |
  | Stopped | UnderAttack | `Attacked` (hostiles engage the stopped carrier, or an escalation event) |
  | UnderAttack | Stopped | `Won` (all attackers destroyed or fled) |
  | UnderAttack | AmbushWaiting | `PlayerLeft` during a live fight: it freezes again ("Fights wait for you") |
  | UnderAttack | Destroyed | `Lost` (hull reaches 0; "gone for good") |
  | Stopped, EscortTravel | UnderAttack → Destroyed | `HullZero` outside a formal fight: the model emits **both** transitions in the same tick, so W3-LOSS always sees `UnderAttack → Destroyed` |

- **REQ-…-3:** no other edges. In particular, `Stopped → Stopped` and other no-op orders are rejected with a reason code, never silently ignored. The design diagram omitted several of these edges; CONVENTIONS §9 made them canonical, so they are not "implied" any more. List them in the report anyway.
- **REQ-…-4** (D-7.11): **Destroyed is terminal.** No command leaves it. The model keeps the record until W3-LOSS finishes cleanup, then removes it.
- **REQ-…-5:** **illegal commands** (e.g. `OrderStop` while `Stopped`, `OrderTravel` while `UnderAttack` or `AmbushWaiting`) return a typed `Rejected{reason}` and never change state. `OrderTravel` while `DockedTravel` is legal (re-route). Every (state × command) pair has a defined outcome, enumerated in a table-driven test.
- **REQ-…-6** (D-7.1): **orders.** `OrderTravel(dest)`, where dest is one of:
  - an in-system point (planet, base or station, gate or hole, from W1-WORLD ids);
  - an adjoining system;
  - any reachable system (multi-hop).

  The route is requested from the W1-WORLD route planner (avoiding lanes and player-locked links, D-7.9) and stored in the model as a list of legs: in-system segments, jump transits and the arrival segment.
- **REQ-…-7** (D-7.2, D-7.13): **travel simulation on game time.**
  - position(t) = interpolation along the legs at the class's simulated speed (from `data/carriers`), plus a fixed jump-transit time per jump.
  - Calibrate so a balanced class crosses one average system in **2–4 real minutes** (D-7.13). Expose the per-class constants from data; no constants hard-coded in logic.
- **REQ-…-8** (D-7.2): progress queries return a structured progress record for the UI:
  - systems remaining, current leg, ETA in game seconds, current system and position;
  - a human sentence, e.g. "two systems out, arriving in 4 minutes".

  Number words up to ten, minutes rounded up, "under a minute" below 60 s.
- **REQ-…-9** (D-7.3, D-7.8): `OrderStop` in DockedTravel or EscortTravel computes the position along the route at the current game time, then asks W1-WORLD for the nearest **safe stop**. The model records the snapped point and transitions to Stopped. Planet destinations stop "close enough to be seen from it, not in orbit".
- **REQ-…-10** (D-7.13, R5 §1.3): **the clock** is the W1-CORE game clock, driven by server `ElapseTime` (vtable +0x30 / `pub::GetRwTime`).
  - It advances while docked, in menus and in the nav map.
  - It **stops only during the F1/Esc pause.**
  - The model never reads wall-clock time.
- **REQ-…-11** (D-7.12, D-3.1): **fleet.**
  - The model holds N carriers. At most one has the player aboard.
  - Any number may be in EscortTravel, but only those in the player's system and within escort range are "live". The others behave as Away.
  - No hard cap lives in the logic; the cap comes from the base mechanism (W2-CARRIER-GAME) and is reported via the API.
- **REQ-…-12** (D-9.7): per-carrier flag `ambush_pending`: no `AmbushRolled` is accepted while the carrier is in AmbushWaiting or UnderAttack.
- **REQ-…-13** (D-14.1, D-14.3): **persistence.**
  - Serialize the whole fleet to a versioned JSON section `carriers` in the per-save file (W1-CORE persistence API): `schema_version`, per-carrier id, name, class, tier, look, state, route legs, `t0`, speeds, stop point, upgrades ref, inventory ref, hull fraction, crew refs, `ambush_pending`, RNG state.
  - A round-trip test proves byte-identical re-serialization.
  - A missing section means an empty fleet, never a crash.
- **REQ-…-14:** **deterministic RNG** (PCG32 or xoshiro128**). It lives per carrier, its seed and counter are persisted, and it is exposed to W3-AMBUSH for rolls. The same save gives the same rolls.
- **REQ-…-16** (D-8.1, CONVENTIONS §9): **reflex eligibility.** Expose `IsInSpace(carrier)` = state ∈ {Stopped, EscortTravel, UnderAttack} and the carrier's form is spawned. W2-REFLEX heals the carrier whenever this is true and hull < policy threshold, not only in combat.
- **REQ-…-15:** **outputs are side-effect requests** (`SpawnSolarAt`, `DespawnSolar`, `BlockLaunch`, `UnblockLaunch`, `SpawnShipForm`, `DespawnShipForm`, `NotifyPlayer`, `RequestAmbushSpawn`), returned as a list that adapters execute. The logic never calls the engine.

## Context pack (read before writing code)

- `/home/user/freelancer/carrier-mod/CLAUDE.md`
- `docs/plan/CONVENTIONS.md` (all; §9 is the state machine, §8 sub-waves and deferred scenarios)
- `docs/plan/DESIGN.md` §3, §7 (all), §9.5–9.7, §14
- `docs/plan/TESTING.md` §Layers, §CI, §Metrics (travel-time bands)
- `state/ENGINE_FACTS.md`: clock and pause facts (from S-BASE/S-NPC)
- Frozen contracts (ARCH-0/ARCH-1): `src/contracts/` clock, persistence, world (route planner, safe stop), carrier model (this package implements it), inventory (refs only)
- `local/research/R5-sp-architecture.md` §1.3 (frame loop, pause counter 0x667D54, ElapseTime +0x30, `pub::GetRwTime`), §9 table
- `local/research/R3-game-data.md` §2.1–2.3 (system graph, lanes), §4.1 (capital engines ≈30 m/s impulse; the simulated speed is ours, not the engine's)
- `docs/design/CARRIERS.md` (W1-CARRIER-DESIGN): class speed multipliers and jump-transit constants

## Ownership

- **Owns:** `src/logic/carrier/`
- **Test assets:** per the BUILD_PLAN §6 ownership conventions: host tests in `src/logic/carrier/tests/` (or `tests/host/carrier/`), discovered by the root CMake glob.
- **Reads:** `src/contracts/`, `src/logic/world/`, `src/logic/core/`, `src/logic/economy/`, `data/carriers/`
- **Must not touch:** everything else

## Contract

- **Consumes:** clock, persistence, the world route planner + safe-stop API, carrier data tables (speeds), economy refs.
- **Provides:** the carrier model API frozen in `src/contracts/` by ARCH-1: commands, queries, the side-effect request list, the persistence section `carriers`, and the per-carrier RNG accessor.

## Tasks

1. Encode the transition table as data: (state, command) → (next state | Rejected, effects). Generate the test matrix from it.
2. Fleet container: create carrier (from W2-YARD purchase), rename, remove after Destroyed cleanup, aboard/escort bookkeeping.
3. Travel legs and the simulation: build from route-planner output, position(t), ETA, progress sentence.
4. Stop: interpolate, then snap via the safe-stop API, then record.
5. Persistence: serialize/deserialize with `schema_version = 1`; migration hook table (empty for v1); fuzz the deserializer against corrupt input.
6. RNG: implementation, seeding (from save id + carrier id), persistence.
7. Devbridge query surface: provide the data behind `carrier.list` and `carrier.status <id>` (CONVENTIONS §4) for W2-CARRIER-GAME to expose. The logic returns structs, not strings.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests (doctest)** in the native Linux build:
  - `transitions_all_pairs`: every (state × command) pair hits its expected result; the legal edges are exactly the CONVENTIONS §9 table (REQ-2).
  - `reroute_from_current_position`, `stopped_attacked_then_won`, `hullzero_outside_fight_passes_underattack`, `underattack_player_left_refreezes`, `away_arrives_becomes_stopped`.
  - `docked_trip_two_systems`: progress sentences at t = 0, mid, end match goldens; ETA monotonic.
  - `stop_midroute_snaps_safe`: the snapped point is ≥ the buffer from every hazard (fixture world).
  - `pause_freezes_progress`: clock advance with pause gives zero progress.
  - `fleet_aboard_exclusive`.
  - `ambush_pending_blocks_rolls`.
  - `persistence_roundtrip_bytes`, `persistence_missing_section_empty_fleet`, `persistence_fuzz` (≥ 10k random mutations, no crash, typed error). Corrupt-file handling at the file level (`.bad-<ts>`, `.bak` fallback) is W1-CORE's, per TESTING §SaveCompat; this package only rejects a corrupt `carriers` section with a typed error.
  - `rng_determinism_after_reload`.
- **Build checks:** host build plus i686 clang-cl build; `harness/ci.sh` host subset green.
- **In-game scenarios:** none owned. W2-CARRIER-GAME's scenarios exercise this logic, and the reviewer runs `carrier_docked_trip` from there once it exists.
- **Metrics:** with the shipped data, simulated per-system crossing time for the balanced class falls in 120–240 s game time (test `calibration_balanced_class`).
- **Negative tests:**
  - an unknown destination id;
  - a route with no path (locked links) → `Rejected{NoRoute}`;
  - a corrupt `schema_version`.

## Engine facts to rely on / verify

- Game time advances while docked and stops in F1 (R5 §1.3, VERIFIED by disassembly; confirm in ENGINE_FACTS from S-BASE).
- Systems without the player are not simulated by the engine (R2 fact 1), so this model is the only source of truth for Away carriers.

## Pitfalls

- Don't use wall-clock time or `std::chrono::system_clock` in logic.
- Don't let float drift accumulate across save/load: store `t0` and leg start times in game seconds as `double`.
- The design's "two systems out" counts **systems remaining to cross**, not jumps taken; define it in the API docs.
- Saves may be loaded out of order (reload an older save). The model must be fully reconstructed from that save's JSON, with no residue from the previous session (clear on load).

## Fallbacks and degrade path

- If W1-WORLD can't provide safe stops for some system, snap to the nearest route waypoint and push 5 km away from the closest hazard centre. Log a decision.
- **Degraded mode:** multi-hop routes disabled (adjoining systems and in-system points only), behind config flag `carrier.multihop = false`.

## Report (the agent's final message)

Per `AGENT_BRIEF_TEMPLATE.md`. Include the transition table as rendered by the test generator, and list the implied edges explicitly.

## Gate-time addendum

The orchestrator fills this in when writing the brief: track, base plan, contract header paths, ENGINE_FACTS ids, lane assignment, attempt number, prior notes (from `state/reports/<ID>-a<n>.md` / `-r<n>.md`).
