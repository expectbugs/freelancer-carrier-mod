# W5-SOAK: Long soaks, crash triage, performance and memory hardening

- **Type:** test (+ triage)
- **Wave:** 5
- **Depends on:** gate M3 PASSED (`state/gates/M3.md`, written by the orchestrator)
- **Unblocks:** W5-SHIP, F

## Goal

Before Adam ever plays it, the mod survives hours of varied, abusive play without a crash, hang, address-space exhaustion or save corruption, and every crash found along the way is understood and fixed (through FIX packages) or documented.

## Requirements

- **REQ-W5-SOAK-1:** Write the journey **mix files** `harness/soak/mixes/w5_*.yaml` (this package's only harness ownership; CONVENTIONS §14), so the W1-HARNESS generator `harness/soak/journey.py` covers **every** merged feature, weighted by risk. If the generator lacks an action this needs, write a FIX proposal for W1-HARNESS's code rather than editing it. The mixes cover:
  - carrier state transitions (all 7 states) and fleets up to 8;
  - yard buy and retrofit;
  - forced and natural ambushes in all three player situations;
  - escort through gates;
  - the Nomad boss;
  - carrier destruction and rebuy;
  - hire, wages and permadeath;
  - army-scale bursts;
  - escalation events and takeovers;
  - save/load at random moments, including mid-transition;
  - F1 pause (input lane only), game restarts every 45 min;
  - sidecar kill and restart (the sidecar always runs in its test profile: fake LLM, null audio, port 29170 + lane; CONVENTIONS §13);
  - `debug crash` / `debug hang` probes once per run, to prove the crash and hang detection still works.
- **REQ-W5-SOAK-2:** Run ≥ **6 hours cumulative** of soak across ≥ 3 lanes, with each lane ≥ 1 h continuous (TESTING §Soak; this package's run is the F gate's soak evidence if done on the release candidate commit). Seeds are recorded per segment.
- **REQ-W5-SOAK-3:** Track `ev=mem` and `ev=perf` series per lane into `soak.csv`. Produce plots (PNG via matplotlib in a venv) and a trend analysis:
  - `va_free_mb` never below 300 MB;
  - growth ≤ 20 MB/h after warm-up;
  - fps floors per §Metrics.

  Identify leaks with targeted repro scenarios.
- **REQ-W5-SOAK-4:** Crash triage per TESTING §CrashTriage for every CRASH or HANG:
  - signature;
  - RVA → crash-offsets lookup (`/home/user/freelancer/refs/StarportKnowledgeBase/static/payloads/crash-offsets.json`, via `harness/triage.py`);
  - minidump for hangs: through the wine guard, `source tools/env.sh; WINEPREFIX=<lane> winedbg --minidump …`, never a raw wine path;
  - **≥ 10 hypotheses**;
  - the discriminating experiment;
  - a deterministic repro scenario (seed);
  - root cause.

  Record everything in `$FLMOD_TESTRUNS/<run>/CRASH-<n>.md` and in the report. The orchestrator copies it into `state/CRASHES.md` (`state/**` is orchestrator-only, CONVENTIONS §14).
- **REQ-W5-SOAK-5:** For each root-caused bug, write a **FIX proposal** (spec-ready: problem, evidence, repro scenario, suspected code, the fix approach, the regression test). The orchestrator turns these into `FIX-<n>` packages (ledger rows, CONVENTIONS §10). After each FIX merges, the orchestrator schedules a re-run of the affected soak segment **as its own ledger row** `W5-SOAK-R<n>`, briefed from this spec.
- **REQ-W5-SOAK-6:** Performance hardening proposals where §Metrics floors are missed (spawn staggering, paper-mode thresholds, encounter caps for performance only, never gameplay caps; D-1.6).
- **REQ-W5-SOAK-7:** Final soak report `$FLMOD_TESTRUNS/w5-soak-<ts>/REPORT.md` (the orchestrator files it as gate evidence): hours per lane, seeds, crashes found and fixed, open issues, plots, and the release-candidate SHA with its clean 6-h run.

## Context pack (read before writing code)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §7 locks, §10, §13, §14)
- `docs/plan/TESTING.md` §Soak, §CrashTriage, §Metrics, §SaveCompat
- `state/ENGINE_FACTS.md`, `state/CRASHES.md` (if any), `state/DEGRADED.md`, `state/gates/M*.md`
- `docs/spec/devbridge.md` (all namespaces)
- `local/research/R4-lore-and-testloop.md` §A1 (crash offsets, limits), §B7 (logs and crash detection on Wine)
- Crash offsets: `/home/user/freelancer/refs/StarportKnowledgeBase/docs/fl-binaries/crash-offsets.mdx` and the JSON payload

## Ownership

- **Owns:** `harness/soak/mixes/w5_*.yaml` only (CONVENTIONS §14), and scenario files under `harness/scenarios/soak_repros/`
- **Reads:** everything
- **Must not touch:** product code (fixes go through FIX packages), the rest of `harness/soak/` (W1-HARNESS), and `state/**`

## Contract

- **Consumes:** the harness, devbridge and all `*.` namespaces.
- **Provides:** soak tooling, the report, FIX proposals.

## Tasks

1. Extend the journey generator; host-test its action grammar (it produces only valid command sequences).
2. Run soak segments; triage as you go.
3. Analyze trends and write the report.
4. After FIX merges (the orchestrator runs FIX packages), re-run the affected segments and do a final clean 6-h cumulative run on the release candidate.

## Acceptance (all automated)

- The report shows ≥ 6 h cumulative clean on a single commit (the RC), every crash found root-caused or documented, and the memory/fps criteria met (`harness/metrics_targets.yaml`).
- Every crash has a repro scenario tagged `regression`.

## Engine facts to rely on / verify

Record new crash causes and limits as ENGINE_FACTS.

## Pitfalls

- Never kill wine globally. Kill only the lane's wineserver.
- Disk space: the root filesystem has about 224 GB free (as of 2026-10-17). Prune old `$FLMOD_TESTRUNS` dumps, keeping the last 20 runs plus every crash's evidence.

## Fallbacks and degrade path

A crash that can't be root-caused within the attempt budget:

1. Find the feature trigger.
2. Gate the feature off in the risky path (config flag), or degrade it.
3. Record it in `state/DEGRADED.md` and BUILD_REPORT known issues.

## Report

Standard, plus the FIX proposals list and the RC SHA.

## Gate-time addendum

(orchestrator)
