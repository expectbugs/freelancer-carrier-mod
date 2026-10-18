All four r2 MINORs and the D113 change are fixed on `wp/P0-HARNESS-b` @ **37a268f**, one commit on top of main. Every check you listed passes. `check_public --commits=main..HEAD` is fully clean, so it can merge `--no-ff`.

I held at most one pool lane at a time and hold none now; P0-TRACK-A currently has lane 1. The GPU stayed at `Recovery Action: None`.

**Fix report**

| Item | Change | Test / evidence | Status |
|---|---|---|---|
| r2-1 lock-order inversion | One global lock order: lane → perf → render → input → baseline, written in `harness/README.md` ("Lock order") and `lib/common.sh`. `baseline.sh fluf-init` now takes input.lock **before** baseline-A, which is the same order a `--track A --input` lane uses. Its xinput call no longer takes the lock a second time, so it can't block itself. | `test_lanes.sh` §13 replays your inversion stand-in through a new test-only command, `baseline.sh fluf-init-lock-probe`, in both orders. Probe first: both sides finish, the lane waited 4 s. Lane first: the probe waits, then finishes after the release. No timeout or deadlock either way. | DONE |
| r2-2 stale selftest DLL | The selftest now deletes and rebuilds `devbridge_selftest.dll` on every run (takes seconds). | `selftest.sh --only b_smoke,a_boot`: PASS, with the rebuild in `20261018-093024-selftest/build.log` | DONE |
| r2-3 runner window search | The runner's window lookup, used for the validity check, placement and the window-close target, now also requires the X server's record of who created the window (`xinput.xres_pid`). A faked window pid is no longer enough. | `test_input_gate.sh` has a new check that the runner's search ignores the forged window: 7/7 pass. b_smoke and a_boot in game still find, place and close their windows. | DONE |
| r2-4 test_lanes in parallel / b_gate text | `test_lanes.sh` skips the input-lock checks while input.lock is busy, and the renderer-class checks (§10) while other agents hold lanes. The perf checks already skipped that way. `test_input_gate.sh` skips itself (exit 77) when input.lock is busy. The b_gate BLOCKED text now says it needs the devbridge `target` verb. | `test_lanes` 34/34 | DONE |
| D113 CI stage 30 | `harness/ci.d/30-pytest.sh` now runs `harness/tests` as a fourth test root. A new `test_shell_suites.py` runs the shell suites from pytest, and each one skips with a reason when its needs are missing: Wine for test_guards, `$DISPLAY` for display-awake and input-gate, and a lane budget for the lane tests. Lane suites are opt-in through `HARNESS_LANE_TESTS` or `ci.sh --lanes N`, so a plain or `env -i` run never takes a lane. | `env -i` run of stage 30: PASS, harness 139 passed, 4 skipped (3× "no DISPLAY", 1× lanes opt-in). Second `env -i` run with refs, baseline and clang hidden: 87 passed, 56 skipped, each with its reason. Logs in `p0-harness-evidence/r2-followup/envi-{plain,noresources}`. | DONE |

**Other runs**
- pytest `harness/tests`: 141 passed, 2 skipped (both lane opt-in).
- Devbridge doctest: 26/26.
- `test_guards`: 61/61.
- `harness/ci.sh --full`: PASS (`20261018T093557Z-ci`). The harness root ran 142 passed, 1 skipped: `test_lanes` needs `--lanes 3`, so I ran it directly instead, 34/34.
- `check_public --tree`: 373 files clean.

**Things to know**
- With the default `ci.sh --lanes 1`, CI runs `test_input_gate` (lane 6, outside the 1–4 pool) and briefly takes input.lock, but skips it whenever input.lock is busy. `test_lanes` runs in CI only with `--lanes 3`.
- `test_lanes` itself holds up to three lanes at once (6–8). They're outside the 1–4 pool the track agents use, so their lane slots weren't affected, but it does take more than one lane in total.
- The new section N20 in `harness/NOTES.md` records these changes.
