# ARCH-2: Contracts for Wave 3 (ambush, escort, Nomad boss, loss)

- **Type:** arch
- **Wave:** 3 (gate-time)
- **Depends on:** gate M1 PASSED (`state/gates/M1.md`, written by the orchestrator)
- **Unblocks:** W3-AMBUSH, W3-ESCORT, W3-NOMAD, W3-LOSS

## Goal

Freeze the interfaces Wave 3 needs, so four agents can build ambushes, escort travel, the Nomad boss and carrier loss in parallel without editing each other's code. Contracts are based on what Wave 2 actually shipped: read the merged code, reports, ENGINE_FACTS and the M1 report, not the plan's assumptions.

## Requirements

- **REQ-ARCH-2-1:** **carrier form-swap contract** (D-7.4, D-7.6, D-9.5). The single API for turning a carrier between representations, used by W3-ESCORT, W3-AMBUSH and W3-LOSS:
  - `Solar` (dockable, Stopped)
  - `Ship` (NPC capital: EscortTravel, live UnderAttack in escort context)
  - `Absent` (simulated: DockedTravel, Away, AmbushWaiting)

  It specifies who calls it, preserved fields (hull fraction, loadout, stocks), deferral and the solar↔ship transform alignment. The implementation home goes in the ownership map. Proposal: W3-ESCORT implements ship form and swap; W2-CARRIER-GAME's executor gets a small extension via a `FIX`/addendum if needed.
- **REQ-…-1b** (CONVENTIONS §8): **sub-waves 3a → 3b.** W3-ESCORT, W3-NOMAD and W3-LOSS (3a) start first. W3-AMBUSH (3b) starts after ESCORT and LOSS merge. Contracts must let 3a packages build and test without W3-AMBUSH: ESCORT's escort-ambush entry point and LOSS's destroy path are callable from devbridge test verbs.
- **REQ-…-1c** (D-9.5, CONVENTIONS §9): **held fights and reload.** `RestoreHeldFight(carrier)` is called by W2-CARRIER-GAME's load restore for an UnderAttack carrier with the player docked aboard. W3-AMBUSH implements it: thaw the held attackers in "hold" mode (keep distance; carrier invulnerable) before launch is allowed. Also freeze who emits `Attacked` / `Won` for non-ambush attacks on a Stopped carrier (W2-CARRIER-GAME's damage watcher) versus ambush outcomes (W3-AMBUSH hooks).
- **REQ-…-2:** **ambush contract** (D-9). `AmbushOdds` inputs and outputs:
  - per-leg exposure from W1-WORLD;
  - CD-capable fraction per (system, faction) from generated data (`R3-data/system_combat_presence.json` equivalent produced by W1-DATA at deploy);
  - reputation, cargo value, interdiction-dampener modifier.

  Roll API (deterministic per-carrier RNG from W2-CARRIER-LOGIC), lineup request (W2-ENCOUNTER generator), outcome mapping to carrier commands (`Won`/`Lost`/`PlayerLeft`), and the distress UX calls.
