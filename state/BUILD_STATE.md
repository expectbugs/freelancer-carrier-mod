BUILD_STATUS: STOPPED
<!-- First line is machine-read by tools/watchdog.sh. Values: NOT_STARTED | IN_PROGRESS | COMPLETE | HALTED | STOPPED -->

# Build ledger (orchestrator-owned; update after every state change, commit at least per merge/gate)

- **Current phase:** Phase 0 — PAUSED at a clean checkpoint (Adam, 2026-10-18 ~10:05Z). All 5 foundation packages merged and pushed; platform bake-off (P0-TRACK-A, P0-TRACK-B) checkpointed mid-run.
- **Track (G0a):** undecided
- **Base plan (S-BASE / G0b):** undecided
- **Lanes:** created by P0-HARNESS (baselines prefix-dev-base-A/B; pool lanes 1–4, test lanes 6–8). `LANES=4` on DXVK at 60 fps (`d3d9.maxFrameRate`), `LANES_SW=2`. At pause: no lanes held, no wine processes. GPU healthy all of session 2 (Recovery Action None; nothing in local/gpu-fault.log).
- **Last update:** 2026-10-18T11:10Z (build PAUSED by Adam; resume with `tools/start-build.sh`)

## Next actions
**RESUME AFTER THE PLANNED PAUSE (Adam paused the build 2026-10-18 ~10:05Z; session 2 ended cleanly).** Resume with `tools/start-build.sh` (it resets line 1 to IN_PROGRESS and launches the orchestrator with tools/RESUME_PROMPT.txt). No agent from session 2 survives; every worktree was removed and every branch is clean. State at pause:
- MERGED and pushed (origin/main): P0-REPO (+ follow-up P0-REPO-b), P0-TOOLCHAIN, P0-SIDECAR, P0-DATATOOLS, P0-HARNESS (+ follow-up P0-HARNESS-b). GitHub Actions green.
- Checkpointed mid-run (attempt 1, PARTIAL, no review yet): P0-TRACK-A @ 855b285, P0-TRACK-B @ 1515d38. Reports `state/reports/P0-TRACK-{A,B}-a1.md`; resume briefs `state/briefs/P0-TRACK-{A,B}-resume.md`; RESUME POINT at the top of `spikes/track_{a,b}/NOTES.md`.

