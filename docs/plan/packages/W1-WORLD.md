# W1-WORLD: world model, route planner, safe stops, route exposure

- **Type:** impl
- **Wave:** 1
- **Depends on:** ARCH-0 (contract `world.hpp`, spec `world_json.md`), P0-DATATOOLS (`world.json` export); sub-wave 1a (CONVENTIONS §8) → **Unblocks:** W2-CARRIER-LOGIC, W2-CARRIER-UI, W3-AMBUSH, W3-ESCORT, W3-NOMAD, W4-ESCALATION

## Goal

An engine-free C++ library that answers every spatial question the carrier and encounter systems ask. It is deterministic and fully host-tested, including golden tests against the research reference implementation:

- Which systems connect, and through which gates and holes?
- What is the route from A to B that a capital would take?
- Where along it is the carrier at time t?
- Where is a safe point to stop?
- Where should it stop near a planet?
- How exposed is a route leg to hostile, interdiction-capable patrols?

## Requirements

- **REQ-W1-WORLD-1: Load the world model** (D-7.1, D-7.8, D-7.9) from `world.json` (schema owned by ARCH-0 `docs/spec/world_json.md`, produced by the P0-DATATOOLS/W1-DATA exporter from the **local install** at deploy time; never committed). Expected content, per system:
  - **Objects:** nickname, archetype, solar type, pos, rotate, base, dock_with, reputation, `atmosphere_range`, radius, `goto` for gates and holes.
  - **Jump links:** `{to, via, to_object, kind: jumpgate|jumphole|airlock|nomad_gate, pos, reputation}`, as in `R3-data/system_graph.json`.
  - **Trade lanes:** chains of `trade_lane_ring` objects with `next_ring`/`prev_ring`, start and end positions, and per-ring positions, as in `R3-data/trade_lanes.json`.
  - **Zones:** nickname, shape, size, pos, rotate, `damage` (death zones), `property_flags`, exclusion zones, encounters `{encounter, level, chance, factions[(faction, weight)]}`, `density`, `pop_type`, `path_label`, `usage`, as in `R3-data/zones_encounters.json`.
  - **Asteroid/nebula fields** (`[Asteroids]`/`[Nebula]` with their zone).
  - **Planet and sun radii.**
  - **Locked links:** `[locked_gates]` in `DATA/initialworld.ini`: `locked_gate` (blocked for the player) and `npc_locked_gate` (NPCs never path through).
- **REQ-W1-WORLD-2: Zone geometry** must match the engine (VERIFIED in R3 §3.4 by a patrol-path continuity test):
  - `rotate = (rx, ry, rz)` in degrees; **world = Rz(rz)·Ry(ry)·Rx(rx)·local** (column vectors).
  - SPHERE: `size = r`. ELLIPSOID: semi-axes. BOX: full extents. CYLINDER: `size = (radius, length)`, **axis = local +Y**, centred on pos. RING: treat as CYLINDER.
  - Port `contains()` from `/home/user/freelancer/carrier-mod/local/research/R3-data/tools/route_exposure.py` exactly.
- **REQ-W1-WORLD-3: System graph and multi-hop routing** (D-7.1, D-7.9).
  - Dijkstra over systems, with edge cost = in-system travel distance from the arrival point to the next exit link (not hop count).
  - Exclude links whose object is `locked_gate`. Story locks are read from the **player's** current `[mPlayer] locked_gate` set, which the game adapter passes in.
  - Mark links in `npc_locked_gate` as "NPC-blocked". Docked or simulated travel may use them; escort mode (a real NPC) must avoid them, or use the W3-ESCORT fallback.
  - Expose both modes: `RouteMode::Simulated` and `RouteMode::LiveNpc`.
  - Exclude disconnected story systems (St01, St02, St02c, St03, St03b, FP7_system) unless reachable through unlocked links.
- **REQ-W1-WORLD-4: In-system pathing.**
  - Waypoint paths between two points that keep a clearance buffer from:
    - planets and suns (radius + `atmosphere_range` + death-zone radius + margin);
    - death zones (`damage > 0`);
    - exclusion zones;
    - asteroid and nebula field zones;
    - station and base solars (radius + 1,500 m);
    - **trade-lane corridors** (each lane segment as a capsule of radius 1,000 m, inflated by the margin).
  - The default margin is a config value (start at 2,000 m).
  - Use visibility-graph or sampled-arc A* around obstacle spheres and capsules. Paths must be smooth enough for a capital (minimum turn radius config, default 3,000 m) and deterministic.
- **REQ-W1-WORLD-5: Safe stop and planet approach** (D-7.3, D-7.8).
  - `SafeStopNear(system, point)` returns the nearest point outside every buffer. It searches along the route backwards first, then radially. It must not be inside any combat encounter zone of a faction hostile to the player at rep ≤ −0.6, if a non-hostile point exists within 10 km. It returns the clearance it achieved.
  - `PlanetApproach(planet)` returns a point outside the death and atmosphere buffers that keeps the planet visible:
    - the distance from the planet centre is `radius × k` (k default 2.5, clamped so the planet subtends ≥ 25° of view, computed from radius / distance);
    - it lies on the side facing the route's arrival direction.
  - "Close enough to be seen, not in orbit."
