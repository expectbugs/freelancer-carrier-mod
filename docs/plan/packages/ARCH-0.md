# ARCH-0: Freeze contracts, specs, module skeleton and code ownership

- **Type:** arch
- **Wave:** end of Phase 0
- **Depends on:** G0b → **Unblocks:** all of Wave 1.

## Goal

Turn the Phase 0 facts into the frozen interfaces that every later package codes against. These are C++ headers in `src/contracts/` plus prose specs in `docs/spec/`. With them, roughly ten agents can build in parallel without stepping on each other.

Deliver a module skeleton that builds into a loadable DLL on the chosen track, and native host test builds of `src/logic`. Deliver `docs/plan/OWNERSHIP.md`, the single map of who owns which directory for every package through Wave 5.

## Requirements

- **REQ-ARCH-0-1: the platform abstraction** (BUILD_PLAN §2). `src/contracts/platform.hpp` is the **only** interface game-facing code uses for engine hooks.
  - Start from the spike API (`spikes/track_<x>/include/spike_platform.hpp`) and generalize it:
    - typed ids: `ShipId`, `SolarId`, `ObjectId`, `BaseId`, `SystemId`, `GoodId`, `RepGroupId`; plain `uint32_t` wrappers, matching FL `CreateID` values;
    - all events: base enter/exit, launch request/complete, jump in/out, dock request (allow/deny + reason IDS), damage (hull/shield, attacker, amount, modifiable if the track supports it per ENGINE_FACTS), destroy (killer), cargo add/remove, purchase (GFGoodBuy/ReqAddItem), save written/loaded, new game, pause change, player death;
    - tick (game-time dt + paused);
    - undock override;
    - launch blocking;
    - overlay draw surface;
    - native button factory (if EF says possible);
    - key input (PTT and hotkeys);
    - text override;
    - screenshot;
    - a deferral queue.
  - Track A implements it over FLUF; Track B over our own hooks. **Only `src/game/platform/` may include FLUF or raw-hook headers.**
  - Document thread rules (main thread only), event ordering, re-entrancy (no spawn or destroy inside callbacks; use `Defer`), and lifecycle (reset on new game, on load, on SP⇄MP; R5 §1.1, §2).