Steps:
0. AUTONOMY §5: check STOP; `date -Is > local/heartbeat`; `tools/display-awake.sh start`; `type -P wine` → tools/bin/wine. Check the GPU: `timeout 20 vulkaninfo --summary` (no vkCreateDevice error) and `nvidia-smi -q | grep 'Recovery Action'` (None); if faulted, lanes use `FLMOD_RENDERER=wined3d-sw` (D105) and tell Adam. Check `harness/lane.sh status` (expect no holders) and `pgrep -af wine` (expect none in lane prefixes).
1. Write a short common resume addendum `state/briefs/RESUME-<date>.md` (environment facts as found in step 0, the new session's commit trailer, "main moved on; merge main into your branch"), like `state/briefs/RESUME-2026-10-18.md`.
2. Spawn fresh agents for P0-TRACK-A and P0-TRACK-B in parallel (Opus 5.5, xhigh, worktree). Prompt: "Your brief: state/briefs/P0-TRACK-X.md, then state/briefs/P0-TRACK-X-resume.md, then state/briefs/RESUME-<date>.md. Read them fully and follow them." Lane budget: at most 2 pool lanes each.
3. In parallel, open FIX-1 (below): a small package for the harness selftest DLL's menu `load` bug (EF-007 correction). Owner paths: `harness/devbridge/` selftest DLL + its selftest assertion that the ship survives the first launch. Brief from AGENT_BRIEF_TEMPLATE + the finding in state/reports/P0-TRACK-B-a1.md; review loop as usual. Also fold in the track agents' harness proposals if small: `harness/baseline.sh` applies Track A's `always_regenerate_restart_file = false` (P0-TRACK-A A1), `@click --warp`, `RUN_WINEDEBUG` env override, `harness/scenario.sh` (CONVENTIONS §5 names it; Track B wrote an adapter).
4. When each track reports DONE: save `state/reports/P0-TRACK-X-a1b.md`, spawn its round-1 reviewer (REVIEWER_BRIEF_TEMPLATE; reviewers re-run items 2, 3, 7, 8, 9 per G0a), fix loop, merge (check_public --commits first; squash only if intermediate commits fail), ci.sh, push. Append engine facts from both reports (Track A NOTES A1–A4; Track B NOTES "Findings" 1–11).
5. Run G0a (`docs/plan/packages/G0a.md`): score both RESULTS.md tables, apply the decision rule, record state/gates/G0a.md, D-entry, ledger Track field, `harness/config/default_track`, push notification.
6. Then the S-* spikes in parallel (briefs from docs/plan/packages/S-*.md + gate addendum), G0b, ARCH-0, Wave 1.

Notes carried for later briefs:
- W1-DATA: its spec's REQ-9 CLI (`--prefix`, `uninstall`, gen/build.py) conflicts with fltools and CONVENTIONS (P0-DATATOOLS r1/r2); text_ids.json committed under data/strings/ (ARCH-0 decides).
- W2-REFLEX + W1-DATA: the deploy-time write of the DLL INI `ptt_vk` from the sidecar's `ptt_key` (P0-SIDECAR).
- W4-BRAIN: verify in its first live run `--setting-sources ""` parsing, the init-message field names, and whether ~/.claude/CLAUDE.md loads with HOME passed.
- W1-HARNESS: post-campaign fixture gate/bar checks once W1-SPAWN's `target` verb exists (D109); the vdesk fullscreen issue N19 (cause unknown).
- Authored data (W1-DATA, W1-CARRIER-DESIGN, W2-ENCOUNTER…): CONVENTIONS §12 authored-data marker; reviewers check every AUTHORED-DATA line in the CI public summary.

## Package ledger
Status values: TODO, READY, BRIEFED, RUNNING, REVIEW, FIXING, MERGED, DEGRADED, BLOCKED, SKIPPED.
W4-ESC-* and FIX-* rows are appended when created.

| ID | Wave | Type | Deps | Status | Attempts | Branch @ SHA | Merged | Notes |
|---|---|---|---|---|---|---|---|---|
| P0-REPO | 0 | impl | — | MERGED | 1 | wp/P0-REPO @ 04e73d3; wp/P0-REPO-b @ 4ea9a86 | eb051ed (squash, D106); follow-up 3fa47f6 | r1/r2 CHANGES_REQUIRED, r3 PASS; first push 3404144, Actions PASS (3.11+3.13); follow-up P0-REPO-b (D112) PASS + micro-fix, merged --no-ff, ci --full PASS |
| P0-TOOLCHAIN | 0 | impl | — | MERGED | 1 | wp/P0-TOOLCHAIN @ 5825345 | 55013bf | r3 + r3b PASS; ci --full PASS after merge; EF-001..005. For TRACK-A/B briefs: see their draft addenda |
| P0-HARNESS | 0 | impl | — | MERGED | 1 | wp/P0-HARNESS @ e05dfc9 | b13db01 (squash, D106); follow-up P0-HARNESS-b merged --no-ff | r1 CHANGES_REQUIRED, r2 PASS; follow-up P0-HARNESS-b PASS + micro-fix merged (D113: harness/tests in CI stage 30); ci --full PASS; EF-007..012; D109 carried items (Track A save crash → TRACK-A; gate/bar → W1-HARNESS) |
| P0-DATATOOLS | 0 | impl | — | MERGED | 1 | wp/P0-DATATOOLS @ 496fa64 | 4d3e5d5 (squash, D106) | r2 + r2b PASS; ci --full PASS after merge (365 + 361 pytest); note for W1-DATA brief: REQ-9 CLI conflicts with fltools/CONVENTIONS |
| P0-SIDECAR | 0 | impl | — | MERGED | 1 | wp/P0-SIDECAR @ 1f25681 | 8bb3b79 | r2 + r2b PASS; EF-006. Cross-package: ptt_vk INI write at deploy → W2-REFLEX (DLL) + W1-DATA (deploy) briefs. Brain sandbox items UNVERIFIED until W4-BRAIN first run (--setting-sources "", init field names, ~/.claude/CLAUDE.md with HOME) |
| P0-TRACK-A | 0 | spike | P0-TOOLCHAIN, P0-HARNESS | RUNNING (checkpoint, PARTIAL a1) | 1 | wp/P0-TRACK-A @ 855b285 | | paused 2026-10-18. Item-2 veto blocker FIXED (FLUF core + flplusplus restart-file patch clash; profile sets always_regenerate_restart_file=false). Items 1,2,3,8,9,12,13 PASS; 4–7 PARTIAL; 10,11 NOT RUN; LOST_FEATURES: 15 replaced, 24 lost, 7 unknown, 1 conflict. Open: A6 XTEST keys don't reach the game on vdesk lanes; A5 start-up stall on long-lived prefixes. Report a1, resume brief |
| P0-TRACK-B | 0 | spike | P0-TOOLCHAIN, P0-HARNESS | RUNNING (checkpoint, PARTIAL a1) | 1 | wp/P0-TRACK-B @ 1515d38 | | paused 2026-10-18. HDE fully intact, 19 byte-checked patch sites. Items 1,2,3,4,5,8,9,12 PASS (5 self-judged vision); 6,11 PARTIAL; 7,10,13 NOT RUN. Open: real clicks don't reach FL UI buttons. Found the harness selftest menu-load bug (FIX-1). Report a1, resume brief |
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
| FIX-1 | 0 | fix | P0-HARNESS | TODO | 0 | | | harness selftest DLL menu `load` leaves the intro-scene flag set → first launch at system origin (ship dies); EF-007 correction; + small harness proposals from TRACK-A/B (see Next actions 3) |

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
None. Session 2 ended at a planned pause (2026-10-18 ~11:10Z); all agents finished at clean checkpoints, all worktrees removed, all branches committed.

| Agent name/id | Package | Role (impl/review) | Started | Notes |
|---|---|---|---|---|

## Lanes
| Lane | Prefix | Holder | Since |
|---|---|---|---|
