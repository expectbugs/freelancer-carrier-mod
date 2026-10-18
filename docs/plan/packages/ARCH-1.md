# ARCH-1: refine and freeze the contracts for Wave 2

- **Type:** arch
- **Wave:** between G1 and Wave 2
- **Depends on:** G1 (PASSED) → **Unblocks:** W2-ENCOUNTER, W2-CARRIER-LOGIC, W2-CARRIER-GAME, W2-LOADOUT, W2-YARD, W2-CARRIER-UI, W2-REFLEX

## Goal

ARCH-0 froze contracts before any production code existed. Wave 1 has since built the platform, core, world, spawn, UI kit, data, inventory, harness and sidecar, and learned things.

ARCH-1 reconciles the contracts with that reality. Then it freezes the **Wave-2 contracts**, using the exact file names in CONVENTIONS §3, precisely enough that seven agents in sub-waves 2a, 2b and 2c (CONVENTIONS §8) can build against them without stepping on each other:

- carrier model and state machine;
- encounter;
- loadout;
- yard;
- carrier UI;
- reflex;
- the IPC game side.

"Precisely" means compile-ready headers, documented semantics, event lists, persistence schemas and an ownership map.

## Requirements

- **REQ-ARCH-1-1: Wave-1 reconciliation.**
  - Read every Wave-1 report and review (`state/reports/<ID>-a<n>.md`, `-r<n>.md`; CONVENTIONS §10), `state/DECISIONS.md`, `state/DEGRADED.md`, `state/QUARANTINE.md` and `state/ENGINE_FACTS.md`.
  - List every contract gap Wave-1 agents raised as an open question, and every place the implementation diverged from ARCH-0's headers.
  - Resolve each one: either amend the contract (with a migration note) or file a `FIX-*` brief for the code.
  - Output: `docs/spec/ARCH-1-reconciliation.md`.
- **REQ-ARCH-1-2: Carrier model contract** (`src/contracts/carrier.hpp`, `docs/spec/carrier.md`). Covers D-3, D-7, D-8 and D-14.
  - `CarrierId`.
  - `CarrierState`, exactly the 7 states: Stopped, DockedTravel, EscortTravel, Away, AmbushWaiting, UnderAttack, Destroyed.
  - The legal transition table: the **canonical edge table in CONVENTIONS §9** (D-7.11 as amended). This includes re-route while in DockedTravel, Stopped→UnderAttack, UnderAttack→AmbushWaiting, Away→Stopped, and destruction outside a formal fight through UnderAttack. Add the fleet rules from D-7.12.
  - Reflex healing applies in every state where the carrier exists in space (CONVENTIONS §9).
  - **Orders:** `TravelTo(destination, mode)` with destination ∈ {point, object, system, multi-hop system}; `Stop()`; `Escort()`; `Rename()`.
  - **Queries:** position at t, ETA, systems remaining, current base binding, hull, stocks, class/tier/look, installed upgrades.
  - **Events:** `carrier.state_changed{from,to,reason}`, `carrier.arrived`, `carrier.stopped{pos}`, `carrier.ambush{…}`, `carrier.destroyed`.
  - **Persistence:** the JSON schema per carrier (schema version 1), including the in-progress route and t0 so docked travel restores exactly mid-trip.
  - Split precisely between W2-CARRIER-LOGIC (engine-free state machine and simulation) and W2-CARRIER-GAME (engine representation: solar/ship spawn, base binding Plan A/B, launch block, undock placement, docking rules, load restore).