- **REQ-ARCH-0-2: contract headers.** The exact file list is CONVENTIONS §3, and **every file listed there must exist** after this package, even as a skeleton.
  - Pure C++23 interfaces (abstract classes or concepts), header-only, no FL headers except in `platform.hpp`'s implementation side.
  - Each documents invariants, units (metres, seconds of game time, credits) and failure modes.
  - JSON: **nlohmann/json** (single header, vendored under `$FLMOD_VENDOR` by P0-TOOLCHAIN). Host tests: **doctest**.

  | Header | Content | Implemented by |
  |---|---|---|
  | `clock.hpp` | Game clock (`now()`, `dt`, paused). In-game day length comes from `universe.ini [Time] seconds_per_day` (HDE value 1800, VERIFIED: the first lines of HDE `universe.ini` read `seconds_per_day = 1800`). Day helpers drive wages (D-11.5), crew replacement (D-11.4) and boss respawn (D-12.4). Wall-clock vs game-clock rules. | W1-CORE |
  | `events.hpp` | Typed event bus: event structs, subscribe/unsubscribe, synchronous dispatch on the main thread | W1-CORE |
  | `persistence.hpp` | Per-save JSON document `<save>.carrier.json` (D-14.1). Subsystem sections with `schema_version`, a migration registry, load/save hooks, atomic write (temp + rename), and mirrored critical flags in the `.fl` (D-14.1; S-BASE/S-UI findings decide the mechanism). Corrupt-file handling: keep a `.bak`, log, start clean, never crash. | W1-CORE |
  | `config.hpp` | Typed config access (YAML under the mod dir), reload hook | W1-CORE |
  | `log.hpp` | Logger (`[carrier] <subsystem>: …`), levels, the `Harness(kv)` emitter | W1-CORE |
  | `devbridge.hpp` | Production devbridge registration (`DevbridgeRegister`, the same API as the Phase-0 core), superseding the harness core. Keeps the same file protocol, which `docs/spec/devbridge.md` promotes from `harness/devbridge/PROTOCOL.md`. | W1-CORE |
  | `spawn.hpp` | `SpawnSpec` (ship or solar, archetype, loadout or runtime loadout, faction, pilot/personality, level, name, pos/rot, system, dockWith, health); validation result; owned handles; freeze snapshot / thaw; despawn; ownership tags (carrier, encounter, wingman) | W1-SPAWN |
  | `ai.hpp` | Orders (goto waypoints, follow, attack by rep, retreat, stop, jump via gate per the EF recipe, guard), plus escort steering (engine AI or kinematic per the G0b decision) | W1-SPAWN |
  | `ui_kit.hpp` | UI kit (window, list, button, progress, text input, tabs, tooltips, modal), FL theme tokens, base-menu button registration, notification service (NN, popup, toast, subtitle, waypoint) | W1-UI |
  | `text.hpp` | IDS lookup, our resource-DLL id map (`$FLMOD_LOCAL/gen/text_ids.json`, generated per `docs/spec/text_ids.md`), runtime overrides | W1-UI |
  | `world.hpp` | System graph (links with `locked_player` / `locked_npc`), hazards, lanes, zones; route planner (multi-hop, in-system waypoints avoiding hazards and lanes, D-7.8/7.9); safe-stop and planet-approach finder; route exposure per faction with interdiction weighting (D-9.1–9.3); loads `world.json` (`docs/spec/world_json.md`) | W1-WORLD |
  | `inventory.hpp` | Item stacks, carrier holds and stocks (nanobots, batteries, munitions), wallet ops (pay, charge, refund-free), wage ledger, price queries | W1-INVENTORY |
  | `carrier.hpp` | Carrier model: id, name, class, tier, look, installed upgrades and slots, hull, stocks, state enum (the 7 states, D-7.11), route and progress, orders (travel to, stop, escort), fleet registry (D-3.1, D-7.12), base binding (Plan A/B from G0b) | W2-CARRIER-LOGIC / W2-CARRIER-GAME |
  | `encounter.hpp` | Definition / trigger / placement / persistence / outcome hooks (D-10.1–10.5); frozen-fight snapshot format | W2-ENCOUNTER |
  | `reflex.hpp` | Policy struct with clamps (`docs/spec/ipc.md` `policy.set` fields), thresholds, a hard `critical_hull` floor, one implementation for the player and the carrier (D-11.1) | W2-REFLEX |
  | `loadout.hpp` | Runtime loadout composition from installed upgrades (S-LOADOUT recipe), munition stock and depletion hooks | W2-LOADOUT |
  | `ipc.hpp` | The game side of the sidecar protocol (`docs/spec/ipc.md`): message structs, worker-thread client interface, policy and command whitelist | W2-REFLEX |
  | `wingmen.hpp`, `yard.hpp`, `escalation.hpp` | Forward-looking skeletons. Mark them **provisional**: ARCH-1 and ARCH-3 finalize them. | — |
