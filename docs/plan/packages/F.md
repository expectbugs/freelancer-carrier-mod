# F: Final gate, build report and completion

- **Type:** gate, **run by the orchestrator itself** (CONVENTIONS §10, BUILD_PLAN §7). The orchestrator may spawn evidence-collection agents for individual REQ-1 steps. They write evidence to `$FLMOD_TESTRUNS/f-<step>-<ts>/` and report back. **Only the orchestrator** writes `state/**`, publishes the release and sets `COMPLETE`; a worktree agent never does.
- **Wave:** 5 (final; the ledger has an `F` row)
- **Depends on:** every package `MERGED` or `DEGRADED` (including W5-SOAK and any `W5-SOAK-R<n>` re-runs, W5-COMPAT, W5-SHIP and all FIX-*)
- **Unblocks:** `BUILD_STATUS: COMPLETE`

## Goal

Prove the finished build meets BUILD_PLAN §0 (definition of done), and hand Adam a single honest document that tells him:

- what he got;
- what is degraded and why;
- what evidence backs it;
- what to tweak;
- how to play or uninstall.

Then mark the build complete and notify him.

## Requirements

- **REQ-F-1.** Execute TESTING §F on the **release-candidate SHA**. `v1.0.0` is published on exactly this SHA, but only after F passes (REQ-5, CONVENTIONS §11). Steps, with evidence:
  1. `ci.sh --full` green.
  2. Condensed §M1–§M3 re-run: regression-tagged scenario per step, plus one full playbot pass of §M1 steps 2–6 by input.
  3. A 6-h cumulative soak clean. The W5-SOAK RC run counts if it was on this exact SHA; otherwise re-run.
  4. The §SaveCompat full matrix green, including uninstall relocation into an unmodded lane.
  5. Fresh `prefix-carrier` install from scratch via `ship/install.sh`, then launch via `/home/user/freelancer/play-carrier.sh`, then buy a carrier, then quit cleanly. Test saves are removed afterwards.
  6. Adam's original install is untouched: a sha256 manifest comparison of `prefix/.../EXE` and `DATA` against `local/play-prefix-manifest.sha256` (via `tools/play_prefix_manifest.sh verify`) (captured at build start), plus a launch smoke on a reflink **clone** of `prefix` (never the original).
  7. Public repo audit:
     - `tools/check_public.py` over the tracked tree;
     - `tools/check_public.py --release <dir>` over the release package;
     - a history scan: every commit's `git log -p` text checked against the same patterns, including the local blocklist. Use the checker's history mode if P0-REPO provided one; otherwise pipe each commit's diff through it.
- **REQ-F-2.** Check every BUILD_PLAN §0 item:
  - all packages MERGED or DEGRADED, with DEGRADED entries complete in `state/DEGRADED.md`;
  - every gate PASSED (G0a, G0b, G1, M1, M2, M3);
  - `prefix-carrier` and `play-carrier.sh` exist and work;
  - the W5-SHIP draft/rc release exists (publication is REQ-5);
  - the report is written;
  - the notification is sent.
- **REQ-F-3.** Write **`docs/BUILD_REPORT.md`** (public: no personal identifiers, no game-file content). Sections, in this order:
  1. **Summary:** 5 lines. What was built, the platform track chosen (A/B), the base plan (A/B), the build dates, the release link.
  2. **How to play:** `/home/user/freelancer/play-carrier.sh`; where saves go (`FreelancerCarrier` folder); push-to-talk key (numpad period by default); first steps (where to buy a carrier); a link to `docs/PLAYER_GUIDE.md`.
  3. **What's in the mod:** feature list mapped to DESIGN.md sections (D-x.y), each with status `DONE | DEGRADED | NOT DONE`.
  4. **Degraded and missing items:** from `state/DEGRADED.md`. For each: what's missing, why (the evidence), what a future session needs to finish it, and the config flag if it's switched off.
  5. **Evidence:** a gates table (gate, date, SHA, key numbers, report path). Test totals: host tests, scenarios, playbot steps, soak hours, crashes found and fixed. Links to the gate reports in `state/gates/`.
  6. **Metrics vs targets:** the TESTING §Metrics table with measured values (travel times, ambush frequency by region, fight durations, carrier survival sim, FPS, address space, army-scale curve and warn threshold, copilot latency).
  7. **Tunables for Adam:** every YAML or config value someone chose on Adam's behalf (AUTONOMY §3.4), with its file path, current value, effect, and the decision log reference. Include: carrier class multipliers, upgrade prices, yard catalogs, ambush odds constants, distress spawn distance, wingman pricing and wages, crew replacement time, boss respawn time, escalation tunables, LLM model and effort, mic source, PTT key, banter cooldown.
  8. **Engine facts discovered:** a short digest of `state/ENGINE_FACTS.md`, linking the full file. It is useful to any future modder.
  9. **Known issues:** from gate findings, MINOR and POLISH items, crashes not root-caused (with workarounds).
  10. **Not testable unattended:** a real microphone with live voice, subjective feel. What Adam should try first, as a short checklist.
  11. **Design docs to review:** `docs/design/ESCALATION.md`, `docs/design/CARRIERS.md` and any others, with one line each on what decisions they contain and how to request changes.
  12. **Uninstall:** `ship/uninstall.sh` (relocates saves first); the original install is untouched.
  13. **Repository map:** where things live; how to rebuild (`harness/ci.sh`, `ship/install.sh`).
