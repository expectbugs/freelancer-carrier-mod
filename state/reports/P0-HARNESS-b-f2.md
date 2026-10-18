`wp/P0-HARNESS-b` @ **602224c**: both MINORs are fixed and every check you listed passes; check_public is clean on `--tree` and `--commits=main..HEAD` (2 commits), so it's ready for the `--no-ff` merge.

- **MINOR 1, lock contention:** when one of their acquires loses to a lock another agent holds (input.lock, a `wined3d-sw` lane, the perf gate), `test_lanes.sh` now records SKIP instead of FAIL. `test_input_gate.sh` exits 77, which pytest reports as skipped. Both suites also skip up front if input.lock is busy or a `wined3d-sw` lane is running elsewhere. The shared logic is in the new `harness/tests/lib_contention.sh`.
- **Self-test:** new `test_lanes` §14 uses fake holders on test lanes 6–7, each holding a lock for 6 s. An input acquire lost to a held input.lock and a default acquire lost to a held `render-sw.lock` both came out SKIP; a failure with no contention behind it still comes out FAIL.
- **MINOR 2, test_guards:** the success case now picks only test lanes 6–8 or `prefix-dev-base-B`, never pool lanes 1–4. It ran on `prefix-lane-6`: 61/61.
- **Results** (TRACK-A on lane 1 and TRACK-B on lane 2 throughout): `pytest harness/tests` 141 passed, 2 skipped (lane opt-in). `test_lanes` 30/30, with the perf and renderer-class checks skipped because of those foreign lanes. `test_input_gate` 7/7. Evidence is in `p0-harness-evidence/r2-followup/`.
- **Lanes:** I never acquired a pool lane. I held input.lock for 6 s at most and hold no lanes now.

Orchestrator verification (2026-10-18): pytest harness/tests on 602224c → 141 passed, 2 skipped.