- **REQ-W1-WORLD-6: Route timing** (D-7.2, D-7.13).
  - `Route` = ordered legs (in-system waypoint polylines plus link transitions), each with a length.
  - Given a speed profile (cruise speed, jump transition seconds), `PositionAt(t)` returns `{system, pos, legIndex, progress}`. Also provide `EtaSeconds` and `SystemsRemaining`.
  - Pure math, so W2-CARRIER-LOGIC can simulate, save and restore mid-trip exactly.
- **REQ-W1-WORLD-7: Route exposure** (D-9.1, D-9.2, D-9.4). Port `exposure()` from `R3-data/tools/route_exposure.py`:
  - sample each leg every 500 m;
  - accumulate metres inside each zone whose encounter is a combat encounter (prefixes `patrolp_`, `area_assault`, `area_defend`, `area_scout`, `area_bh_`, `area_gunboats`, `area_nomads`);
  - weight = metres × density × chance × faction weight, for factions with rep ≤ −0.6;
  - output per faction: `metres_inside`, `weighted`, `max_level`, zones.

  Add `interdiction` per faction: the weighted sum multiplied by `frac_spawnable_ships_with_CD` for that faction and level (from `world.json`; R3 §8 computed it in `zone_encounters_flat.tsv` / `system_combat_presence.json`), plus a gunboat/capital presence flag. Exclude trade-lane box zones when the route never enters lanes. **No randomness here.** W3-AMBUSH converts exposure to odds.
- **REQ-W1-WORLD-8: Destination catalog** (D-7.1). For the travel menu, list per system:
  - planets (approach points);
  - dockable bases and stations (stand-off points);
  - gates and holes (approach points);
  - adjoining systems;
  - all reachable systems (multi-hop).

  Display names come from the text service (IDS from `world.json`).
