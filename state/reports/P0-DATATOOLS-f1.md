## Fix report (P0-DATATOOLS, review r1, fix round 1)

Every finding from review r1 is DONE on `wp/P0-DATATOOLS @ 236b530`. No game runs and no wine were used, so there are no GPU notes. Evidence is in `/home/user/freelancer/carrier-mod/local/testruns/20261018T065208Z-p0-datatools-fix1/` (abbreviated `$RUN` below; captured at cdb8e86, with stage 30 and check_public re-run at 236b530).

| # | What changed | Test | Status |
|---|---|---|---|
| M1 | Stage 30 runs one pytest per root (session 1). The verdict line now puts `; ` between root summaries. | `test_ci_stage.py`; `$RUN/ci-head/30-pytest.log` PASS | DONE |
| M2 | `_deploy` checks everything first, now including `patches.json` against the manifest sha. It saves an `in_progress` state listing every file and every directory it will create. The patch state now records a file before it gains regions and drops it only after the file is restored (`_commit_durable`). `undeploy` also removes our exact-name temp leftovers and the empty directories it created. | `test_deploy_txn.py` (14 cases), `test_patch.py::test_commit_saves_state_before_patching_and_after_restoring` | DONE |
| M3 | Guard on every write path (session 1), now tested | `test_safety.py` (every writer against a fake prefix that must stay byte-identical, `..`, symlink, hard-coded prefix with the env var unset or pointing elsewhere, sibling prefixes allowed, run.py, read-only `hde` view) | DONE |
| m1 | Stage log clobbered (fixed with M1) | `test_ci_stage.py` | DONE |
| m2 | IDS subjects are now `<nick>:<key>`; baseline regenerated (same 79 keys); worldexport lane picked by ring nickname; display strings removed from peres, utf, NOTES and WORLD_JSON | `test_baseline_is_exact`, `test_spot_values` | DONE |
| m3 | Overlay D002/H001/E006 become ERROR. New rule C001: new nicknames need `fcm_` (`[Room]`/`[MRoom]` exempt). E006 is flagged overlay even for a baselined vanilla pair. | `test_overlay_warnings_become_errors`, `test_encounter_formation_rules` (both E003 forms), `test_mod_prefix_rule` | DONE |
| m4 | ids_index check at deploy | `test_overlay_ids_index_mismatch_is_refused` | DONE |
| m5 | flock timeout setting (`TEXT_IDS_LOCK_TIMEOUT`) | `test_text_ids_lock_is_taken_and_times_out`, `test_default_text_ids_lock_lives_in_flmod_locks` | DONE |
| m6 | One-line errors from run.py | `test_run_py_reports_corrupt_inputs_in_one_line` | DONE |
| m7 | world.json no longer thrown away (session 1) | — | DONE |
| m8 | Correction for the report: Controls.dll's base is 0x070E0000; our DLL's base is 0x07100000. | — | DONE |
| D106 | Decomp citations moved from `hash.py`, `ini.py` and `test_hash.py` to NOTES §6 | `check_public --tree` OK | DONE |

The M2 and M3 tests were mutation-checked; each mutation made its tests fail:
- removing the `in_progress` state save failed 7 tests;
- going back to write-then-record broke the ordering test;
- removing the `write_dll` guard failed both the refusal check and the prefix-unchanged teardown.

## Standard report

