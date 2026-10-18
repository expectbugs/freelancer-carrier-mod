# M3-PLAYTEST: Bot playthrough #3 (crew, voice, escalation) + 3-hour soak

- **Type:** test (playbot)
- **Wave:** 4 (milestone M3)
- **Depends on:** W4-WINGMEN, W4-HIRING and W4-BRAIN MERGED or DEGRADED, and **W4-ESCALATION-DESIGN MERGED or DEGRADED**, plus **every W4-ESC-* row it created** (or W4-ESC-FALLBACK, if the design degraded) MERGED or DEGRADED.
  - M3 must not start while the design package is unfinished: its W4-ESC-* rows don't exist in the ledger until it merges, so "all W4 rows done" can look true too early.
  - The wave-4 integration pass (CONVENTIONS §8) must also be complete.
- **Unblocks:** Wave 5 (W5-SOAK, W5-COMPAT)

## Goal

Stand in for Adam's third playtest: prove, by actually playing through the real UI and input paths, that crew and hired wingmen, voice and LLM orders, and the escalation system work together in the real game, and that the game stays stable at scale for 3 hours.

Produce the evidence report from which the **orchestrator** writes `state/gates/M3.md` (CONVENTIONS §10). This package never writes `state/`.

## Requirements

- **REQ-M3-1:** Execute **TESTING.md §M3 exactly** (it is authoritative), every step in order. Method:
  - per §Playbot: synthetic XTEST input under `lane.sh acquire --input` for player actions, never `xdotool … --window`; devbridge for setup and observation;
  - judgments per §Vision.
- **REQ-M3-2:** Every step records intent, actions, evidence (HARNESS lines, screenshots, vision verdicts, metrics) and PASS/FAIL/SKIP/SKIP-DEGRADED/SKIP(quarantined)/BLOCKED in `$FLMOD_TESTRUNS/playbot-m3-<ts>/JOURNAL.md`.
  - **Continue past failures** (CONVENTIONS §10). Each failure gets a FIX proposal.
  - Feel notes within metric ranges go to a Tuning notes section.
- **REQ-M3-3:** Exploratory play ≥ 30 minutes (§Playbot 5) around wingmen, hiring, voice, escalation and their interactions with carriers and ambushes. Break things on purpose:
  - order spam;
  - hire 100 then dismiss 90;
  - save/load mid-takeover;
  - F1 pause during the LLM reply;
  - kill the sidecar mid-sentence;
  - alt-tab.

  Every finding becomes a FIX proposal in the report.
- **REQ-M3-4:** §Metrics re-measurement, against `harness/metrics_targets.yaml`:
  - army-scale curve (10/25/50/100/200 followers) with fps_avg, fps_p1 and `va_free_mb`, measured under `lane.sh acquire --perf` (no other lane running);
  - copilot latency (grammar path and LLM path);
  - escalation performance budget (ships active during a house-war battle; FPS floors).
- **REQ-M3-5:** A **3-hour soak** (§Soak) across lanes, with the journey generator including wingmen, hiring and escalation actions. Zero crashes and hangs; address-space criteria met.
- **REQ-M3-6:** The real-LLM smoke (W4-BRAIN's `smoke-real-llm`) is the **only** step that uses the real brain (CONVENTIONS §13). Every other step, the soak and the lanes use the sidecar's test profile (fake LLM, null audio sink, port 29170 + lane).
  - The smoke asserts the brain sandbox: cwd `/home/user/freelancer/carrier-brain-cwd`, an allowlisted env, and zero tools and zero MCP servers in the stream-json `system/init`.
  - If a usage limit blocks it, retry up to 3 times with backoff over ≥ 2 hours before recording SKIP.
  - The real microphone is SKIP by design (unattended); use the W1-SIDECAR `--mic-file` WAV injection instead.
- **REQ-M3-7:** Regression: `harness/ci.sh --full` green at the tested commit, before and after the playthrough (the commit SHA is recorded).
- **REQ-M3-8:** Write the evidence report `$FLMOD_TESTRUNS/playbot-m3-<ts>/REPORT.md` (the orchestrator turns it into `state/gates/M3.md`) with:
  - the commit SHA;
  - per-step results with evidence paths;
  - metrics tables;
  - soak summary;
  - findings ranked BLOCKER/MAJOR/MINOR/POLISH;
  - a recommended gate verdict.

## Context pack (read before playing)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §4 verbs, §6 fixtures, §7 locks, §10, §13)
- `docs/plan/DESIGN.md` §11, §13 (and §7–§9 for interactions)
- `docs/plan/TESTING.md`: all of it, especially §Playbot, §Vision, §Metrics, §Soak, §M3
- `docs/design/ESCALATION.md`, `docs/design/CARRIERS.md`
- `state/ENGINE_FACTS.md`, `state/DEGRADED.md`, `state/QUARANTINE.md`, `state/gates/M1.md`, `state/gates/M2.md`, `state/reports/*` (Wave-4 reports)
- Specs (for expected behavior only; **do not read implementation code to decide whether behavior is right**): `docs/plan/packages/W4-*.md`, `docs/spec/devbridge.md`, `docs/spec/ipc.md`
- Harness docs: `harness/README.md` (W1-HARNESS), `harness/playbot/`

## Ownership

- **Owns:** `harness/playbot/journeys/m3/`, new scenario files under `harness/scenarios/milestones/m3/` (regression captures of what was played), and rubrics `harness/rubrics/m3_*.yaml` (BUILD_PLAN §6 conventions).
- **Reads:** everything.
- **Must not touch:** product code and `state/**`. You report bugs; you never fix them (independence, §Playbot 6).

## Contract

- **Consumes:** the harness, devbridge, scenario runner, playbot tools.
- **Provides:** the M3 gate report and new regression scenarios.

## Tasks

1. Fresh lanes from the current `main` build. Display awake confirmed.
2. Run §M3 steps 1–9 in order. Use the input lane for every "by input" action.
3. Exploratory session (REQ-3).
4. 3-hour soak (may run in parallel on other lanes while steps run, if lanes allow).
5. Metrics; `ci.sh --full`; write the gate report.

## Acceptance (all automated)

- `REPORT.md` exists, with every §M3 step carrying evidence paths that exist.
- No step is marked PASS without at least one HARNESS assertion or vision verdict backing it.
- Soak criteria met, or failures documented with seeds.
- The orchestrator's gate procedure (BUILD_PLAN §7) can decide from the report alone.

## Engine facts to rely on / verify

Re-verify S-PERF numbers with real wingmen; record any divergence as new facts.

## Pitfalls

- Input goes to the focused window. Always hold the input lock and `windowactivate --sync` before keys, and use XTEST, never `--window`.
- `time.skip` advances only the mod clock (§Devbridge). Engine-driven behavior needs real time.
- Don't let a stuck lane block the run: use `lane.sh reap`.

## Fallbacks and degrade path

If a step can't run because a dependency is DEGRADED, mark the step DEGRADED with a reference to `state/DEGRADED.md`. Continue with the rest.

## Report

Standard format plus the `REPORT.md` path, the FIX proposals list (each with repro steps, seed and evidence) and tuning notes. The orchestrator saves the message as `state/reports/M3-PLAYTEST-a<n>.md`.

## Gate-time addendum

(orchestrator)
