# ARCH-3: Contracts for wingmen, hiring, brain and escalation hooks

- **Type:** arch
- **Wave:** 4 (opens the wave)
- **Depends on:** gate M2 PASSED (`state/gates/M2.md`, written by the orchestrator)
- **Unblocks:** sub-wave 4a (W4-WINGMEN, W4-BRAIN, W4-ESCALATION-DESIGN), then 4b (W4-HIRING after WINGMEN; W4-ESC-* after the design; CONVENTIONS §8)

## Goal

Freeze the interfaces Wave 4 builds against, so four agents can work in parallel without stepping on each other:

- the wingman model and in-space control;
- the hiring and roster economy;
- the game↔sidecar command surface for wing orders and banter;
- the escalation hook points the design agent will plug into.

The output is compiling headers and prose specs that describe **what is true after Waves 1–3 merged**, not what was planned in Phase 0.

## Requirements

- **REQ-ARCH-3-1:** `src/contracts/wingmen.hpp`, covering D-11.4–D-11.9 and D-8.5:
  - wingman identity (crew vs hired, carrier binding);
  - roster entry (pilot name, skill tier, ship arch, loadout, faction affiliation, wage, status `docked|following|guarding|launched|dead|quit`);
  - order enum (`follow, formation(<tight|loose|line|escort>), focus(<target ref>), engage_free, hold, retreat, regroup, guard_carrier(<id>), stay_docked(<id>)`);
  - events: `wing.spawned, wing.engage, wing.damaged, wing.down, wing.rejoined, wing.quit, wing.replaced`;
  - bay capacity query per carrier;
  - hangar auto-launch hook called by the ambush/encounter system.
- **REQ-ARCH-3-2:** `src/contracts/hiring.hpp`:
  - candidate generation API (bar base id → candidates);
  - hire/fire;
  - a wage ledger tick on the mod game clock (1 in-game day = `seconds_per_day` from `universe.ini` [Time], verified as 1800 s in HDE);
  - unpaid-day counter (quit after 3 per D-11.5);
  - permadeath record.

  Reuses `src/contracts/inventory.hpp` (W1-INVENTORY) for credits. Never duplicate credit logic.
- **REQ-ARCH-3-3:** `docs/spec/ipc.md` v2 (extends P0-SIDECAR v1 and W2-REFLEX):
  - `wing.formation`, `wing.focus`, `wing.order`, `wing.policy`;
  - `say` with speaker `wing:<id>`;
  - roster snapshot fields;
  - a `brain.context` **IPC event** (system, carrier states, escalation headline) for banter. The devbridge verb `brain.context` (CONVENTIONS §4, W4-BRAIN) prints the same payload for tests.

  Version bump rules; the DLL's validation and clamp rules for every new command (R6 §3.4).
- **REQ-ARCH-3-4:** `src/contracts/escalation.hpp` (the file name is fixed by CONVENTIONS §3; ARCH-0 created the skeleton). The **minimum surface** W4-ESCALATION-DESIGN may rely on:
  - per-faction-per-system influence store (persisted in the per-save JSON);
  - event taps (player kills by faction, missions completed for a faction, bribes or donations if feasible, trade deliveries, base visits);
  - an encounter-definition registration API (W2-ENCOUNTER);
  - a scheduled-tick API on the mod clock;
  - news, NN and toast notification APIs (W1-UI);
  - a "base control override" interface stub whose implementation W4-ESCALATION-DESIGN's spike decides.

  Mark every capability VERIFIED (exists in merged code) or PROPOSED (the design agent must spike it).
- **REQ-ARCH-3-5:** `docs/spec/persistence.md` addendum: JSON schema sections for `wingmen`, `roster`, `hiring`, `escalation` (opaque blob owned by escalation packages, with a version field), plus migrations from the current schema version.
- **REQ-ARCH-3-6:** `docs/spec/devbridge.md` addendum: freeze the `wing.*`, `hire.*`, `brain.*` and `esc.*` verb lists and their `ev=` events (CONVENTIONS §4: `ev=` lines, `va_*` keys).
- **REQ-ARCH-3-7:** Ownership map update in `docs/plan/OWNERSHIP.md` for Wave 4 paths. W4-ESC-* packages get paths under `src/logic/escalation/<area>/`, `src/game/escalation/<area>/` and `data/escalation/<area>/`, with no limit on the number of packages. The reserved fallback package **W4-ESC-FALLBACK** gets `src/logic/escalation/fallback/`, `src/game/escalation/fallback/` and `data/escalation/fallback/` (W4-ESCALATION-DESIGN spec, Fallbacks).
- **REQ-ARCH-3-8:** Everything compiles. A stub implementation (no-op) of each new interface links into the module, and `harness/ci.sh --quick` is green.