- **REQ-ARCH-1-3: Encounter contract** (`encounter.hpp`, `docs/spec/encounter.md`). D-10 verbatim, as typed structures:
  - **Definition:** faction, ship specs (npcship nickname or arch+loadout+pilot+level), group size and composition rules, scaling inputs.
  - **Trigger:** kinds AmbushRoll, ZoneEnter, NomadEngaged, EscalationStage, Manual; with parameters.
  - **Placement:** relative to the player, a carrier, a point, or a system random-safe point; with distance and spread.
  - **Persistence:** frozen state via W1-SPAWN `FrozenGroup`; partial-fight snapshot.
  - **Outcome hooks:** OnWin, OnLoss, OnRetreat, with typed effects (set flag, destroy carrier, change influence, drop loot, notify).
  - The YAML data format for `data/encounters/`.
  - Owner boundaries with W3-AMBUSH, W3-NOMAD and W4-ESCALATION.
- **REQ-ARCH-1-4: Loadout contract** (`loadout.hpp`, `docs/spec/loadout.md`). From the S-LOADOUT facts:
  - how installed upgrades become a runtime loadout (runtime composition, pre-generated variants, or slot templates; whichever S-LOADOUT proved);
  - the hardpoint-extended model naming and generation interface for `gen/models/` (W2-LOADOUT);
  - munition tracking events and launcher enable/disable;
  - the shield-generator mechanism.
- **REQ-ARCH-1-5: Yard contract** (`yard.hpp`, `docs/spec/yard.md`). D-5 and D-6:
  - catalog queries per yard; purchase transaction (class, initial upgrades, name), using the W1-INVENTORY Txn;
  - retrofit (install, remove-to-hold) with the 10 km Stopped rule;
  - fleet-cap reporting (D-3.1);
  - the Gammu gate check (`nomad_gate_unlocked`, the only flag name; CONVENTIONS §2).
- **REQ-ARCH-1-6: Carrier UI contract** (`docs/spec/carrier_ui.md`).
  - Panels and their data sources: the travel menu (destination catalog from W1-WORLD), progress, Stop, status, hold transfer, quartermaster, in-space command panel and hotkey.
  - Strings keys; devbridge widget IDs for tests.
- **REQ-ARCH-1-7: Reflex and IPC contract** (`reflex.hpp`, `docs/spec/reflex.md`, plus amendments to `docs/spec/ipc.md`).
  - Policy struct and clamps: `bots_hull_below` 0.05–0.95, reserves, the `critical_hull` hard floor, release conditions.
  - Who calls the reflex: the player ship and each live carrier.
  - The nanobot/battery usage mechanism proven by S-NPC (`use_item` vs `SetRelativeHealth` plus stock decrement).
  - Snapshot and event fields the DLL sends (R6 §3.2–3.4); command whitelist and rate limits.
- **REQ-ARCH-1-7b: Devbridge freeze.** Freeze every Wave-2 verb into `docs/spec/devbridge.md`, using the CONVENTIONS §4 namespaces and event names (`ev=<name>`): `carrier.*`, `yard.*`, `enc.*`, `reflex.*`, `ipc.*`. Also record the additive Wave-1 verbs the reports declared, e.g. `inv.*`, `world.probe`, `ui.type/select/perf`, `spawn.*`, `ai.*`, `kill`, `target`, `debug hang`.
- **REQ-ARCH-1-8: Compile-ready.**
  - All headers compile under clang-cl i686 **and** host clang++ (logic-only headers). Discovery is by glob, so the root CMake is edited only if a new directory pattern is needed (CONVENTIONS §14).
  - A stub implementation library (`src/contracts/stubs/`) lets each Wave-2 package build and unit-test against the others' interfaces before they exist.
- **REQ-ARCH-1-9: Ownership map.**
  - Update `docs/plan/OWNERSHIP.md`: directory → package for Wave 2, plus the shared files and who may append (e.g. `data/strings/` keys per namespace).
  - Update each Wave-2 package spec's **gate-time addendum** section with the exact contract file list. Edit only the addendum sections. ARCH packages hold this right standing (BUILD_PLAN §6 ownership conventions), so no per-run grant is needed.