```
PACKAGE: P0-DATATOOLS   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-DATATOOLS @ 236b530
SUMMARY: Review r1 fix round complete. Deploy is now transactional and recovers from interruption.
  Every writer refuses the play prefix, with tests. The validator treats overlay content strictly
  (D002/H001/E006 as ERROR, new C001 fcm_ rule) and has negative tests. Data hygiene and D106
  cleanups done.
FILES: gen/framework/{core.py,README.md,WORLD_JSON.md}, harness/ci.d/30-pytest.sh,
  tools/fltools/{patch,validate,hash,ini,peres,utf}.py, tools/fltools/{baseline_findings.txt,
  README.md,NOTES.md}, tests/py/fltools/{conftest,test_deploy_txn(new),test_safety(new),
  test_validate,test_patch,test_worldexport,test_hash}.py
TESTS:
  pytest tests/py/fltools (with game data) — PASS 115/115 — $RUN/pytest_full.log
  same, no game data — PASS 77, SKIP 38 (each: "local HDE install not found") — $RUN/pytest_nodata.log
  20x flake loop — PASS 20/20 — $RUN/flake20.txt
  flvalidate, stock HDE — ERROR=0 WARNING=0 BASELINE=79 — $RUN/validate_stock.txt
  hashscan — 24,900 nicknames / 0 collisions; 55 factions / 0 — $RUN/hashscan.json
  build + validate example overlay — PASS — $RUN/build.txt, validate_overlay.txt
  deploy/redeploy/undeploy on a full reflink HDE copy — PASS: redeploy identical; undeploy
    leaves files byte-identical and the directory set identical — $RUN/deploy.txt
  CI stage 30 at HEAD — PASS — $RUN/ci-head/30-pytest.log
  check_public --tree at HEAD — PASS (146 files) — $RUN/check_public_tree_head.txt
  check_public --commits=main..HEAD — FAIL (3 decomp markers, all in intermediate commits
    463eb68 / 1a99d13; acceptable per D106) — $RUN/check_public_commits_head.txt
  play prefix — 0 files newer than the run start — $RUN/play_prefix_newer.txt
DECISIONS:
  1. Patch state is saved before a file gains marker regions, and a record is dropped only after
     the file is restored, so the saved state always covers the disk.
  2. Deploy state has a "dirs" list; undeploy removes those directories if empty, plus our
     exact-name *.carrier-mod.tmp / *.json.tmp leftovers.
  3. Deploy refuses a patches.json that doesn't match the manifest sha256.
  4. C001 checks nicknames in overlay files and in sections added by patch units. "New" means
     not defined anywhere in the pristine install. [Room]/[MRoom] are exempt.
  5. E006/E003 count as overlay when the zone, encounter or file belongs to the overlay. E006
     reports one finding per (system, faction) and prefers an overlay row.
  6. Validator finding subjects never contain values from game files.
  7. flvalidate exits 2 when an output path is inside the play prefix.
ENGINE FACTS LEARNED: none (no game runs).
OPEN QUESTIONS / BLOCKERS:
  - ARCH-0: should text_ids.json be committed (your earlier answer: yes, under data/strings/ by W1-DATA)?
  - Marker clash with P0-HARNESS (proposal, not implemented): harness lib/deploy.py should write
    its dacom.ini block as an fltools.patch unit on the shared state:
    patch_file(root, "EXE/dacom.ini", [{"id": "harness.dacom", "version": 1,
      "ops": [{"op": "append", "section": "Libraries", "lines": libs}]}])
    Catch (from reading patch.py, not tested): plan_overlay_patches makes the install carry
    exactly gen's units, so the next gen deploy would strip a harness unit. Fix: about 10 lines
    in fltools.patch so overlay planning keeps "harness.*" units. Needs your go-ahead.
KNOWN ISSUES:
  - Resource DLL loading in game is still DEFERRED(P0-HARNESS); the faction hash is UNVERIFIED in game.
  - undeploy keeps a directory it created if someone else's files are in it (by design).
  - W1-DATA REQ-9 (`--prefix`, `uninstall`, gen/build.py) still conflicts with this CLI and CONVENTIONS (from the review).
```

Every claim above is VERIFIED by the listed evidence except where marked UNVERIFIED or "from reading patch.py". Nothing was written to `$FLMOD_LOCAL/gen` or `$FLMOD_LOCKS` (checked), and there are no background processes or prefixes left. NOTES.md has an up-to-date RESUME POINT and the design notes for this round (§7).
