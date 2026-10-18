BUILD_STATUS: IN_PROGRESS
<!-- First line is machine-read by tools/watchdog.sh. Values: NOT_STARTED | IN_PROGRESS | COMPLETE | HALTED | STOPPED -->

# Build ledger (orchestrator-owned; update after every state change, commit at least per merge/gate)

- **Current phase:** Phase 0 — all 5 foundation packages merged and pushed; platform bake-off running (P0-TRACK-A, P0-TRACK-B)
- **Track (G0a):** undecided
- **Base plan (S-BASE / G0b):** undecided
- **Lanes:** created by P0-HARNESS (baselines prefix-dev-base-A/B clean; lane-6/7/8 deleted). Measured: `LANES=4` on DXVK (~195 fps each), `LANES_SW=2` on wined3d-sw; Track A must use vdesk mode. **GPU healthy since the reboot** (VERIFIED 2026-10-18T01:34: vulkaninfo OK, Recovery Action None; driver 615.71.09, kernel 6.18.48) → `FLMOD_RENDERER=auto` = DXVK. `LANES=2` until P0-HARNESS measures concurrency. GPU-fault watch: agents log to `local/gpu-fault.log` and fall back to wined3d-sw.
- **Last update:** 2026-10-18T09:25Z (P0 foundation complete; TRACK-A/B starting; HARNESS follow-up)

## Next actions
Session 2 (started 2026-10-18T01:34). Resume briefs: `state/briefs/RESUME-2026-10-18.md` (common) + `state/briefs/<ID>-resume.md`. check_public snapshot for siblings: `local/snapshots/check_public.py` (wp/P0-REPO @ 4e02754).
1. Wait for the 5 running agents (table below). Each turn: check `STOP`, heartbeat, `local/gpu-fault.log`.
2. After each fix report: save it to `state/reports/<ID>-f1.md`, then spawn a round-2 reviewer (`state/briefs/<ID>-r2.md` from REVIEWER_BRIEF_TEMPLATE; include the r1 findings and the f1 report). P0-HARNESS: save its report as `state/reports/P0-HARNESS-a1b.md` (attempt 1 continued); it gets its first review (r1) once it reports DONE.
3. Merge order once each reviewer PASSes: P0-REPO first, squashed (D106; it brings the hooks and checker; then `git push origin main` after `tools/check_public.py --tree .` and `--commits` on the whole history; check the first Actions run), then the others. Run `python3 -I tools/check_public.py --commits=main..wp/<ID>` before every merge (squash per D106 if only intermediate commits fail), then `harness/ci.sh` after it.
3a. DONE 09:25Z: all 5 P0 foundation packages merged + pushed (HARNESS b13db01). TRACK-A/B spawned. HARNESS follow-up wp/P0-HARNESS-b (r2 MINORs + harness/tests as a stage-30 root, D113) with the HARNESS agent; review by ae9a5d0d12e392a5a; merge --no-ff.
3b. After both DATATOOLS and HARNESS merge, harness deploy.py switches its dacom.ini block to a `harness.dacom` fltools.patch unit (D107).
4. When P0-TOOLCHAIN and P0-HARNESS are merged: brief and spawn P0-TRACK-A and P0-TRACK-B in parallel.
5. Run G0a (`docs/plan/packages/G0a.md`), then the S-* spikes in parallel, then G0b, then ARCH-0, then Wave 1.

## Package ledger
Status values: TODO, READY, BRIEFED, RUNNING, REVIEW, FIXING, MERGED, DEGRADED, BLOCKED, SKIPPED.
W4-ESC-* and FIX-* rows are appended when created.

