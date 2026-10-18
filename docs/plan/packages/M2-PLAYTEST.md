# M2-PLAYTEST: Bot playthrough #2 (danger and tiers) + 2-hour soak + ambush-frequency checks

- **Type:** test
- **Wave:** 3 milestone
- **Depends on:** every W3 package MERGED or DEGRADED (W3-ESCORT, W3-NOMAD, W3-LOSS, W3-AMBUSH), and the wave-3 integration pass (CONVENTIONS §8)
- **Unblocks:** gate M2 (written by the orchestrator), then ARCH-3 and Wave 4

## Goal

Replace Adam's second playtest. This package proves:

- ambushes in all three player situations (aboard, escorting, away), including held fights and frozen distress fights;
- escort travel across gates;
- tiers and the Nomad gate, with an unassisted boss run;
- permanent loss with salvage;
- the ambush-frequency model.

It also re-runs the M1 core as regression and soaks for 2 hours. The output is an evidence report, from which the **orchestrator** writes `state/gates/M2.md` (CONVENTIONS §10).

## Requirements

- **REQ-M2-PLAYTEST-1:** execute **TESTING.md §M2 exactly**, every step in order, on a fresh lane with the `main` build. TESTING §M2 is authoritative; this spec only adds procedure.
  - Input steps use XTEST under `lane.sh acquire --input` (CONVENTIONS §7).
  - Vision steps follow TESTING §Vision.
- **REQ-…-2** (TESTING §M2 step 10, §Metrics): **ambush frequency.** No in-game statistical rate comparison: about 2 expected events per run makes one unreachable. Instead:
  - (a) Host Monte Carlo (`ambush_mc`, W3-AMBUSH) for every region class × rep class, ≥ 10,000 simulated hours each, seeded. Every band in `harness/metrics_targets.yaml` must hold, and every MC result must agree with the analytic expectation Σ(λ·Δt) within 3σ.
  - (b) **Determinism:** `ambush.simulate 20 <seed>` in game reproduces the host MC result **exactly** for the same seed and data, on 4 routes: Li01→Li04, Br01→Br04, Bw03→Bw02, Ew03→Hi02.
  - (c) **Qualitative:** step 1's natural-roll run produced **≥ 1 natural ambush** on the forced high-exposure route.
- **REQ-…-3:** **survival balance check**, informational unless far off. Over 10 forced escort ambushes per tier, with a tier-matched balanced-class carrier, full nanobots and a passive player (godmode, not shooting), report the observed carrier win rate. The target is **≥ 70 %** (TESTING §Metrics; host-sim authoritative). If in game it falls outside 50–95 %, write a tuning note.
- **REQ-…-4:** **soak**, 2 hours (TESTING §Soak): `harness/soak/soak.sh --hours 2 --lanes 2 --seed <n>`, using the default journey mix, which covers ambushes of all kinds, escort legs, boss spawns, carrier deaths and rebuys, and save/load. The TESTING §Soak crash-free criteria apply, plus the object-leak check: registry counts return to baseline after each cycle.
- **REQ-…-5** (CONVENTIONS §10): **continue past failures.**
  - Each failure is recorded with evidence, and the playthrough continues. Dependent steps are marked `BLOCKED(<step>)`.
  - Each failure gets a FIX proposal (symptom, evidence, suspected owner, ten hypotheses).
  - Feel notes go in a separate Tuning notes section.
  - Report quarantined scenarios as `SKIP(quarantined)` and degraded features as `SKIP-DEGRADED(<ID>)`.
- **REQ-…-6:** never modify product code. This package only tests and reports.

## Context pack

- `CLAUDE.md`, `CONVENTIONS.md` (all: §2 flag `nomad_gate_unlocked`, §4 verbs, §6 fixtures, §7 locks, §9 state machine, §10, §13)
- `TESTING.md` §M2 (**the checklist**), §M1 (regression subset), §Playbot, §Vision, §Metrics, §Soak, §Fixtures, §Devbridge, §CrashTriage
- `DESIGN.md` §4, §6, §7, §8, §9, §12
- `state/gates/M1.md`, `state/reports/*` (W3 package reports, M1 report), `state/ENGINE_FACTS.md`, `state/DEGRADED.md`, `state/QUARANTINE.md`
- `docs/spec/` ambush, escort, nomad, loss, carrier_forms (ARCH-2)

