# M1-PLAYTEST: Bot playthrough #1 (carrier v1 and copilot reflexes) + 60-minute soak

- **Type:** test
- **Wave:** 2 milestone
- **Depends on:** every W2 package MERGED or DEGRADED (W2-ENCOUNTER, W2-CARRIER-LOGIC, W2-LOADOUT, W2-REFLEX, W2-CARRIER-GAME, W2-YARD, W2-CARRIER-UI), plus the wave-2 integration pass (CONVENTIONS §8) completed
- **Unblocks:** gate M1 (written by the orchestrator), then ARCH-2 and Wave 3

## Goal

Replace Adam's first playtest with an automated, evidence-backed playthrough of everything Wave 2 delivers, played the way a player would. It is judged by HARNESS assertions, metrics and screenshot vision checks, then followed by a 60-minute soak.

The output is an evidence report from which the **orchestrator** writes `state/gates/M1.md` (CONVENTIONS §10). This package never writes `state/`.

## Requirements

- **REQ-M1-PLAYTEST-1:** execute **TESTING.md §M1 exactly**, every step in order, on the final `main` build deployed to a fresh lane. TESTING §M1 is authoritative; this spec only adds procedure.
  - Use the W1-HARNESS playbot framework (TESTING §Playbot): devbridge for setup and measurement, **real input** for UI interactions.
  - Input means XTEST to the focused window under `harness/lane.sh acquire --input`; never `xdotool … --window` (CONVENTIONS §7).
- **REQ-…-2:** run every vision checkpoint per TESTING §Vision. The playbot agent judges each screenshot against its rubric and records the verdict with its reasoning in `vision.json`.
- **REQ-…-3:** extract the TESTING §Metrics values the steps name, and compare them with `harness/metrics_targets.yaml`, the single source of thresholds.
- **REQ-…-4:** run the 60-minute soak (TESTING §Soak): `harness/soak/soak.sh --hours 1 --lanes 2 --seed <n>`, using the default journey mix, which exercises everything merged. Criteria are TESTING §Soak's crash-free criteria.
- **REQ-…-5** (CONVENTIONS §10): **continue past failures.** A failed step is recorded with its evidence and the playthrough continues with the next step. Steps that depend on the failed one are marked `BLOCKED(<step>)`.
  - For each failure, write a `FIX` proposal in the report: symptom, evidence paths, suspected owning package, ten hypotheses.
  - "Feel" observations within the metric ranges go in a separate **Tuning notes** section, which the orchestrator copies into `state/TUNING.md`. They are not FIX proposals.
  - Scenarios listed in `state/QUARANTINE.md` are reported as `SKIP(quarantined)`.
- **REQ-…-6:** never fix product code yourself. This package only tests and reports.
- **REQ-…-7:** degraded features (`state/DEGRADED.md`) are reported as `SKIP-DEGRADED(<ID>)` with the reference. Never as PASS.

## Context pack (read before running anything)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all: §4 verbs, §6 fixtures, §7 locks, §10 reports and failures, §13 sidecar test profile)
- `TESTING.md` §M1 (**the checklist**), §Playbot, §Vision, §Metrics, §Soak, §Fixtures, §Devbridge, §CrashTriage
- `DESIGN.md` §2.1, §5, §6, §7, §8.1, §11.1–11.3
- Every W2 package report, `state/reports/<ID>-a<n>.md` and `-r<n>.md` (absolute: `/home/user/freelancer/carrier-mod/state/reports/`)
- `state/ENGINE_FACTS.md`, `state/DEGRADED.md`, `state/QUARANTINE.md`
- W1-HARNESS docs (`harness/README.md`, `docs/spec/scenario_schema.md`)

## Ownership

- **Owns:** `harness/playbot/journeys/m1/`, `harness/rubrics/m1_*` (BUILD_PLAN §6 conventions)
- **Reads:** everything
- **Must not touch:** product code, data, contracts, `state/**`

## Contract

