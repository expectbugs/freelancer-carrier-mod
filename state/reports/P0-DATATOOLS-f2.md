All 9 MINORs from round 2 are closed on `wp/P0-DATATOOLS`. HEAD is **4d9b317**.

Evidence is in `/home/user/freelancer/carrier-mod/local/testruns/20261018T075212Z-p0-datatools-r2polish/` (called `$E` below).

| # | Change | Test | Status |
|---|---|---|---|
| 1 | `deploy` and `undeploy` each take a per-install lock, `$FLMOD_LOCKS/deploy-<sha256(realpath)[:16]>.lock` (waits up to 900 s). | `test_deploy_r2.py`: lock held means both time out with nothing written; two `run.py deploy` processes started against a held lock both wait, then run one after the other, and undeploy gives back the original tree. | DONE |
| 2 | `undeploy` now deletes the deploy state last, after the directories. The manifest copy's temp file and the state `.tmp` files are cleaned as leftovers. | Kill tests on a small synthetic install (not a full HDE copy): stop before each of the 39 (first deploy), 42 (redeploy) and 20 (undeploy) writes. At every point, undeploy restores the original tree, and a rerun matches a clean run. Separate test that the state is the last write. `$E/killpoints.txt` | DONE |
| 3 | The temp overlay dir is chosen from `$TMPDIR`/`$TEMP`/`$TMP` or `/tmp` without tempfile's probe write, and is refused inside a protected prefix. | `TMPDIR` inside a fake prefix: an audit hook records 0 writes there. A normal `TMPDIR` leaves nothing behind. | DONE |
| 4 | Validator: every section a patch unit adds counts as overlay content. C001 newness is judged per namespace. New rule C002 flags a unit that adds, replaces or disables a vanilla `nickname` key. | `test_patch_unit_provenance` covers your three cases. Your probe script, re-run: FN1/2/3 are now ERRORs and the FP probes are unchanged. `$E/vprobes.txt` | DONE |
| 5 | The patch state file is deleted once it records no files. | `test_harness_units.py` now asserts the whole install is byte-identical; the explicit pop is gone. | DONE |
| 6 | New `safety.contained_rel` / `is_within`. Absolute paths and `..` are refused in generator writes, `patch`, manifest entries, state entries and patch targets. A destination that resolves outside the install root is refused. | 5 escape forms at build time; tampered manifest, patches and state at deploy; a symlinked directory pointing outside. | DONE |
| 7 | Corrupt YAML, a `files` entry that is not a dict, and `flresdll` / `flworldexport` play-prefix refusals now each give one `ERROR:` line. | Subprocess tests: exactly one stderr line, no traceback. | DONE |
| 8 | `plan_file` refuses a target that resolves into the play prefix. | A symlinked `EXE/freelancer.ini` is refused with no state file and no DLL copy. | DONE |
| 9 | The copied IDS value is gone from `peres.py` and `test_resources.py`. | `git grep` finds it only in `docs/plan/`, which isn't ours. | DONE |

**Mutation checks:** I reverted each fix in turn (12 cases) and every one made its test fail (`$E/mutations.txt`).

**Results at 4d9b317:**
- **pytest with game data:** 138 passed (`$E/pytest_full.log`).
- **pytest without game data:** 99 passed, 39 skipped, all for the single reason "local HDE install not found" (`$E/pytest_nodata.log`).
- **Flake loop:** 5 of 5 runs at 138/138 (`$E/flake5.txt`).
- **CI stage 30:** PASS (`$E/ci/30-pytest.log`).
- **`check_public --tree`:** OK on 148 files.
- **`check_public --commits`:** fails only on the 3 old decomp markers in 463eb68 and 1a99d13, which D106 accepts.

**One incident:** before I added the test fixture that points `$FLMOD_LOCKS` at a private temp dir, one test run created 44 empty `deploy-*.lock` files in the shared locks dir. All were 0 bytes and created in that run's 34-second window, so I deleted exactly those. After all evidence runs, the shared dir holds only the lane, input and perf locks.

NOTES has an updated resume point with a row per MINOR. Every commit uses the session trailer.