## Ownership

- **Owns:** `harness/playbot/journeys/m2/`, `harness/rubrics/m2_*`
- **Reads:** everything
- **Must not touch:** product code, data, contracts, `state/**`

## Contract

- **Consumes:** devbridge commands from W1–W3 packages (CONVENTIONS §4), the harness/playbot framework, fixtures from `gen_fixture.py`, `ambush_mc`.
- **Provides:**
  - the evidence report `$FLMOD_TESTRUNS/playbot-m2-<ts>/REPORT.md`, with `JOURNAL.md`, `vision.json`, `metrics.json`, the MC tables and `soak/`;
  - the final message (saved by the orchestrator as `state/reports/M2-PLAYTEST-a<n>.md`).

## Tasks

1. Generate the fixtures TESTING §M2 names (`HARNESS_hostile_frontier`, `HARNESS_friendly_frontier`, `HARNESS_ew06_space`, `HARNESS_yard_*`, `HARNESS_endgame_eagle`) with `gen_fixture.py`. Use the fixture `carrier_json:` blocks for pre-built fleets.
2. Write `harness/playbot/journeys/m2/m2.yaml` (one block per TESTING §M2 step) plus its rubrics.
3. Run it, the measurements, the soak and the regression subset, then write the report.

## Procedure notes per TESTING §M2 step

These are additions only.

- **Long waits:** `time.skip <game seconds>`. One in-game day is 1800 s (D-7.14), so 3 days = 5400 s and 4 days = 7200 s.
  - If `time.skip` doesn't advance some subsystem consistently, record it as a FIX. Do the frozen-fight check in real time (10 min) and mark only the day-scale assertion SKIP, with the reason.
- **Forced vs natural:** forced ambushes (`ambush.force`) bypass odds. They are for exercising outcome paths only and never count toward frequency.
- **Held fight reload** (TESTING §M2 step 1):
  1. while docked during the alert, run `save HARNESS_m2_held`, quit, relaunch and load;
  2. assert the solar exists before any launch, attackers are holding, and the carrier's hull is unchanged;
  3. launch, then fight.
- **Boss:**
  - `nomad.engage_test` triggers seeking; assert that `ev=nomad.seek dist=` shrinks over 60 s.
  - The **unassisted** run uses godmode off and no `nomad.kill_boss`; time it against 5–12 min.
  - The flag check: `nomad_gate_unlocked` survives save/load, and the `.fl` contains the mirrored line (grep the save file).
- **Loss:**
  - `loss.kill <id>` once with an ambush active, and once on a **Stopped** carrier attacked by spawned hostiles (CONVENTIONS §9 path).
  - Collect pods with `loss.collect`, or by tractoring on the input lane once.
  - Assert that the manifest diff is empty.

## Acceptance

- Every TESTING §M2 step is PASS, `SKIP-DEGRADED`, `SKIP(quarantined)`, or FAIL with a FIX proposal. The orchestrator's gate procedure decides.
- REQ-2 (a), (b) and (c) hold.
- The REQ-3 survival rate is reported.
- The escort stuck-detection rule holds (no unrecovered stall), and the frame-rate floor holds with an ambush active (`--perf` measurement).
- The 2-hour soak is clean.

## Engine facts to rely on / verify

None new. Contradictions with ENGINE_FACTS are findings.

## Pitfalls

- Frequency claims must come from the host MC and `ambush.simulate`, never from forced rolls.
- Vision verdicts must quote what is seen. Re-shoot an unclear image once, then FAIL.

## Fallbacks and degrade path

None. The package reports truthfully; the gate policy applies (BUILD_PLAN §7, CONVENTIONS §10).

## Report (the agent's final message)

Per the template, plus:

- the `REPORT.md` path;
- the per-step table;
- the MC table (region × rep class → ambushes/hour, with the analytic expectation and σ);
- the determinism check results;
- the survival rate;
- the soak summary;
- FIX proposals and tuning notes;
- a verdict recommendation.

## Gate-time addendum

Build SHA, lanes (one input lane), degraded and quarantine lists, the `metrics_targets.yaml` revision in force, attribution trailer.
