BUILD_STATUS: IN_PROGRESS
<!-- First line is machine-read by tools/watchdog.sh. Values: NOT_STARTED | IN_PROGRESS | COMPLETE | HALTED | STOPPED -->

# Build ledger (orchestrator-owned; update after every state change, commit at least per merge/gate)

- **Current phase:** Phase 0 — foundation packages checkpointed for the GPU-reset reboot (resume per Next actions)
- **Track (G0a):** undecided
- **Base plan (S-BASE / G0b):** undecided
- **Lanes:** created by P0-HARNESS (baselines prefix-dev-base-A/B clean; lane-1/2 disposable; lane-6/7/8 leftovers). **GPU faulted at 2026-10-18 00:28 (D103); Adam is rebooting about 01:00 to reset it.** After the reboot, verify Vulkan works (Next actions 0).
- **Last update:** 2026-10-18T01:00 (all P0 agents checkpointed; reboot pending)

## Next actions
**RESUME AFTER THE GPU-RESET REBOOT (2026-10-18 ~01:00; Adam rebooted on purpose; see D103–D105).** Every agent was told to stop at a clean checkpoint before the reboot. No agent from the previous session survives. Each FIXING/RUNNING package is interrupted: continue it with a FRESH agent (attempt 1 continued; the fix-round count carries over).
0. `date -Is > local/heartbeat`; `tools/display-awake.sh start`. The GPU should be healthy again: check `timeout 20 vulkaninfo --summary` (no `vkCreateDevice failed`) and `nvidia-smi -q | grep 'Recovery Action'` (None). If Vulkan works, lanes use DXVK (`FLMOD_RENDERER=auto`), and `LANES` can go back above 2 once concurrency is proven. If it's still faulted, record that in the ledger, continue on wined3d-sw, and tell Adam.
1. Remove the stale agent worktrees so the branches can be checked out again: for each `.claude/worktrees/agent-*`, check `git -C <wt> status --short` is empty (all were clean at checkpoint), then `git worktree remove <wt>`; then `git worktree prune`. Never delete a dirty worktree — commit its contents to its branch first. The branches `wp/P0-*` and the reports in `state/reports/` hold everything.
2. Re-brief one fresh agent per package. Brief = the original `state/briefs/<ID>.md` plus a resume addendum: "continue from branch wp/<ID> at <sha>; read the RESUME POINT in <NOTES path> first; the review findings are in state/reports/<ID>-r1.md; finish fix round 1, then report with a short fix report (what changed per finding, tests, evidence, SHA)":
   - **P0-REPO** @ wp/P0-REPO (latest; the agent may report a checkpoint SHA) — fix round 1 of r1 (state/reports/P0-REPO-r1.md). RESUME POINT in harness/ci.d/NOTES-P0-REPO.md or tools notes (see the agent's checkpoint report in the ledger row).
   - **P0-TOOLCHAIN** @ ad47bb5 — RESUME POINT at the end of toolchain/NOTES.md. Remaining: re-run ci.d 20/50 plus the stale-binary test, README, PINS (FLUF URLs, redist pin), final load-proof + EH probe on both tracks, fix report. Open question for G0a/W1-PLATFORM: app-local native MSVC runtime for FLUF (Track A).
   - **P0-HARNESS** @ a5bafe5 (attempt-1 PARTIAL report: state/reports/P0-HARNESS-a1.md) — RESUME POINT at the top of harness/NOTES.md. Do first on DXVK: Track A boot (x11 + vdesk), dacom.dll stricmp crash triage (N7), concurrency at 2 and then 3–4 lanes; then spew allow-lists per track/renderer, A fixture validity, lvl1_rich_fp9, vdesk input gate, README, selftest.sh, check_public. prefix-lane-6/7/8 are leftovers and may be deleted.
   - **P0-DATATOOLS** @ 463eb68 — RESUME POINT in tools/fltools/NOTES.md. Remaining: tests for MAJOR 2/3 and the MINORs, the data-hygiene and validator-severity MINORs, report text, the marker-clash proposal.
   - **P0-SIDECAR** @ dbc1c9f — RESUME POINT in sidecar/NOTES.md. Remaining: tests (pause, late ack, ptt cancel, send timeout, ids, ports, brain, voice_smoke mocked, critical_hull clamp), README port, CUDA `voice_smoke --require-cuda` re-run on the healthy GPU, 20× suite, check_public, fix report.
3. After each fix report: save it to `state/reports/<ID>-f1.md`, then spawn a round-2 reviewer (`state/briefs/<ID>-r2.md` from REVIEWER_BRIEF_TEMPLATE; include the r1 findings and the f1 report). P0-HARNESS gets its first review once it reports DONE.
4. Merge order once each reviewer PASSes: P0-REPO first (it brings the hooks and checker; then `git push origin main` after `tools/check_public.py --tree .` and `--commits` on the whole history; check the first Actions run), then the others. Run `python3 -I tools/check_public.py --commits=main..wp/<ID>` before every merge, then `harness/ci.sh` after it.
5. When P0-TOOLCHAIN and P0-HARNESS are merged: brief and spawn P0-TRACK-A and P0-TRACK-B in parallel.
6. **GPU (D103):** while the GPU is faulted, check each turn whether Vulkan is back.
7. Run G0a (`docs/plan/packages/G0a.md`), then the S-* spikes in parallel, then G0b, then ARCH-0, then Wave 1.

## Package ledger
Status values: TODO, READY, BRIEFED, RUNNING, REVIEW, FIXING, MERGED, DEGRADED, BLOCKED, SKIPPED.
W4-ESC-* and FIX-* rows are appended when created.

| ID | Wave | Type | Deps | Status | Attempts | Branch @ SHA | Merged | Notes |
|---|---|---|---|---|---|---|---|---|
| P0-REPO | 0 | impl | — | FIXING | 1 | wp/P0-REPO @ 257ef54 | | r1 CHANGES_REQUIRED (4 MAJOR); fix round 1 |
| P0-TOOLCHAIN | 0 | impl | — | FIXING (checkpoint) | 1 | wp/P0-TOOLCHAIN @ ad47bb5 | | r1 fix round 1 mostly done: EH (c) fixed by -mstackrealign, (a)/(b) coding rules ABI.md §6, 27-case EH probe; remaining: re-run ci.d 20/50, README, PINS (FLUF URLs, redist pin), final acceptance + fix report; OPEN Q: app-local native MSVC runtime for FLUF (Track A) |
| P0-HARNESS | 0 | impl | — | RUNNING (checkpoint, PARTIAL a1) | 1 | wp/P0-HARNESS @ a5bafe5 | | report state/reports/P0-HARNESS-a1.md; RESUME POINT at top of harness/NOTES.md; first after reboot: Track A DXVK boot + dacom stricmp crash triage, concurrency, spew allow-lists, vdesk input gate |
| P0-DATATOOLS | 0 | impl | — | FIXING (checkpoint) | 1 | wp/P0-DATATOOLS @ 463eb68 | | r1 fix round 1 ~half done (MAJOR1 done; MAJOR2/3 code done, tests missing; hygiene+validator MINORs not started); RESUME POINT in tools/fltools/NOTES.md |
| P0-SIDECAR | 0 | impl | — | FIXING (checkpoint) | 1 | wp/P0-SIDECAR @ dbc1c9f | | r1 fix round 1 partly done; RESUME POINT in sidecar/NOTES.md (tests for pause/late-ack/ptt-cancel/ports/brain/critical_hull, README port, CUDA smoke re-run) |
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
None. All agents from session 1 were stopped at clean checkpoints for the 2026-10-18 01:00 reboot. Their former ids (af7c7d7d P0-REPO, afd32a81 TOOLCHAIN, a55157d6 HARNESS, a446e058 DATATOOLS, a5795216 SIDECAR, plus reviewers a6d079bb, aa8f1e46, a3d414fa, a1877e17) are unreachable after the reboot.

| Agent name/id | Package | Role (impl/review) | Started | Notes |
|---|---|---|---|---|

## Lanes
| Lane | Prefix | Holder | Since |
|---|---|---|---|
