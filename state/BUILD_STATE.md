BUILD_STATUS: IN_PROGRESS
<!-- First line is machine-read by tools/watchdog.sh. Values: NOT_STARTED | IN_PROGRESS | COMPLETE | HALTED | STOPPED -->

# Build ledger (orchestrator-owned; update after every state change, commit at least per merge/gate)

- **Current phase:** Phase 0 (not started)
- **Track (G0a):** undecided
- **Base plan (S-BASE / G0b):** undecided
- **Lanes:** not yet created (P0-HARNESS)
- **Last update:** 2026-10-17 (plan authored; build not started)

## Next actions
1. `source tools/env.sh`; confirm the wine guards refuse an unset prefix (`wine --version` must exit 97). Make sure no wine process uses the play prefix (`pgrep -af 'freelancer/prefix/'`), then run `tools/play_prefix_manifest.sh capture` (read-only; proves later that the play install was never touched).
2. Create the shared Python venv: `python3.13 -m venv /home/user/freelancer/carrier-mod/.venv && .venv/bin/pip install pytest pyyaml jsonschema` (CONVENTIONS §1). Create `/home/user/freelancer/carrier-brain-cwd` (empty dir, CONVENTIONS §13).
2b. `tools/display-awake.sh start`; send push notification "Freelancer carrier build started" (fallback: append to `state/NOTIFICATIONS.md`).
3. Set the first line of this file to `BUILD_STATUS: IN_PROGRESS`; commit.
4. Brief and spawn in parallel: P0-REPO, P0-TOOLCHAIN, P0-HARNESS, P0-DATATOOLS, P0-SIDECAR (BUILD_PLAN §5). P0-REPO creates the public GitHub repo and pushes the existing history.
5. When P0-TOOLCHAIN and P0-HARNESS are merged: spawn P0-TRACK-A and P0-TRACK-B in parallel.
6. Run G0a (`docs/plan/packages/G0a.md`), then the S-* spikes in parallel, then G0b, then ARCH-0, then Wave 1.

## Package ledger
Status values: TODO, READY, BRIEFED, RUNNING, REVIEW, FIXING, MERGED, DEGRADED, BLOCKED, SKIPPED.
W4-ESC-* and FIX-* rows are appended when created.

| ID | Wave | Type | Deps | Status | Attempts | Branch @ SHA | Merged | Notes |
|---|---|---|---|---|---|---|---|---|
| P0-REPO | 0 | impl | — | TODO | 0 | | | |
| P0-TOOLCHAIN | 0 | impl | — | TODO | 0 | | | |
| P0-HARNESS | 0 | impl | — | TODO | 0 | | | |
| P0-DATATOOLS | 0 | impl | — | TODO | 0 | | | |
| P0-SIDECAR | 0 | impl | — | TODO | 0 | | | |
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
| Agent name/id | Package | Role (impl/review) | Started | Notes |
|---|---|---|---|---|

## Lanes
| Lane | Prefix | Holder | Since |
|---|---|---|---|
