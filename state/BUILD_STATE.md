BUILD_STATUS: IN_PROGRESS
<!-- First line is machine-read by tools/watchdog.sh. Values: NOT_STARTED | IN_PROGRESS | COMPLETE | HALTED | STOPPED -->

# Build ledger (orchestrator-owned; update after every state change, commit at least per merge/gate)

- **Current phase:** Phase 0 — session 2 resumed after the GPU-reset reboot; the 5 foundation packages continue with fresh agents
- **Track (G0a):** undecided
- **Base plan (S-BASE / G0b):** undecided
- **Lanes:** created by P0-HARNESS (baselines prefix-dev-base-A/B clean; lane-6/7/8 deleted). Measured: `LANES=4` on DXVK (~195 fps each), `LANES_SW=2` on wined3d-sw; Track A must use vdesk mode. **GPU healthy since the reboot** (VERIFIED 2026-10-18T01:34: vulkaninfo OK, Recovery Action None; driver 615.71.09, kernel 6.18.48) → `FLMOD_RENDERER=auto` = DXVK. `LANES=2` until P0-HARNESS measures concurrency. GPU-fault watch: agents log to `local/gpu-fault.log` and fall back to wined3d-sw.
- **Last update:** 2026-10-18T03:45 (TOOLCHAIN r3 PASS → polish; SIDECAR polish; REPO fix r2; DATATOOLS r2 + HARNESS r1 reviews running)

## Next actions
Session 2 (started 2026-10-18T01:34). Resume briefs: `state/briefs/RESUME-2026-10-18.md` (common) + `state/briefs/<ID>-resume.md`. check_public snapshot for siblings: `local/snapshots/check_public.py` (wp/P0-REPO @ 4e02754).
1. Wait for the 5 running agents (table below). Each turn: check `STOP`, heartbeat, `local/gpu-fault.log`.
2. After each fix report: save it to `state/reports/<ID>-f1.md`, then spawn a round-2 reviewer (`state/briefs/<ID>-r2.md` from REVIEWER_BRIEF_TEMPLATE; include the r1 findings and the f1 report). P0-HARNESS: save its report as `state/reports/P0-HARNESS-a1b.md` (attempt 1 continued); it gets its first review (r1) once it reports DONE.
3. Merge order once each reviewer PASSes: P0-REPO first, squashed (D106; it brings the hooks and checker; then `git push origin main` after `tools/check_public.py --tree .` and `--commits` on the whole history; check the first Actions run), then the others. Run `python3 -I tools/check_public.py --commits=main..wp/<ID>` before every merge (squash per D106 if only intermediate commits fail), then `harness/ci.sh` after it.
3a. P0-HARNESS fix round (after its r1 review): also add a shared baseline flock (baseline.sh edits/recreates baselines in place while lane.sh/prefix_clone may clone them; P0-TOOLCHAIN r3 note).
3b. After both DATATOOLS and HARNESS merge, harness deploy.py switches its dacom.ini block to a `harness.dacom` fltools.patch unit (D107).
4. When P0-TOOLCHAIN and P0-HARNESS are merged: brief and spawn P0-TRACK-A and P0-TRACK-B in parallel.
5. Run G0a (`docs/plan/packages/G0a.md`), then the S-* spikes in parallel, then G0b, then ARCH-0, then Wave 1.

## Package ledger
Status values: TODO, READY, BRIEFED, RUNNING, REVIEW, FIXING, MERGED, DEGRADED, BLOCKED, SKIPPED.
W4-ESC-* and FIX-* rows are appended when created.

