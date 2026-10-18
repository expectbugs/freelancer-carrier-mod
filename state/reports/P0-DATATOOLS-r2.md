```
REVIEW: P0-DATATOOLS ROUND 2   VERDICT: PASS
Branch wp/P0-DATATOOLS @ 8eb78e3. Evidence: /home/user/freelancer/carrier-mod/local/testruns/20261018T071418Z-review-P0-DATATOOLS-r2/ ($RUN)
Method notes:
- strace and inotify aren't installed. For SIGKILL and errno injection I used a Python audit hook that fires before every filesystem write call (killrun.py in my scratchpad).
- Play-prefix probes ran in `unshare -rm`, with /home/user/freelancer/prefix bind-mounted read-only as a safety net.
- Afterwards: `find -newermt` on the play prefix gives 0 files, and play_prefix_manifest.sh verify says UNCHANGED.

R1 FINDINGS:
- M1 (CI stage 30): fixed. 30-pytest.sh:31-54 runs one pytest per root. The test fails when run against 1a99d13's stage script. Real harness/ci.sh on an uncommitted octopus merge of DATATOOLS+REPO+SIDECAR (since aborted): PASS. tests-py 303 passed, sidecar 306 passed with 0 ImportError, public PASS (ci-merged/20261018T073830Z-ci/).
- M2 (transactional deploy): fixed. Deploy runs all checks before writing, saves an in_progress intent first, and commits patches durably. Mutations break test_deploy_txn. SIGKILL at all 106 write points recovers byte-identically at 100 of them, and so does ENOSPC injection; the other 6 leave residue (MINOR 2). Real EACCES (read-only EXE dir or root) and real ENOSPC (tmpfs) both recover byte-identically.
- M3 (play-prefix guard): fixed. 38 probes × 4 FLMOD_PLAY_PREFIX states (set, unset, elsewhere, empty) = 152 runs. Probes used direct paths, `..`, a symlink, a symlinked parent, a relative path from a cwd inside the prefix, dosdevices/c:, mixed symlinked EXE/DATA/file installs, crafted states, and every bin/ writer. All were refused with 0 write attempts in the prefix. The one exception is TMPDIR (MINOR 3).
- m1 (stage log clobbered): fixed. Per-root logs go to $CI_RUNDIR/30-pytest/<root>.log; ci.sh's 30-pytest.log holds only the verdict line.
- m2 (data hygiene): fixed. I002 subjects are now `<nick>:<key>`, the r1 display strings are gone from branch files (git grep), and the lane is picked by ring nickname. One nit remains (MINOR 9).
- m3 (validator severities): partially fixed. D002/H001/E006 overlay findings become ERROR, the new C001 rule exists, and the negative tests fail under mutation. Patch-unit gaps remain (MINOR 4).
- m4 (ids_index check): fixed. The test fails when the check is removed.
- m5 (text_ids lock): fixed. flock with a timeout; the test fails without the lock.
- m6 (one-line errors): fixed for the inputs r1 listed (tested). New traceback paths are in MINOR 7.
- m7 (world.json): fixed. deploy defaults to world=False (core.py:375).
- m8 (report text): fixed in the f1 report.
- D106: tip tree clean. --commits fails only on 463eb68 and 1a99d13.

COVERAGE:
- REQ-P0-DATATOOLS-1: covered. 82 passed, 38 skipped without data, all for one reason ("local HDE install not found").
- REQ-2: covered.
- REQ-3: covered. The faction-hash golden stays UNVERIFIED, as the spec allows.
- REQ-4: covered.
- REQ-5: covered. The built DLL is byte-identical to the one r1 loaded under Wine (sha 41b60eb2…), so no new Wine run was needed. The in-game load stays DEFERRED(P0-HARNESS).
- REQ-6: covered.
- REQ-7: covered, with the false-negative gaps in MINOR 4.
- REQ-8: covered.
- REQ-9: covered, including D107.
- REQ-10: covered.
- REQ-11: covered, with MINORs 1, 2, 3, 5 and 6. There is still no on-disk INI cache (decision 6, accepted at r1).

REPRODUCED:
- pytest tests/py/fltools with data: reproduced. 120 passed, plus 3 flake runs at 120/120 (repro/pytest_full.log, flake{1,2,3}.log).
- Same without data (FLMOD_HDE/RESEARCH/GOLDEN/LOCAL pointed at an empty dir): reproduced. 82 passed, 38 skipped, single skip reason (repro/pytest_nodata.log).
- CI stage 30 through real ci.sh on the merged tree: reproduced, PASS (ci-merged/).
- check_public snapshot: reproduced. --tree OK on 147 files; --commits shows 3 violations, only in the D106-accepted commits (repro/check_public_*.txt). No tracked game-data file extensions.
- D107 on real HDE copies, both orders, both with an overlay patching dacom [Libraries] and with the example overlay: reproduced. Redeploy is byte-exact, the harness unit survives undeploy, the namespace is refused (uppercase id, a generator named "Harness", a tampered overlay). The API is one documented call each way (patch_file / unpatch_file, README §Reserved unit namespace). Deviation in MINOR 5 (d107.txt).
- Validator FP probes (own fcm_ content, [Room] via patch, keys added to vanilla sections, [MRoom]/[GF_NPC], vanilla [EncounterParameters] in a new system): 0 false positives (vprobes.txt).
- Mutation spot checks: 11 of 12 reverted fixes make tests fail. The run.py catch-all is redundant because core already wraps the errors (mutations.txt).

FINDINGS (ordered by severity):
[MINOR] gen/framework/core.py:365-505 — deploy and undeploy take no per-install lock. Two concurrent deploys onto one install: in 2 of 5 interleavings both exit 0 but leave an unrecorded overlay file plus an unrecorded region in market_ships.ini. Undeploy then exits 0 with the tree not pristine, and the next deploy fails "exists in the install and is not ours" (concurrent.txt). The lane lock and the harness's baseline refresh limit the real-world impact. — Required: flock $FLMOD_LOCKS/deploy-<hash(realpath)>.lock around deploy and undeploy; add a test.
[MINOR] core.py:483-500, 458 — two narrow windows leave residue (6 of 106 kill or ENOSPC points). (a) undeploy deletes carrier-mod.deploy.json before removing the directories it lists; a kill in between orphans the created dirs permanently (undeploy k=20-23). (b) leftovers miss carrier-mod.manifest.json.carrier-mod.tmp, so a kill at that rename leaves it after undeploy (killmatrix_*.txt). — Required: remove the dirs before deleting the deploy state (delete the state last); add MANIFEST_COPY+TMP_SUFFIX to leftovers; add tests.
[MINOR] core.py:379 — with TMPDIR inside a protected prefix, tempfile's probe file and mkdtemp/rmtree write inside it before build refuses (tmpdir_probe.txt, fake prefix). — Required: refuse when the temp dir resolves into a protected root, or use mkdtemp(dir=<safe>); add a test.
[MINOR] tools/fltools/validate.py:205-221, 916-957 — patch-unit false negatives:
  - add_section duplicating a vanilla nickname in the same vanilla file → D002 WARNING with ov=False, exit 0;
  - [Engine] named after a vanilla ship → no finding (C001's "new" is global across namespaces);
  - a `set nickname` rename of a vanilla good → no finding.
  — Required: mark every section a patch unit adds as overlay (by region provenance, not by the nickname being absent); judge C001 newness per namespace; flag ops on vanilla `nickname` keys; add tests.
[MINOR] tools/fltools/patch.py:559-583, README.md:133-139 — after gen undeploy and then the harness unpatch, an empty carrier-mod.patchstate.json stays in the install root, so the install is not byte-identical. This happens in every gen-undeploy-then-harness-unpatch run (6), and test_harness_units.py:82 pops the file explicitly. — Required: delete the state file once it records no files (own state), or document that the harness must.
[MINOR] core.py:57-58, 134-147, 338-350 — `..` in overlay paths isn't contained. ctx.write_file('EXE/../../x') lands outside files/ at build and outside the install root at deploy (escape.txt). — Required: reject absolute paths and `..` components; check the destination stays under root.
[MINOR] gen/framework/strings.py:119, core.py:403, worldexport.py/resdll.py main() — remaining tracebacks:
  - a corrupt strings*.yaml gives a 51-line traceback from run.py build;
  - a MANIFEST whose "files" is not a dict raises AttributeError;
  - flworldexport/flresdll print 17-20-line tracebacks when they refuse the play prefix (no write happens).
  — Required: turn these into one-line errors.
[MINOR] patch.py:497-510 — plan_file doesn't resolve the target. If EXE/freelancer.ini is a symlink into the play prefix, the refusal comes only at commit time, after the in_progress state and the DLL copy (no write in the play prefix; undeploy recovers). — Required: call refuse_play_prefix(path) in plan_file.
[MINOR] tools/fltools/peres.py:9, tests/py/fltools/test_resources.py:72 — the IDS value 196609 copied from universe.ini is still in committed code and comments. — Required: drop the number.
```

All throwaway installs, mount namespaces and temp trees are deleted, and my worktree is clean at 8eb78e3 (the CI merge was aborted). Nothing was committed and no Wine ran.