- **Consumes:** devbridge commands from all W1/W2 packages (CONVENTIONS §4), the harness/playbot framework, fixtures from `harness/fixtures/gen_fixture.py`.
- **Provides:**
  - the evidence report: `$FLMOD_TESTRUNS/playbot-m1-<ts>/REPORT.md`, plus `JOURNAL.md`, `vision.json`, `metrics.json`, `soak/`;
  - the final message (saved by the orchestrator as `state/reports/M1-PLAYTEST-a<n>.md`).

## Tasks

1. Generate the fixtures TESTING §M1 names: `HARNESS_yard_Li01_07_Base`, `HARNESS_lvl1_rich_fp9`, `HARNESS_endgame_eagle`, and the yard fixtures for the second purchase. Use `gen_fixture.py` (CONVENTIONS §6); never ad-hoc names.
2. Write the journey `harness/playbot/journeys/m1/m1.yaml`, one block per TESTING §M1 step, with rubrics `harness/rubrics/m1_*.yaml`.
3. Run it, collect evidence, and retry a failed step at most once, recording the flake. Then run the soak.
4. Write the report.

## Procedure notes per TESTING §M1 step

The steps themselves are in TESTING §M1; these are additions only.

- **Moving near the carrier:** `pos x,y,z` (teleport near it), then FL autopilot by synthetic keys. There is no `goto` verb.
- **Carrier commands:** `carrier.list`, `carrier.status <id>`, `carrier.travel`, `carrier.stop`; `base carrier:<name>` for a test dock. The step that requires a **real** dock request uses input.
- **Re-route step:** issue the second destination by **input** in the Travel tab. Assert `carrier.status` shows the new destination, the state stayed `DockedTravel`, and no `Stopped` event occurred in between.
- **Save/load:** `save HARNESS_m1_<state>`, then `quit`, relaunch with the harness loader, and `load HARNESS_m1_<state>`.
- **Travel-time metric:** measured on the first leg in **real game time**, with no `time.skip`.
- **Carrier auto-nanobots step:** spawn attackers with `spawn <hostile npc_def> 3 near=<carrier pos> tag=m1att`.
  - Expect `ev=carrier.state … state=UnderAttack`, `ev=reflex.use by=carrier`, and the stock decreasing.
  - `despawn m1att` (or kill them) → `Won` → `Stopped`.
  - Then `reflex.damage carrier:<id> hull=0.4` with **no attackers**: it still heals, and the state stays `Stopped` (healing outside a fight, CONVENTIONS §9).
- **Sidecar:** both reflex runs use the sidecar's **test profile** (`--profile test`: fake LLM, null audio sink, port 29170 + lane, CONVENTIONS §13), then a run with the sidecar stopped.

## Acceptance

- Every TESTING §M1 step is PASS, `SKIP-DEGRADED`, `SKIP(quarantined)`, or FAIL with a FIX proposal. The orchestrator's gate procedure (CONVENTIONS §10) decides the gate.
- The metrics named in TESTING §M1 are within `harness/metrics_targets.yaml`:
  - docked travel 2–4 min per system (balanced class);
  - dock-to-interior < 5 s;
  - save/load drift ≤ 1 % of route progress;
  - reflex decision ≤ 0.5 s game time;
  - frame-rate floor.
- The 60-minute soak meets the TESTING §Soak crash-free criteria.

## Engine facts to rely on / verify

None new. Report any behavior that contradicts ENGINE_FACTS as a finding.

## Pitfalls

- Input steps need the `input` lock and the keep-running patch. Screenshots of covered windows can be black, so use the harness screenshot method chosen in P0-HARNESS.
- Vision checks must state what was seen. Don't pass ambiguous images: re-shoot once from a better camera position, then FAIL.

## Fallbacks and degrade path

None. A test package reports truthfully. Failing steps produce FIX proposals, and the gate policy applies (BUILD_PLAN §7, CONVENTIONS §10).

## Report (the agent's final message)

Per the template, plus:

- the path to `REPORT.md`;
- a per-step PASS/FAIL/SKIP table;
- the metrics table;
- the soak summary;
- FIX proposals;
- tuning notes;
- a one-line verdict recommendation for the orchestrator.

## Gate-time addendum

Build SHA under test, lanes (one input lane required), degraded and quarantine lists, attribution trailer.