| ID | Wave | Type | Deps | Status | Attempts | Branch @ SHA | Merged | Notes |
|---|---|---|---|---|---|---|---|---|
| P0-REPO | 0 | impl | — | FIXING (r2) | 1 | wp/P0-REPO @ 32ab66a | | r2 CHANGES_REQUIRED (MAJOR: R5 false positives on our schemas → D108 authored-data escape; R5 misses compact JSON/flow YAML; 6 MINOR) → fix round 2 sent 03:05; after merge: convert the short tailnet blocklist entry to `w:` form, amend CONVENTIONS §12 per D108; squash-merge (D106) |
| P0-TOOLCHAIN | 0 | impl | — | REVIEW PASSED (r3) → polish | 1 | wp/P0-TOOLCHAIN @ 370c47f | | r3 PASS (3 MINOR N1–N3) → polish round running while merge waits for P0-REPO. D110: ehprobe --crt both in TRACK-A/B + W1-PLATFORM acceptance. For TRACK-A brief: stray-DLL assertion must cover ucrtbase*/concrt140*/msvcp1?0*; binary-scan FLUF catch funclets; confirm FLUF non-CRT imports resolve in the lane prefix; ABI.md §6.7 hook template, §6.8 in-game EH items |
| P0-HARNESS | 0 | impl | — | REVIEW (r1) | 1 | wp/P0-HARNESS @ 181ebcc | | a1b PARTIAL (all REQs implemented; selftest 6 PASS/2 BLOCKED); D109 carries (1) Track A any-save crash (NOTES N7) → P0-TRACK-A, (2) post-campaign gate/bar check → W1-HARNESS after W1-SPAWN `target`; LANES=4 DXVK / LANES_SW=2; squash-merge (D106: a5bafe5); r1 reviewer running |
| P0-DATATOOLS | 0 | impl | — | REVIEW (r2) | 1 | wp/P0-DATATOOLS @ 8eb78e3 | | fix r1 DONE + D107 addendum (120 tests); r2 reviewer running; squash-merge (D106: 463eb68/1a99d13 fail --commits); note for W1-DATA brief: REQ-9 CLI conflicts with fltools/CONVENTIONS |
| P0-SIDECAR | 0 | impl | — | REVIEW PASSED (r2) → polish | 1 | wp/P0-SIDECAR @ 75da0e4 | | r2 PASS (5 MINOR); polish round running while merge waits for P0-REPO (ipc.md gaps a–f, per-session PTT state, warn rate-limit, play-port test safety, doc); merge after P0-REPO. D7 (lane.sh exports FLCOPILOT_FORCE_TEST_PROFILE=1) accepted, already on wp/P0-HARNESS. Cross-package: ptt_vk INI write at deploy → W2-REFLEX (DLL) + W1-DATA (deploy) briefs. Brain sandbox items UNVERIFIED until W4-BRAIN first run (--setting-sources "", init field names, ~/.claude/CLAUDE.md with HOME) |
| P0-TRACK-A | 0 | spike | P0-TOOLCHAIN, P0-HARNESS | TODO | 0 | | | |
| P0-TRACK-B | 0 | spike | P0-TOOLCHAIN, P0-HARNESS | TODO | 0 | | | |
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
Session-1 agents are gone (stopped for the reboot). Session-2 agents (spawned 2026-10-18T01:44, Opus 5.5 xhigh, worktree isolation):

| Agent name/id | Package | Role (impl/review) | Started | Notes |
|---|---|---|---|---|
| a98da3ea1147f6e70 | P0-REPO | impl (fix r2) | 2026-10-18T01:44 | f1 DONE @ 32ab66a; resumed 03:05 for fix round 2 |
| ad0f03e5949648e45 | P0-REPO | review r2 | 2026-10-18T01:57 | DONE 03:00: CHANGES_REQUIRED (state/reports/P0-REPO-r2.md) |
| a51e1fa9688258fbd | P0-TOOLCHAIN | impl (polish) | 2026-10-18T01:44 | f2 DONE @ 370c47f; resumed 03:45 for r3 MINOR polish |
| a3ce63ff4e332397d | P0-TOOLCHAIN | review r2 → r3 | 2026-10-18T02:03 | r3 PASS 03:42 (state/reports/P0-TOOLCHAIN-r3.md) |
| aa760a6d5172501fc | P0-HARNESS | impl (a1 cont.) | 2026-10-18T01:44 | a1b PARTIAL ~03:25 @ 181ebcc (idle; resume via SendMessage for fix r1) |
| ae9a5d0d12e392a5a | P0-HARNESS | review r1 | 2026-10-18T03:30 | |
| aeb69a8aaddaa49db | P0-DATATOOLS | impl (fix r1 cont.) | 2026-10-18T01:44 | f1 + D107 DONE @ 8eb78e3 (idle) |
| a1a1514f6667c4372 | P0-DATATOOLS | review r2 | 2026-10-18T02:47 | |
| ae243e39aecae6681 | P0-SIDECAR | impl (polish) | 2026-10-18T01:44 | f1 DONE @ 75da0e4; resumed 03:20 for MINOR polish |
| a0a202af5ab1a8be0 | P0-SIDECAR | review r2 | 2026-10-18T02:10 | DONE 03:15: PASS (state/reports/P0-SIDECAR-r2.md); resume to verify the polish |

## Lanes
| Lane | Prefix | Holder | Since |
|---|---|---|---|
