BUILD_STATUS: IN_PROGRESS
<!-- First line is machine-read by tools/watchdog.sh. Values: NOT_STARTED | IN_PROGRESS | COMPLETE | HALTED | STOPPED -->

# Build ledger (orchestrator-owned; update after every state change, commit at least per merge/gate)

- **Current phase:** Phase 0 — session 2 resumed after the GPU-reset reboot; the 5 foundation packages continue with fresh agents
- **Track (G0a):** undecided
- **Base plan (S-BASE / G0b):** undecided
- **Lanes:** created by P0-HARNESS (baselines prefix-dev-base-A/B clean; lane-1/2 disposable; lane-6/7/8 leftovers HARNESS may delete). **GPU healthy since the reboot** (VERIFIED 2026-10-18T01:34: vulkaninfo OK, Recovery Action None; driver 615.71.09, kernel 6.18.48) → `FLMOD_RENDERER=auto` = DXVK. `LANES=2` until P0-HARNESS measures concurrency. GPU-fault watch: agents log to `local/gpu-fault.log` and fall back to wined3d-sw.
- **Last update:** 2026-10-18T02:10 (REPO, TOOLCHAIN, SIDECAR in r2 review; HARNESS, DATATOOLS running)

## Next actions
Session 2 (started 2026-10-18T01:34). Resume briefs: `state/briefs/RESUME-2026-10-18.md` (common) + `state/briefs/<ID>-resume.md`. check_public snapshot for siblings: `local/snapshots/check_public.py` (wp/P0-REPO @ 4e02754).
1. Wait for the 5 running agents (table below). Each turn: check `STOP`, heartbeat, `local/gpu-fault.log`.
2. After each fix report: save it to `state/reports/<ID>-f1.md`, then spawn a round-2 reviewer (`state/briefs/<ID>-r2.md` from REVIEWER_BRIEF_TEMPLATE; include the r1 findings and the f1 report). P0-HARNESS: save its report as `state/reports/P0-HARNESS-a1b.md` (attempt 1 continued); it gets its first review (r1) once it reports DONE.
3. Merge order once each reviewer PASSes: P0-REPO first, squashed (D106; it brings the hooks and checker; then `git push origin main` after `tools/check_public.py --tree .` and `--commits` on the whole history; check the first Actions run), then the others. Run `python3 -I tools/check_public.py --commits=main..wp/<ID>` before every merge (squash per D106 if only intermediate commits fail), then `harness/ci.sh` after it.
4. When P0-TOOLCHAIN and P0-HARNESS are merged: brief and spawn P0-TRACK-A and P0-TRACK-B in parallel.
5. Run G0a (`docs/plan/packages/G0a.md`), then the S-* spikes in parallel, then G0b, then ARCH-0, then Wave 1.

## Package ledger
Status values: TODO, READY, BRIEFED, RUNNING, REVIEW, FIXING, MERGED, DEGRADED, BLOCKED, SKIPPED.
W4-ESC-* and FIX-* rows are appended when created.

| ID | Wave | Type | Deps | Status | Attempts | Branch @ SHA | Merged | Notes |
|---|---|---|---|---|---|---|---|---|
| P0-REPO | 0 | impl | — | REVIEW (r2) | 1 | wp/P0-REPO @ 32ab66a | | fix r1 DONE (f1 report; 183 tests); r2 reviewer running; squash-merge (D106); F9 blocklist entry added by orchestrator |
| P0-TOOLCHAIN | 0 | impl | — | REVIEW (r2) | 1 | wp/P0-TOOLCHAIN @ 0bceb22 | | fix r1 DONE (f1 report): -mstackrealign, EH probe 24/3/0 both tracks+CRTs, ci 10/20/50 PASS; CRT recommendation: builtin by default, native as TRACK-A fallback; r2 reviewer running |
| P0-HARNESS | 0 | impl | — | RUNNING (a1 continued) | 1 | wp/P0-HARNESS @ a5bafe5 | | report state/reports/P0-HARNESS-a1.md; RESUME POINT at top of harness/NOTES.md; first after reboot: Track A DXVK boot + dacom stricmp crash triage, concurrency, spew allow-lists, vdesk input gate |
| P0-DATATOOLS | 0 | impl | — | FIXING | 1 | wp/P0-DATATOOLS @ 463eb68 | | r1 fix round 1 ~half done (MAJOR1 done; MAJOR2/3 code done, tests missing; hygiene+validator MINORs not started); RESUME POINT in tools/fltools/NOTES.md |
| P0-SIDECAR | 0 | impl | — | REVIEW (r2) | 1 | wp/P0-SIDECAR @ 75da0e4 | | fix r1 DONE (f1 report): 306 tests x20 clean; CUDA voice_smoke PASS (stt 131 ms, tts first audio 374 ms); open proposal D7: lane.sh exports FLCOPILOT_FORCE_TEST_PROFILE=1; r2 reviewer running |
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
| a98da3ea1147f6e70 | P0-REPO | impl (fix r1 cont.) | 2026-10-18T01:44 | DONE 01:52 @ 32ab66a (idle; resume via SendMessage for fix r2) |
| ad0f03e5949648e45 | P0-REPO | review r2 | 2026-10-18T01:57 | |
| a51e1fa9688258fbd | P0-TOOLCHAIN | impl (fix r1 cont.) | 2026-10-18T01:44 | DONE ~02:00 @ 0bceb22 (idle; resume via SendMessage for fix r2) |
| a3ce63ff4e332397d | P0-TOOLCHAIN | review r2 | 2026-10-18T02:03 | |
| aa760a6d5172501fc | P0-HARNESS | impl (a1 cont.) | 2026-10-18T01:44 | from a5bafe5 |
| aeb69a8aaddaa49db | P0-DATATOOLS | impl (fix r1 cont.) | 2026-10-18T01:44 | from 463eb68 |
| ae243e39aecae6681 | P0-SIDECAR | impl (fix r1 cont.) | 2026-10-18T01:44 | DONE ~02:09 @ 75da0e4 (idle; resume via SendMessage for fix r2) |
| a0a202af5ab1a8be0 | P0-SIDECAR | review r2 | 2026-10-18T02:10 | |

## Lanes
| Lane | Prefix | Holder | Since |
|---|---|---|---|