- **REQ-…-3:** **escort controller contract** (D-7.4–7.7). Inputs: route legs, live/away status. Outputs: AI directives through W1-SPAWN AI helpers, gate-transition protocol, stuck-detection events, fallback steering. Plus events consumed by W3-AMBUSH (escort ambush on the spot).
- **REQ-…-4:** **Nomad boss contract** (D-12). Boss encounter definition id, roam/seek behavior API on W2-ENCOUNTER, unlock flag name (`nomad_gate_unlocked`, persisted and mirrored in the `.fl`), respawn timer persistence, and the Gammu-yard flag consumer (W2-YARD already reads the flag; confirm the name).
- **REQ-…-5:** **loss contract** (D-8.3–8.5). Carrier-destroyed event payload; salvage manifest (everything aboard); salvage-crate API and tractor/pickup conversion; hangar auto-launch request (consumed by W4 later; W3 provides the event); cleanup ordering with W2-CARRIER-LOGIC (Destroyed record removal) and W2-CARRIER-GAME (base binding release; never leave the player docked at a destroyed carrier's base).
- **REQ-…-6:** **docs.** Update `docs/spec/` with one file per contract (`ambush.md`, `escort.md`, `nomad.md`, `loss.md`, `carrier_forms.md`), headers `src/contracts/{ambush,escort,nomad,loss,carrier_forms}.hpp`. Extend the frozen verb and event table in `docs/spec/devbridge.md` with the `ambush.*`, `escort.*`, `nomad.*` and `loss.*` namespaces (CONVENTIONS §4: `ev=` names, `va_*` keys). Include sequence diagrams in text for the tricky flows:
  - docked ambush with forced stop and launch;
  - an escort jump through a gate with the player following and not following;
  - an away ambush thawing on arrival;
  - carrier death with the player nearby;
  - a reload while docked aboard during a held fight.
- **REQ-…-7:** **build.** Headers compile in the host and i686 builds; stub implementations make the module link; `harness/ci.sh` stays green.
- **REQ-…-8:** **ownership map update.** Edit `docs/plan/OWNERSHIP.md` directly (ARCH packages may; BUILD_PLAN §6 conventions), including Wave-3 test-asset directories. Also write the "Gate-time addendum" sections of the four W3 specs.

## Context pack (read before writing code)

- `CLAUDE.md`, `CONVENTIONS.md` (all), `BUILD_PLAN.md` §2, §6–8, `DESIGN.md` §7–10, §12, §14
- `TESTING.md` §M2, §Metrics (ambush frequency bands)
- `state/gates/M1.md`, `state/reports/*` (W2 package and M1 reports), `state/ENGINE_FACTS.md`, `state/DEGRADED.md`, `state/DECISIONS.md`, `state/QUARANTINE.md`
- Merged code: `src/contracts/`, `src/logic/carrier/`, `src/game/carrier/`, `src/logic/encounter/`, `src/game/encounter/`, `src/game/loadout/`, `src/logic/reflex/`, `src/logic/world/`
- The package specs W3-AMBUSH, W3-ESCORT, W3-NOMAD, W3-LOSS (this folder)

## Ownership

- **Owns:** `src/contracts/`, `docs/spec/`, `docs/plan/OWNERSHIP.md`, and the Gate-time addendum sections of the W3 specs
- **Reads:** everything
- **Must not touch:** implementation code (stubs only inside `src/contracts/` if needed for linking)

## Contract

- **Provides:** the frozen Wave-3 contracts above.

## Tasks

1. Inventory the Wave 2 reality (APIs actually merged, deviations recorded in reports).
2. Draft the contracts and specs; resolve every overlap between the four W3 packages explicitly (who calls whom).
3. Build stubs; CI green.
4. Write the gate-addendum notes for each W3 package (contract paths and the key decisions).

## Acceptance (all automated; the agent runs them and attaches evidence)

- Headers compile (host and i686); CI green.
- A reviewer checklist in the report shows every W3 REQ maps to a contract entry point.
- No contract requires a W2 package to change behavior, unless listed as an explicit `FIX-*` request with rationale.

## Engine facts to rely on / verify

S-NPC (capital travel, JumpIn, freeze/thaw, loot) and S-BASE (solar/base binding) are referenced by id in each spec.

## Pitfalls

Don't design contracts around unverified engine behavior. If a needed fact is missing, add a "verify first" task to the consuming package spec addendum.

## Fallbacks and degrade path

If a W3 feature can't be contracted cleanly because of a W2 degrade, specify the reduced contract and note the degraded behavior.

## Report (the agent's final message)

Per the template: the list of contract files, the ownership changes proposed, and the per-package addendum notes.

## Gate-time addendum

M1 report path, degraded list, attempt and prior notes.