- **REQ-W1-WORLD-9: Performance.** Load `world.json` in under 300 ms; plan a 6-system route in under 20 ms on the host (Release). It must not allocate per frame when queried for `PositionAt`.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§1 paths, §12 game-data hygiene)
- `docs/plan/DESIGN.md` §7 (D-7.1–D-7.9, D-7.13), §9 (D-9.1–D-9.4)
- `docs/plan/TESTING.md` §Layers, §Metrics (travel-time and ambush-frequency targets)
- `src/contracts/world.hpp`, `docs/spec/world_json.md`
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R3-game-data.md` §2 (systems table with hops and region; gate/hole graph with 232 symmetric directed links; story systems disconnected; `[locked_gates]` lists; precomputed `systems_shortest_path.ini`), §2.3 (trade lanes), §3.1–§3.4 (zone keys, encounters, geometry convention, exposure algorithm), §8 (cruise-disruptor factions by level; Liberty zones ≤ level 4)
  - `/home/user/freelancer/carrier-mod/local/research/R3-data/`: `system_graph.json`, `systems_full.json` (objects with `atmosphere_range`), `zones_encounters.json`, `trade_lanes.json`, `system_combat_presence.json`, `tools/route_exposure.py`, `tools/euler_test.py`, `tools/flini.py`
- Live data (read-only, for the golden-generation script): `/home/user/freelancer/prefix-dev-base-<track>/drive_c/Games/Freelancer HD Edition/DATA/UNIVERSE/` (or the play prefix, read-only, if the dev base doesn't exist). Facts:
  - Planets carry `atmosphere_range` (Manhattan `Li01_01`: `planet_earthgrncld_4000`, `atmosphere_range = 4200`).
  - Death zones are zones with `damage = 2000000` (`Zone_Li01_Manhattan_death`).
  - Exclusion zones are named `Zone_*_Exclusion_*` and are referenced by asteroid/nebula files.
  - The planet radius is encoded in the archetype suffix (`_4000`, `_2000`) and in `solararch.ini` `solar_radius`; prefer solararch.
- Reference: `/home/user/freelancer/refs/Librelancer/src/LibreLancer.Data/GameData/World/Zone.cs` (ContainsPoint), `/home/user/freelancer/refs/flint` (universe graph + Dijkstra in Python)

## Ownership

- **Owns:**
  - `src/logic/world/` and `tests/host/world/` (tests only).
  - **Golden files are derived from game data, so they are never committed** (CONVENTIONS §12). `tests/host/world/gen_golden.py` reads the local install and the research reference script, and writes golden JSON into `$FLMOD_GOLDEN/world/`. Tests regenerate the goldens if missing, or skip with a clear message when the install is absent.
  - A thin game-side adapter `src/game/world/`, which registers the `world.probe <system>` devbridge verb (additive, `world.*` namespace) through the devbridge core API.
  - Scenarios in `harness/scenarios/world/`.
- **Reads:** `src/contracts/`, `tools/fltools/`, research, live DATA.
- **Must not touch:** the exporter in `tools/fltools/` (P0-DATATOOLS; report bugs), contracts.

## Contract

- **Provides:** `world.hpp` implementation: `WorldModel::Load(path)`, `RoutePlanner`, `Route`, `SafeStop`, `PlanetApproach`, `Exposure`, `DestinationCatalog`.
- **Consumes:** the `world.json` schema (ARCH-0 spec). No game headers: this library must compile with host clang++ on Linux **and** clang-cl for the DLL.

## Tasks

1. Write a schema-validating loader with clear error messages and a version check.
2. Port the geometry with unit tests per shape (inside, outside, boundary) and rotation-order tests. Reproduce the R3 Euler finding: patrol-path segment joints match with a median gap under 100 m on the golden data.
3. Build the system graph with locked and NPC-locked flags. Dijkstra, plus K-shortest alternatives (K=3) for escort fallback.
4. Implement the obstacle model and in-system pather, with turn-radius smoothing and deterministic tie-breaking.
5. Implement safe stop and planet approach.
6. Implement route timing, `PositionAt`, and its exact serialization.
7. Port route exposure. Golden tests compare against the Python reference at relative tolerance 1e-6. Interdiction weighting.
8. Destination catalog.
9. Benchmarks (REQ-9) as tests with thresholds.

## Acceptance

- **Host tests** (`tests/host/world/`, doctest):
  - `geom_shapes` (all shapes and rotations)
  - `geom_euler_order` (patrol continuity median under 100 m)
  - `graph_symmetric_links` (all 232 directed links have reverses)
  - `graph_story_systems_unreachable`
  - `route_li01_to_hi02` (a valid multi-hop route exists; it never uses a `locked_gate`; under `RouteMode::LiveNpc` it avoids `npc_locked_gate`)
  - `route_respects_player_locks` (with M02/M04 story locks passed in, `Li01→Li02` is excluded)
  - `path_clears_hazards` (Li01 Manhattan → Texas gate: no waypoint inside any buffer; minimum clearance logged)
  - `path_avoids_lanes` (no sample within the lane capsule except crossings, which are minimized and perpendicular)
  - `safestop_never_in_hazard` (10,000 random points per system for 5 systems → every result is outside the buffers)
  - `planet_approach_visible` (subtended angle ≥ 25°, outside the death zone)
  - `route_timing_roundtrip` (`PositionAt` serialization exact)
  - `exposure_golden` (≥ 20 legs across Li01, Li02, Br04, Bw01, Ew04, Hi02, Ew06 vs `route_exposure.py`, relative tolerance 1e-6)
  - `exposure_liberty_core_no_interdiction` (the Li01 California-gate → Texas-gate leg gives interdiction 0, as R3 §3.4 found)
  - `perf_load_and_plan`
- **Golden data:** `tests/host/world/gen_golden.py` runs `/home/user/freelancer/carrier-mod/local/research/R3-data/tools/route_exposure.py` (with `$FLMOD_VENV/bin/python -I`) on the same legs and writes the expected values to `$FLMOD_GOLDEN/world/`.
- **In-game smoke** (light; the full in-game travel test belongs to W2): `world_positions_match`, `DEFERRED(W1-PLATFORM)` because the adapter needs the production platform from the same sub-wave. Devbridge `world.probe <system>` prints selected objects' positions from `world.json`. Compare with the live game: `pub::SpaceObj::GetLocation` of the same objects. All positions match within 1 m. This proves the exporter and the loader are consistent with the engine.
- **Metrics:** compute the route length and the docked-travel ETA, at the default speed profile, for the 10 sample routes in TESTING §Metrics. Write them to the report so W1-CARRIER-DESIGN can tune speeds.

## Engine facts to rely on / verify

- The geometry convention and exposure algorithm are VERIFIED in R3 §3.4. Re-verify with the golden tests.
- `npc_locked_gate` blocks NPC pathing (UNVERIFIED in practice; S-NPC tests it). This library only labels links.
- **Gate arrival point:** jump-in places a ship at the destination object's arrival location (R2 fact 7). For simulation, use the destination gate's position plus 2,500 m along its exit direction. Refine from S-NPC facts.

## Pitfalls

- Overlapping zones are each counted, so `metres_inside` can exceed the leg length (R3 §3.4). That's fine, but document it.
- Some systems have more than 10 jump objects in modded data. Not our concern: we never add links.
- Ew05 and Ew06 are hole-only. Ku06/Ku07, Bw02 and Bw04 are hole-only too (R3 §2.2).

## Fallbacks and degrade path

1. If the obstacle pather fails to find a clear path (pathological fields), fall back to a straight line with the minimum-clearance violation reported, and let the caller choose an alternative destination.
2. If the exposure computation is too slow, precompute per-zone segment intersections at load time.

## Report

Use the standard report. Include the 10-route length and ETA table, the clearance statistics, and the benchmark numbers.

## Gate-time addendum

The orchestrator fills:

- the world.json schema version and path on lanes;
- ENGINE_FACTS for jump arrival offsets and capital speed (S-NPC);
- the path to the dev-base DATA;
- attempt notes;
- the commit trailer.