- **REQ-ARCH-0-3: specs in `docs/spec/`.** This is exactly the CONVENTIONS §3 list; every file must exist.
  - `devbridge.md`:
    - the wire protocol, promoted verbatim from `harness/devbridge/PROTOCOL.md`;
    - the **full verb and owner table and the periodic events**, seeded from CONVENTIONS §4 (`ev=` events, `va_free_mb` / `va_largest_free_mb` keys);
    - the argument and output format of each verb that exists by now; the others are listed as "reserved, owner X".
  - `persistence.md`: file schema, versioning, migrations, `.bak`, corrupt-file policy (TESTING §SaveCompat wins), save-scum notes.
  - `world_json.md`: promoted from P0-DATATOOLS's `gen/framework/WORLD_JSON.md`.
  - `data_schemas.md`: YAML schemas for every `data/**` area (core, carriers, yards, encounters, pilots, strings, tuning), plus **placeholder YAML committed under `data/`**, so W1-DATA and W1-CARRIER-DESIGN work against one agreed shape in parallel. All new nicknames use the `fcm_` prefix (CONVENTIONS §2).
  - `events.md`: the event-bus catalog (struct, publisher, subscribers, ordering).
  - `ui.md`: panel conventions, theme, input focus, Esc behaviour, resolution scaling from 1280×720 to 4K (D-15.2/15.3).
  - `text_ids.md`: IDS allocation rules, the index-8 detection (D-15.1), the `data/<area>/strings.yaml` key namespaces (CONVENTIONS §2), and the generated map `$FLMOD_LOCAL/gen/text_ids.json`.
  - `ipc.md`: owned by P0-SIDECAR. Review it and add a "frozen v1" note, including the per-lane port `29170+N` (CONVENTIONS §7). Don't rewrite it.
  - `scenario_schema.md`: a copy of TESTING §Scenarios (`package`, `do`, `asserts`, …), the one schema.
  - `fixtures.md`: the CONVENTIONS §6 namespace (`HARNESS_<name>`, `harness/fixtures/gen_fixture.py`) and the list of existing fixtures.
  - `balance_sim.md`: the host balance-simulator interface W1-CARRIER-DESIGN implements (inputs: carrier and encounter stat blocks from YAML; outputs: win rate, time to kill, consumption).
  - Optional extras, allowed: `platform.md` (event list, ordering, thread rules, track notes) and `logging.md`.
- **REQ-ARCH-0-4: module skeleton.**
  - `src/module/` builds `carrier_endgame.dll` for the chosen track.
    - Track A: a `FlufCombinedModule`.
    - Track B: a dacom DLL whose platform layer is moved from the spike into `src/game/platform/` as **production-quality code** with the spike hacks removed. Alternatively, leave a clearly marked shim that W1-PLATFORM replaces. Decide which and record it.
  - It initializes a subsystem registry, the logger and the devbridge, and runs: `HARNESS ev=module_ready version=<git sha>`.
  - `src/logic/` builds natively on the host, plus with clang-cl, via a CMake check.
  - A `smoke` scenario (`harness/scenarios/smoke.yaml`, schema per TESTING §Scenarios) boots, loads the fixture `HARNESS_endgame_eagle`, sees `HARNESS ev=module_ready`, and quits.
    - Wire it into CI by creating `harness/ci.d/60-scenarios-quick.sh` as a minimal stage that runs `smoke`. W1-HARNESS takes over and extends that stage file in Wave 1.
    - Run output goes to `$FLMOD_TESTRUNS`.
- **REQ-ARCH-0-5: `docs/plan/OWNERSHIP.md`.** One table covering every package from W1 to W5, plus how `W4-ESC-*` and `FIX-*` get ownership. Columns: package → owned directories and files → contracts provided → contracts consumed.
  - Must match BUILD_PLAN §6 "Owns" **and the ownership conventions and CONVENTIONS §14**:
    - `state/**` and the `tools/` scripts are orchestrator-only;
    - the root CMake and `cmake/` pass to ARCH-0 now;
    - `src/module/` passes to W1-PLATFORM;
    - `harness/soak/` belongs to W1-HARNESS;
    - `tests/compat/` belongs to W5-COMPAT;
    - `requirements-dev.txt` is shared and append-only;
    - per-package test and scenario folders follow the BUILD_PLAN §6 conventions.
  - Where BUILD_PLAN is too coarse, refine it (e.g. split `src/game/ui/` subdirectories) **without contradicting it**, and record each refinement in DECISIONS.
  - No path may have two owners in the same wave.
- **REQ-ARCH-0-6:** carry the G0b decisions into the contracts. Examples:
  - Plan A/B base binding in `carrier.hpp`;
  - the upgrade strategy in `yard.hpp`;
  - the nanobot mechanism behind `reflex.hpp`;
  - the escort movement mode behind `ai.hpp`;
  - the scale thresholds as config constants in `spawn.hpp`.

  Each contract header cites the `EF-*` ids it relies on.

## Context pack

