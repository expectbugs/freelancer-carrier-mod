# W4-ESC-<AREA>: <Title>   (template used by W4-ESCALATION-DESIGN; this file is `_ESC_TEMPLATE.md`, outside the `W4-ESC-*` glob)

> W4-ESCALATION-DESIGN copies this file to `docs/plan/packages/W4-ESC-<AREA>.md` for each implementation package and fills every section. The orchestrator adds each package to the ledger with the deps and owns given here.
>
> Keep the headings unchanged; they follow `_TEMPLATE.md`.

- **Type:** impl
- **Wave:** 4 (sub-wave 4b, CONVENTIONS §8)
- **Depends on:** W4-ESCALATION-DESIGN [+ other W4-ESC-* only if unavoidable; prefer a shared foundation package first]. Scenarios needing an unmerged sibling W4-ESC-* package are marked `DEFERRED(<ID>)` (CONVENTIONS §8).
- **Unblocks:** M3-PLAYTEST

## Goal

What this area adds to the escalation system, in player terms. One paragraph.

## Requirements

`REQ-W4-ESC-<AREA>-n`. Each cites `docs/design/ESCALATION.md` §… (and `DESIGN.md` D-13.x / D-1.x where relevant). Quote the design doc's numbers: thresholds, rates, compositions.

## Context pack (read before writing code)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all)
- `docs/plan/DESIGN.md` §1, §10, §13
- `docs/design/ESCALATION.md` (the relevant sections, plus the levers table)
- `docs/plan/TESTING.md` §M3 step 8, §Scenarios, §Metrics
- `state/ENGINE_FACTS.md`: the S-FACTION entries this area relies on
- Contracts: `src/contracts/escalation.hpp`, `encounter.hpp`, and others used
- Spike code `spikes/s_faction/<…>` that proved the levers used
- `local/research/…` sections as needed

## Ownership

- **Owns:** `src/logic/escalation/<area>/`, `src/game/escalation/<area>/`, `data/escalation/<area>/`, `harness/scenarios/escalation/<area>/`, `tests/host/escalation/<area>/`
- **Reads:** contracts, merged code, other escalation areas' public headers
- **Must not touch:** other areas' directories, contracts (propose additive changes in the report)

## Contract

- **Consumes:** …
- **Provides:** … (events `ev=esc.<area>.*`, devbridge `esc.<area>.*` commands per `docs/spec/devbridge.md` / CONVENTIONS §4, the persistence sub-blob with a version)
- **Game-data hygiene** (CONVENTIONS §12): committed data references vanilla bases, factions and NPCs by nickname only. Derived tables come from deploy-time generator plugins (`gen/plugins/escalation_<area>/`, owned by this package).

## Tasks

An ordered list: model first (host-tested), then game adapter, data, UI, scenarios.

## Acceptance (all automated)

- **Host tests:** the model math, matching the design doc's numbers; persistence round-trip and migration.
- **In-game scenarios** (≥ 2), showing each lever and stage this area owns. Each has the steps, the expected `HARNESS` lines, screenshots and a vision rubric. At least one is tagged `regression`.
- **Persistence:** a state change survives save/load and a game restart.
- **Metrics:** the performance budget from the design doc (active events, ships), within TESTING §Metrics FPS floors.
- **Negative:** the feature stays off before `campaign_complete`; corrupt sub-blob ⇒ reset to defaults with a warning, no crash.

## Engine facts to rely on / verify

List the S-FACTION fact IDs.

## Pitfalls

Capital death fuses, base solar handling, story-faction side effects, encounter crash rules (R4 §A1.4.7).

## Fallbacks and degrade path

From the design doc's levers table.

## Report

Standard brief report.

## Gate-time addendum

(orchestrator)