- **REQ-ARCH-1-10: Test plan per contract.** For each contract, list the integration scenarios that prove cross-package behavior at M1: buy → stop → dock → travel → stop → undock; save mid-trip; reflex heals carrier; the first escalation proof encounter.
  - Add them to `harness/scenarios/m1/` as **skeleton YAML** in the TESTING §Scenarios schema, with `package:` set to the owner. The owning packages fill them in.
  - Mark which ones are expected to be `DEFERRED(<sibling>)` under the 2a/2b/2c ordering.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §3, §4, §8, §9 especially)
- `docs/plan/BUILD_PLAN.md` §2, §5, §6
- `docs/plan/DESIGN.md`: all of it (Wave 2 touches §3–§11, §14, §15)
- `docs/plan/TESTING.md` §M1, §Scenarios, §SaveCompat
- `state/`: `ENGINE_FACTS.md`, `DECISIONS.md`, `DEGRADED.md`, `gates/G0a.md`, `gates/G0b.md`, `gates/G1.md`
- Existing contracts and specs: `src/contracts/*`, `docs/spec/*`, `docs/plan/OWNERSHIP.md`
- All Wave-1 package reports (from the ledger) and their code (read-only), especially the W1-PLATFORM capability matrix, W1-SPAWN freeze/thaw, W1-WORLD route timing, W1-INVENTORY Txn, W1-CARRIER-DESIGN YAML schema use, and the W1-UI kit
- Research: R1 §2–§4, R2 §2 (dynamic bases), §4 (AI), R5 §3–§4, §9 (carrier mapping table), R6 §3 (protocol)

## Ownership

- **Owns:** `src/contracts/`, `docs/spec/`, `harness/scenarios/m1/` (skeletons only), `docs/plan/OWNERSHIP.md`, and the gate-time addendum sections of the Wave-2 package specs (standing ARCH rights, BUILD_PLAN §6).
- **Reads:** everything.
- **Must not touch:** implementation code (file `FIX-*` briefs instead).

## Contract

- **Provides:** the frozen Wave-2 headers, specs, stubs, ownership map and M1 scenario skeletons.
- **Consumes:** the Wave-1 reality.

## Tasks

1. Reconciliation report (REQ-1).
2. Write or update the headers and specs (REQ-2 to REQ-7). Each header begins with a comment block: purpose, threading rules, ownership, version.
3. Stubs plus a build check on both compilers.
4. Ownership map plus addenda.
5. M1 scenario skeletons.
6. Self-review against DESIGN: tick each D-x.y that Wave 2 must satisfy and point it to a contract element (`docs/spec/ARCH-1-trace.md`, a traceability matrix).

## Acceptance

- `harness/ci.sh --quick` (build stages; TESTING §CI) compiles every header and stub with clang-cl and host clang++.
- A traceability matrix covers 100% of D-3, D-5, D-6, D-7, D-8, D-10, D-11.1–11.3 and D-14 requirements, with no orphan contract elements.
- The reconciliation lists every Wave-1 open question with a resolution.
- An independent reviewer agent (orchestrator-spawned) passes the contracts against DESIGN and the Wave-2 specs.

## Engine facts to rely on / verify

Use ENGINE_FACTS only. This package doesn't run the game, except optional quick checks through existing scenarios.

## Pitfalls

- Over-generalizing. Contracts serve the Wave-2 specs; don't design Wave-3/4 interfaces beyond the hooks they need (ARCH-2 and ARCH-3 do that).
- Changing a Wave-1 contract without a migration path for code already merged.

## Fallbacks and degrade path

If a needed capability was degraded in Wave 1 (e.g. no overlay), the contracts expose the capability flags and specify the degraded behavior. Never pretend the capability exists.

## Report

Use the standard report. Include the list of headers, the traceability summary, and the reconciliation decisions.

## Gate-time addendum

The orchestrator fills:

- the Wave-1 report paths (`state/reports/`);
- the G1 gate report path;
- attempt notes;
- the commit trailer.