- **REQ-F-4.** The orchestrator writes `state/gates/F.md` (evidence per REQ-1/2 item).
- **REQ-F-5.** Completion, by the orchestrator, in order:
  1. `tools/play_prefix_manifest.sh verify` → UNCHANGED. If it says CHANGED, investigate before anything else; that is a HALT-level risk.
  2. Publish: tag `v1.0.0` on F's SHA, push the tag, and publish the release (turn the W5-SHIP draft into `v1.0.0`, or `gh release create v1.0.0` with its notes and the source package). Assets follow CONVENTIONS §11 (source only unless the FLSDK license check passed).
  3. Restore the display settings (`tools/display-awake.sh stop`).
  4. Commit and push the report and `state/gates/F.md`.
  5. Update `state/BUILD_STATE.md` so its first line reads `BUILD_STATUS: COMPLETE`. Never touch any other line ordering.
  6. Send a push notification: "Freelancer carrier mod build COMPLETE — v1.0.0. Report: <GitHub URL of docs/BUILD_REPORT.md>. N degraded items." If the notification tool is unavailable, append the message to `state/NOTIFICATIONS.md`. The watchdog exits on the status line.
- **REQ-F-6.** If any REQ-1 step fails: apply BUILD_PLAN §7 (FIX packages, up to 3 gate attempts per criterion, then a documented exception). Never write COMPLETE while a BLOCKER-severity finding is open without a documented exception in the report.

## Context pack (read before running)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §10, §11)
- `docs/plan/BUILD_PLAN.md` §0, §7
- `docs/plan/AUTONOMY.md` §3–§4, §7
- `docs/plan/TESTING.md` §F (and all referenced sections)
- `docs/plan/DESIGN.md`
- `state/` (all files: ledger, decisions, degraded, engine facts, crashes, gates/)
- `docs/PLAYER_GUIDE.md`, `docs/COMPATIBILITY.md`, `docs/design/*`

## Ownership

- **Owns (orchestrator):** `docs/BUILD_REPORT.md`, `state/gates/F.md`, the release publication, and the `BUILD_STATUS` line at completion
- **Evidence agents own:** only their run dirs under `$FLMOD_TESTRUNS`
- **Reads:** everything
- **Must not touch:** product code, `/home/user/freelancer/prefix`

## Contract

- **Consumes:** the harness, ship scripts, gate reports.
- **Provides:** the final verdict and report.

## Tasks

1. Confirm the release-candidate SHA. Every REQ-1 step runs on it; any new commit means re-running the affected steps.
2. Run REQ-1 steps (parallelize lanes where independent).
3. Assemble the metrics and tunables from data files, decisions and gate reports. Verify every number against its source file; never copy from memory.
4. Write the report and F.md.
5. Completion steps (REQ-5).

## Acceptance (all automated)

- Every REQ-1 step has evidence paths that exist.
- `docs/BUILD_REPORT.md` contains sections 1–13. Every DESIGN D-x.y appears in section 3. Every DEGRADED ledger entry appears in section 4.
- `check_public.py` passes on the report.
- The ledger shows `BUILD_STATUS: COMPLETE` only after all of the above.

## Engine facts to rely on / verify

None new. Summarize the existing ones.

## Pitfalls

- Don't report a feature DONE because its package merged. DONE needs passing scenario evidence.
- The report is public. Keep personal identifiers (email, IPs, device serials, account labels) out; refer to `local/` for specifics if needed.

## Fallbacks and degrade path

If the GitHub release can't be published (network or auth) after retries with backoff:

1. finish everything else;
2. mark the release "pending" in the report, with the exact command;
3. notify.

The build is still COMPLETE if every other criterion holds (record the decision).

## Report

Evidence agents' final messages (saved as `state/reports/F-<step>-a<n>.md`) give per-step results and evidence paths. The orchestrator's own gate summary goes into `state/gates/F.md`.

## Gate-time addendum

(orchestrator)