| ID | Wave | Type | Deps | Status | Attempts | Branch @ SHA | Merged | Notes |
|---|---|---|---|---|---|---|---|---|
| P0-REPO | 0 | impl | — | MERGED | 1 | wp/P0-REPO @ 04e73d3; wp/P0-REPO-b @ 4ea9a86 | eb051ed (squash, D106); follow-up 3fa47f6 | r1/r2 CHANGES_REQUIRED, r3 PASS; first push 3404144, Actions PASS (3.11+3.13); follow-up P0-REPO-b (D112) PASS + micro-fix, merged --no-ff, ci --full PASS |
| P0-TOOLCHAIN | 0 | impl | — | MERGED | 1 | wp/P0-TOOLCHAIN @ 5825345 | 55013bf | r3 + r3b PASS; ci --full PASS after merge; EF-001..005. For TRACK-A/B briefs: see their draft addenda |
| P0-HARNESS | 0 | impl | — | MERGED | 1 | wp/P0-HARNESS @ e05dfc9 | b13db01 (squash, D106) | r1 CHANGES_REQUIRED, r2 PASS (4 MINOR → follow-up wp/P0-HARNESS-b); ci --full PASS; EF-007..012; D109 carried items (Track A save crash → TRACK-A; gate/bar → W1-HARNESS) |
| P0-DATATOOLS | 0 | impl | — | MERGED | 1 | wp/P0-DATATOOLS @ 496fa64 | 4d3e5d5 (squash, D106) | r2 + r2b PASS; ci --full PASS after merge (365 + 361 pytest); note for W1-DATA brief: REQ-9 CLI conflicts with fltools/CONVENTIONS |
| P0-SIDECAR | 0 | impl | — | MERGED | 1 | wp/P0-SIDECAR @ 1f25681 | 8bb3b79 | r2 + r2b PASS; EF-006. Cross-package: ptt_vk INI write at deploy → W2-REFLEX (DLL) + W1-DATA (deploy) briefs. Brain sandbox items UNVERIFIED until W4-BRAIN first run (--setting-sources "", init field names, ~/.claude/CLAUDE.md with HOME) |
| P0-TRACK-A | 0 | spike | P0-TOOLCHAIN, P0-HARNESS | RUNNING | 1 | | | |
| P0-TRACK-B | 0 | spike | P0-TOOLCHAIN, P0-HARNESS | RUNNING | 1 | | | |
| S-BASE | 0 | spike | G0a, P0-DATATOOLS | TODO | 0 | | | |
| S-NPC | 0 | spike | G0a, P0-DATATOOLS | TODO | 0 | | | |
| S-UI | 0 | spike | G0a, P0-DATATOOLS, P0-SIDECAR | TODO | 0 | | | |
| S-LOADOUT | 0 | spike | G0a, P0-DATATOOLS, S-BASE | TODO | 0 | | | |
| S-PERF | 0 | spike | G0a, P0-DATATOOLS | TODO | 0 | | | |
| ARCH-0 | 0 | arch | G0b | TODO | 0 | | | |
| W1-PLATFORM | 1 | impl | ARCH-0 | TODO | 0 | | | |
| W1-CORE | 1 | impl | W1-PLATFORM, W1-HARNESS | TODO | 0 | | | |
| W1-WORLD | 1 | impl | ARCH-0, P0-DATATOOLS | TODO | 0 | | | |
| W1-SPAWN | 1 | impl | W1-PLATFORM, W1-HARNESS | TODO | 0 | | | |
| W1-UI | 1 | impl | W1-PLATFORM, W1-HARNESS | TODO | 0 | | | |
| W1-DATA | 1 | impl | ARCH-0, P0-DATATOOLS | TODO | 0 | | | |
| W1-INVENTORY | 1 | impl | ARCH-0 | TODO | 0 | | | |
| W1-CARRIER-DESIGN | 1 | design | ARCH-0 | TODO | 0 | | | |
| W1-HARNESS | 1 | test | ARCH-0 | TODO | 0 | | | |
| W1-SIDECAR | 1 | impl | P0-SIDECAR, S-UI | TODO | 0 | | | |
| ARCH-1 | 1 | arch | G1 | TODO | 0 | | | |
| W2-ENCOUNTER | 2 | impl | ARCH-1 | TODO | 0 | | | |
| W2-CARRIER-LOGIC | 2 | impl | ARCH-1 | TODO | 0 | | | |
| W2-CARRIER-GAME | 2 | impl | W2-CARRIER-LOGIC, W2-LOADOUT | TODO | 0 | | | |
| W2-LOADOUT | 2 | impl | ARCH-1 | TODO | 0 | | | |
| W2-YARD | 2 | impl | W2-CARRIER-GAME | TODO | 0 | | | |
| W2-CARRIER-UI | 2 | impl | W2-CARRIER-GAME | TODO | 0 | | | |
| W2-REFLEX | 2 | impl | ARCH-1 | TODO | 0 | | | |
| M1-PLAYTEST | 2 | test | all W2 | TODO | 0 | | | |
| ARCH-2 | 3 | arch | M1 | TODO | 0 | | | |
| W3-AMBUSH | 3 | impl | W3-ESCORT, W3-LOSS | TODO | 0 | | | |
| W3-ESCORT | 3 | impl | ARCH-2 | TODO | 0 | | | |
| W3-NOMAD | 3 | impl | ARCH-2 | TODO | 0 | | | |
| W3-LOSS | 3 | impl | ARCH-2 | TODO | 0 | | | |
| M2-PLAYTEST | 3 | test | all W3 | TODO | 0 | | | |
| ARCH-3 | 4 | arch | M2 | TODO | 0 | | | |
| W4-WINGMEN | 4 | impl | ARCH-3 | TODO | 0 | | | |
| W4-HIRING | 4 | impl | W4-WINGMEN | TODO | 0 | | | |
| W4-BRAIN | 4 | impl | ARCH-3 | TODO | 0 | | | |
| W4-ESCALATION-DESIGN | 4 | design | ARCH-3 | TODO | 0 | | | |
| M3-PLAYTEST | 4 | test | all W4 incl. W4-ESC-* | TODO | 0 | | | |
| W5-SOAK | 5 | test | M3 | TODO | 0 | | | |
| W5-COMPAT | 5 | impl | M3 | TODO | 0 | | | |
| W5-SHIP | 5 | impl | W5-SOAK, W5-COMPAT | TODO | 0 | | | |
| F | 5 | gate (orchestrator) | W5-SHIP | TODO | 0 | | | |

## Gates
| Gate | Status | Report |
|---|---|---|
| G0a | PENDING | |
| G0b | PENDING | |
| G1 | PENDING | |
| M1 | PENDING | |
| M2 | PENDING | |
| M3 | PENDING | |
| F | PENDING | |

## Agents running
Opus 5.5 xhigh, worktree isolation.

| Agent name/id | Package | Role (impl/review) | Started | Notes |
|---|---|---|---|---|
| abdf0fe9fe8b438d3 | P0-TRACK-A | impl (spike, attempt 1) | 2026-10-18T09:27Z | from main 9ed5b56; brief state/briefs/P0-TRACK-A.md |
| abf9280af309b9ff8 | P0-TRACK-B | impl (spike, attempt 1) | 2026-10-18T09:27Z | from main 9ed5b56; brief state/briefs/P0-TRACK-B.md |
| aa760a6d5172501fc | P0-HARNESS | impl (follow-up wp/P0-HARNESS-b, D113) | 2026-10-18T09:27Z | r2 MINORs + harness/tests in stage 30; at most 1 lane |
| ae9a5d0d12e392a5a | P0-HARNESS | review (idle) | — | resume to review wp/P0-HARNESS-b |

## Lanes
| Lane | Prefix | Holder | Since |
|---|---|---|---|
