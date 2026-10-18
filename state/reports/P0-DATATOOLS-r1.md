```
REVIEW: P0-DATATOOLS ROUND 1   VERDICT: CHANGES_REQUIRED
Evidence dir: /home/user/freelancer/carrier-mod/local/testruns/20261018T052439Z-review-P0-DATATOOLS-r1/

COVERAGE:
REQ-P0-DATATOOLS-1: covered. fltools imports only stdlib (VERIFIED). Tests skip with a reason when there is no game data. The spec's "-I -m fltools.x" form can't work (a spec wording problem); the bin/ wrappers work under -I (VERIFIED). One hygiene nit, see MINOR 2.
REQ-P0-DATATOOLS-2: covered. ini.py, test_ini (all 1,254 DATA INIs; find gives 1254 too).
REQ-P0-DATATOOLS-3: covered. hash.py, test_hash. Goldens plus newplayer.fl pairs pass. MakeId matches decomp common_id.cpp:409. The faction golden stays UNVERIFIED, as the spec allows.
REQ-P0-DATATOOLS-4: covered. peres.py, test_resources (R3 name parity, the 196609 case).
REQ-P0-DATATOOLS-5: covered. resdll.py, test_resources, Wine loader probe. The in-game load is DEFERRED(P0-HARNESS).
REQ-P0-DATATOOLS-6: covered. utf.py, test_utf (3 capital models, plus 2 added hardpoints).
REQ-P0-DATATOOLS-7: partial.
  - Overlay content that only warns still exits 0: D002 duplicates, H001 missing hardpoints and the E006 BaseFaction rule.
  - E003 and E006 have no negative test.
REQ-P0-DATATOOLS-8: covered. hashscan.py, test_hashscan. 24,900 is explained in NOTES §1.
REQ-P0-DATATOOLS-9: covered. patch.py, test_patch, including real HDE files for every target file the spec lists.
REQ-P0-DATATOOLS-10: covered. worldexport.py, geometry.py, test_worldexport (R3 parity), WORLD_JSON.md. The golden is in $FLMOD_GOLDEN/route_exposure/.
REQ-P0-DATATOOLS-11: partial.
  - deploy is not transactional (MAJOR 2).
  - Only deploy/undeploy guard the play prefix (MAJOR 3).
  - There is no on-disk INI cache (recorded as decision 6).
  - CI stage 30 breaks after merge (MAJOR 1).

REPRODUCED:
- pytest tests/py/fltools with game data: reproduced. 86 passed (pytest_full.log), plus 3 more runs at 86/86 (flake3.txt).
- pytest without game data (FLMOD_HDE, RESEARCH, GOLDEN and LOCAL pointed at an empty dir): reproduced. 52 passed, 34 skipped, each with a reason (pytest_nodata.log).
- Validator plus hashscan on stock HDE (deployed copy): reproduced.
  - ERROR=0, WARNING=0, BASELINE=79, INFO=475.
  - 24,900 nicknames with 0 CreateID collisions; 55 factions with 0 faction-hash collisions (deploy_exp.json).
- Extra UTF claim: reproduced. 3,284/3,284 files round-trip byte-identical; hardpoint add re-reads on 2,022/2,022 models (utf_scan.txt).
- Deploy, redeploy, undeploy on a full reflink copy of HDE: reproduced.
  - deploy adds EXE/fcm_text.dll plus 3 state files and patches freelancer.ini.
  - redeploy changes nothing.
  - undeploy gives a file and directory set byte-identical to the original (deploy_exp.json).
- Play-prefix refusal: reproduced.
  - Tried deploy, undeploy, a "/../" path and a symlink to the play HDE. All exit 1 before touching anything: a Python audit hook recorded 0 open/listdir/write events under /home/user/freelancer/prefix.
  - `find /home/user/freelancer/prefix -newermt <review start>` finds 0 files (checked again at the end).
- check_public (P0-REPO's checker at 257ef54): reproduced. `--tree` OK on 143 files; `--commits main..wp/P0-DATATOOLS` OK on 7 commits.
- Substitute loader check, standing in for the primary scenario: reproduced, VERIFIED on Wine in throwaway clone prefix-dev-review-datatools (now deleted). Files in loaderprobe/.
  - LoadStringW(1) returns "Carrier Mod Test String" with both LoadLibraryExW(AS_DATAFILE) and plain LoadLibraryW.
  - FindResourceW(2, RT_HTML) returns 336 bytes starting FF FE, decoding to `<RDL>…</RDL>`. Missing ids fail correctly (gle 1814).
  - Loaded alongside Controls.dll: two distinct bases (0x070E0000 and 0x07100000).
  - With 0x07100000 reserved, it relocates and still serves both resources. That is Wine only; real Windows is UNVERIFIED.
  - llvm-readobj against HDE's resource DLLs: same machine, magic, characteristics 0x210E, OS/subsystem 4.0 and entry point 0. No loader-relevant mismatch.
  - The in-game load is DEFERRED(P0-HARNESS).
- CI stage 30 run standalone in the branch: reproduced PASS. Under ci.sh-style redirection it clobbers its own log (MINOR 1). On a tree merged with wp/P0-SIDECAR it FAILs (MAJOR 1).

FINDINGS (ordered by severity):

[MAJOR] harness/ci.d/30-pytest.sh:14,33
  Problem:
  - The stage runs one pytest process over "tests/py sidecar/tests gen/tests".
  - On a tree of this branch + wp/P0-REPO tests/py + wp/P0-SIDECAR sidecar/, collection fails with 8 ImportErrors. sidecar/tests do `from conftest import SCRIPTS_DIR, run, …`, and that resolves to tests/py/fltools/conftest.py, which was imported first under the module name `conftest`.
  - The stage FAILs, and ci.sh stops at the first FAIL, so every later stage reads NOT RUN on the first CI after the P0 merges.
  - In a combined run, sidecar's own pyproject pytest config (pythonpath, testpaths) is also ignored.
  - Evidence: merged/cirun/30-pytest.log. Each root passes collection on its own.
  Required change:
  - Run one pytest process per existing root, with cwd at that root's project (e.g. `cd sidecar && pytest tests`), and aggregate the verdict.
  - Add a test with two roots whose conftests both export names.
  - Orchestrator note: P0-SIDECAR's `from conftest import` pattern is fragile too.

[MAJOR] gen/framework/core.py:267-308 (deploy)
  Problem:
  - Files are copied (line 295) before patch units are applied (line 305) and before the deploy state is written (line 308).
  - Reproduced twice: a failing unit (PatchError) and a corrupt carrier-mod.patchstate.json (raw JSONDecodeError traceback). Both times EXE/fcm_text.dll was left in the install and recorded nowhere.
  - After that, every `deploy` fails, with or without --force: "EXE/fcm_text.dll exists in the install; patch it instead". `undeploy` removes 0 files, so the lane stays broken until someone deletes the file by hand (deploy_exp.json failA_*).
  - harness/deploy.sh runs this on every lane, and nobody will clean up by hand during an autonomous build.
  Required change:
  - Before writing anything: check every patch unit in memory (strip + apply_units + baseline checks), load all state, and check that MANIFEST and patches are present.
  - Record each copied file in the deploy state as it is written, so undeploy and --force can always recover.
  - Turn JSON and IO errors into GenError.
  - Add a test for failure mid-deploy.

[MAJOR] tools/fltools/patch.py:435,468,503 (also gen/framework/core.py:180-220 build, resdll.write_dll, utf.dump, worldexport.write)
  Problem:
  - The play-prefix refusal exists only in core.deploy/undeploy, and it is keyed on $FLMOD_PLAY_PREFIX alone. Setting that variable removes protection for the real path.
  - `fltools.patch` (patch_file, unpatch_file, apply_overlay_patches, and the `flpatch apply --root` CLI) writes into any root with no check.
  - `gen/run.py build --out/--text-ids` wrote an overlay and text_ids.json inside a fake play prefix (VERIFIED with FLMOD_PLAY_PREFIX pointed at a fake dir; the real prefix was never targeted).
  - The test fixtures default `hde` to the real play install, so one wrong argument in a future test (e.g. `patch.patch_file(hde, …)`) would modify Adam's install and halt the build (guardrail 1).
  Required change:
  - Add one fltools helper that refuses paths inside the play prefix, checking the hard-coded /home/user/freelancer/prefix as well as the env value.
  - Call it from every write path: patch file writes and PatchState.save, build out_dir and text_ids, write_dll, UtfFile.dump, worldexport.write, and the --json / --write-baseline outputs.
  - Add tests against a fake prefix.

[MINOR] harness/ci.d/30-pytest.sh:31
  Problem:
  - The stage writes its pytest log to $CI_RUNDIR/30-pytest.log. That is the same file ci.sh truncates and sends the stage's stdout to (wp/P0-REPO ci.sh:211,238).
  - The verdict line overwrites the pytest output, so the PASS log ends up as "CI pytest: PASS (…)\nin 33.42s" and the -rs skip reasons are lost (ci_emulate.txt).
  - The protocol says artifacts go in $CI_RUNDIR/<NN>-<name>/.
  Required change: write to $CI_RUNDIR/30-pytest/pytest.log.

[MINOR] Data hygiene (CONVENTIONS §12)
  Problem:
  - tools/fltools/baseline_findings.txt:91-94: the I002 subjects embed IDS values copied from game files (strid_desc=11551, strid_name=11051, tradelane_space_name=5621/5611).
  - HDE display strings appear in committed files: tests/py/fltools/test_worldexport.py:53-54 ("Fort Bush", "Colorado Jump Gate"), peres.py:9 ("New York"), NOTES.md:85 ("Planet Gammu") and WORLD_JSON.md:46 ("Border Worlds"). docs/plan already contains the first three.
  - Counts and nicknames used as references are fine.
  Required change:
  - Drop "=value" from finding subjects.
  - Select the lane by ring nickname taken from R3's JSON.
  - Replace the display strings in docs with placeholders.

[MINOR] tools/fltools/validate.py:275,432,775
  Problem:
  - An overlay that redefines an HDE nickname with the same case (D002) and an overlay loadout that names a missing hardpoint (H001) are both WARNING only, so the validator exits 0 (VERIFIED, validate_exp.json).
  - Stock HDE has no H001 findings, so making these errors costs nothing on vanilla.
  - The E006 BaseFaction rule (R4 §0.1 #3) can never fail CI.
  - There is no check that overlay nicknames start with `fcm_` (CONVENTIONS §2).
  Required change:
  - Make D002, H001 and E006 errors when the finding involves overlay files or nicknames.
  - Add the `fcm_` prefix rule.
  - Add negative tests for E003 (missing formation) and E006.

[MINOR] gen/framework/core.py:267-280 (deploy with --overlay)
  Problem:
  - There is no check that the target's [Resources] index equals MANIFEST.ids_index.
  - An overlay built on one install and deployed onto an install with an extra DLL gets its IDS shifted by 65536 with no error.
  Required change: call detect_resource_index(target, RESOURCE_DLL, expected=man["ids_index"]) before copying.

[MINOR] gen/framework/strings.py:47,160
  Problem:
  - The read-modify-write of the shared $FLMOD_LOCAL/gen/text_ids.json has no lock, and every worktree and lane shares that file.
  - Ids therefore depend on every branch's build history on this machine.
  - The "never reused" rule can't hold for end users, because the map is gitignored.
  Required change:
  - Wrap the read-modify-write in flock $FLMOD_LOCKS/text_ids.lock.
  - Raise the question for ARCH-0 / text_ids.md: commit the map (it is our own data)?

[MINOR] gen/run.py:84
  Problem: only GenError, PatchError and ResourceIndexError are caught. Corrupt text_ids, patchstate or MANIFEST JSON, or a bad --install path, end in Python tracebacks (rc 1).
  Required change: report them as one-line ERROR messages.

[MINOR] gen/framework/core.py:277
  Problem: deploy builds world.json in its temp overlay and then deletes it. That costs a few seconds per deploy, and the file is unavailable afterwards.
  Required change: pass world=False, or write it to $FLMOD_LOCAL/gen/world.json.

[MINOR] Report accuracy
  Problem: Decision 1 says the header copies Controls.dll, "base 0x07100000". Controls.dll's base is actually 0x070E0000; resdll.py:37 is correct.
  Required change: fix the report text.

NOTES (for the orchestrator, not author defects):
- Engine-safety audit: N/A. No game-side code here, and the DLL is resource-only with entry 0.
- Failure paths: sidecar, saves, death, F1 and alt-tab are N/A. Corrupt or missing JSON is covered under MAJOR 2 and the gen/run.py:84 MINOR.
- Design fidelity: D-2.1's "set field 1 = 0 on every marketgood" shape is supported and tested on real market files. Data is additive (write_file refuses existing files; HDE files are only touched inside marker blocks).
- Two marker systems share the "carrier-mod" namespace:
  - P0-HARNESS deploy.py writes `; >>> carrier-mod` with no id into dacom.ini.
  - This branch's regexes don't match it (no clash today).
  - But if a W1 plugin later patches dacom.ini through fltools.patch, the harness rewriting its own block will trip the baseline check on redeploy.
- W1-DATA REQ-9 names `--prefix`, `uninstall` and a gen/build.py alias, which conflicts with this CLI and with CONVENTIONS.
```