- **All of:** `docs/plan/CONVENTIONS.md` (authoritative names), `docs/plan/DESIGN.md`, `docs/plan/BUILD_PLAN.md`, `docs/plan/TESTING.md`, `state/ENGINE_FACTS.md`, `state/DECISIONS.md`, `state/gates/G0a.md`, `state/gates/G0b.md`, and the spike reports `state/reports/S-*-a*.md`
- Every spike's `FINDINGS.md`/`RESULTS.md`; `spikes/track_<x>/` (platform code to promote); `harness/README.md`; `harness/devbridge/PROTOCOL.md`; `tools/fltools/README.md`; `gen/framework/WORLD_JSON.md`; `docs/spec/ipc.md`
- `$FLMOD_RESEARCH/R5-sp-architecture.md` §1–2 (lifecycle and threading); `$FLMOD_RESEARCH/R1-fluf.md` §1.3 (module lifecycle) if Track A

## Ownership

- **Owns:** `src/contracts/`, `docs/spec/` (except `ipc.md`, which is review-only), the `src/module/` skeleton (passes to W1-PLATFORM afterwards), root `CMakeLists.txt` and `cmake/` (taken over from P0-TOOLCHAIN), `docs/plan/OWNERSHIP.md`, placeholder YAML under `data/` (schemas only; W1-DATA and W1-CARRIER-DESIGN take over their areas), `harness/scenarios/smoke.yaml`, `harness/ci.d/60-scenarios-quick.sh` (minimal; W1-HARNESS takes over).
- **Must not touch:** `docs/plan/{BUILD_PLAN,DESIGN,AUTONOMY,TESTING,CONVENTIONS}.md`, `state/**`, `tools/` scripts. Propose changes in the report; the orchestrator applies them.

## Contract

Provides all of the above. Once merged, `src/contracts/` is **frozen**. Changes go only through ARCH-1/2/3 or a `FIX-*` with orchestrator approval logged in DECISIONS.

## Tasks

1. Read everything in the context pack. List every DESIGN D-id and map it to the contract that serves it. Put the coverage table in `docs/spec/README.md`.
2. Write the headers. Each compiles standalone on host and win32 (CI test).
3. Write the specs.
4. Build the module skeleton plus the smoke scenario.
5. Write `OWNERSHIP.md`.
6. Self-review against ENGINE_FACTS: no contract may assume a REFUTED fact.

## Acceptance

- `harness/ci.sh` is green, including: `host` (all contract headers compile standalone, and `src/logic` is clean of Windows includes), `win32` (`carrier_endgame.dll` builds; import check PASS), and the `smoke` scenario (verdict PASS, `HARNESS ev=module_ready`).
- The coverage table maps **every** D-id in DESIGN.md to a contract or an explicit "data only / sidecar" note.
- Every file in the CONVENTIONS §3 lists exists: contracts compile standalone, and specs are non-empty.
- `docs/spec/devbridge.md`'s verb table matches CONVENTIONS §4 exactly: same verbs, owners and event keys.
- `OWNERSHIP.md` has no path owned twice within a wave, and is consistent with BUILD_PLAN §6.
- The reviewer checks the contracts against ENGINE_FACTS and DESIGN, and confirms there are no FL types outside `platform.hpp`'s implementation boundary.

## Engine facts to rely on / verify

All of `state/ENGINE_FACTS.md`. This package verifies nothing new in game except the smoke boot.

## Pitfalls

- Over-specifying the forward-looking contracts (`wingmen`, `yard`) before their waves: mark them provisional.
- Leaking FL types into `src/logic`: that breaks host tests.
- Forgetting lifecycle resets. The game can load a different save without restarting, so every subsystem needs `OnNewGame` / `OnLoad` / `OnUnload`.

## Fallbacks and degrade path

None. This package must complete. If a decision is unresolved, choose using AUTONOMY §3 and record it.

## Report

AGENT_BRIEF_TEMPLATE format plus the coverage table summary and the list of decisions.

## Gate-time addendum

(Orchestrator: track, base plan, G0b decisions list, attempt, commit trailer.)