## Context pack (read before writing)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all)
- `docs/plan/DESIGN.md` §8, §10, §11, §13, §14
- `docs/plan/TESTING.md` §Devbridge, §SaveCompat
- `state/ENGINE_FACTS.md`: all entries, especially S-NPC and S-PERF
- Merged contracts: `src/contracts/*.hpp`; `docs/spec/*.md`; `docs/design/CARRIERS.md`
- Gate reports `state/gates/M1.md`, `state/gates/M2.md`, package reports `state/reports/*`, `state/QUARANTINE.md`, `state/TUNING.md`: known issues that affect contracts
- `local/research/R2-engine-api.md` §4.1–4.4 (AI ops, wingman recipe: follow via `DirectiveFollowOp`, attack via `pub::Reputation::SetAttitude`, recall via `DirectiveGotoOp`), §8 (reputation API)
- `local/research/R6-copilot-sidecar.md` §3 (protocol), §5.4 (output schema), §6 (memory)
- `local/research/R5-sp-architecture.md` §5 (messaging), §3.3 (persistence)

## Ownership

- **Owns:** `src/contracts/` (wingmen.hpp, hiring.hpp, escalation.hpp, and edits to existing contracts *only* for additive Wave-4 needs), `docs/spec/`, `docs/plan/OWNERSHIP.md`, contract stubs under `src/module/stubs/`, and the Gate-time addendum sections of the Wave-4 specs.
- **Reads:** all merged code.
- **Must not touch:** implementations in `src/logic/*` and `src/game/*`. An existing contract needing a breaking change ⇒ report it; the orchestrator decides (and may open a FIX package).

## Contract

- **Consumes:** existing platform, clock, events, persistence, spawn, AI, UI, inventory, carrier, encounter and reflex contracts.
- **Provides:** the files in REQ-1 to REQ-6.

## Tasks

1. Inventory what Waves 1–3 actually merged: grep contracts and specs, and read `state/DECISIONS.md` and `state/DEGRADED.md`.
2. Draft the headers and specs; each type and function gets a doc comment with units, thread (main only), and lifetime.
3. Write stub implementations and make the module build.
4. Write `docs/spec/wave4-contracts.md`: a one-page orientation for the four Wave-4 agents (who owns what, the call graph, event flow).
5. Run `ci.sh --quick`.

## Acceptance (automated)

- `ci.sh --quick` green. Win32 build includes the stubs. Import check clean.
- Host test `contracts_compile` compiles every header in isolation (one TU per header) under both native clang++ and clang-cl.
- The `persistence` host test round-trips a JSON containing the new sections, and migrates the previous version's golden file.
- Review checklist: every REQ maps to a file and section.

## Engine facts to rely on / verify

- S-NPC: follow/attack-by-rep behavior; jump handling for followers (R2 fact 8: followers try to dock or jump with the leader).
- S-PERF: the army-scale threshold value for the warning.

## Pitfalls

- Don't design APIs that call `pub::` off the main thread, or that hold engine pointers across ticks without revalidation (R5 §2).
- Faction ids: rep group via `pub::Reputation::GetReputationGroup`, not the 16-bit faction hash (R3 §10).

## Fallbacks and degrade path

- If an escalation lever is unproven, declare it PROPOSED with a no-op stub. The design agent spikes it.
- If ENGINE_FACTS shows wingmen can't follow through jumps natively, the contract includes despawn/respawn-on-JumpInComplete semantics (R2 §4.4 step 6).

## Report

Standard brief format. List new and changed files, PROPOSED vs VERIFIED capabilities, and any breaking-change requests.

## Gate-time addendum

(orchestrator)
