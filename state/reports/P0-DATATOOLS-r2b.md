```
REVIEW: P0-DATATOOLS ROUND 2b (polish check)   VERDICT: PASS
Branch wp/P0-DATATOOLS @ 4d9b317. Evidence: /home/user/freelancer/carrier-mod/local/testruns/20261018T080421Z-review-P0-DATATOOLS-r2b/
Play prefix: probes ran with it bind-mounted read-only; find -newermt = 0; play_prefix_manifest.sh verify = UNCHANGED.

R2 MINORS:
1 deploy lock: fixed.
  - My 5 concurrent interleavings on real HDE copies now run one after the other: both exit 0, undeploy restores a byte-identical tree.
  - A SIGKILLed holder doesn't leave a stale lock: the next deploy goes ahead at once.
  - A stopped holder causes a one-line GenError at the timeout (checked with the constant lowered to 3 s); nothing is written.
  - The lock fd isn't inheritable, and deploy-*.lock names don't clash with lane.sh's lane-*/.acq-* files.
  - So only a live, hung holder can stall a lane deploy, for at most 900 s.
2 kill windows: fixed. SIGKILL at all 103 write points (deploy, redeploy, undeploy) on a real HDE reflink copy: 103/103 recover byte-identically, both by undeploy and by re-running the command then undeploy. ENOSPC injected at the same 103 points: 103/103, and every real failure is one ERROR line.
3 TMPDIR: fixed. A fake prefix sees 0 events. The real prefix (read-only bind) is refused with a one-line error and no write attempt.
4 validator gaps: fixed. My r2 probes FN1/FN2/FN3 are now D002/C001/C002 ERRORs. Two new probes (a nickname appended into a vanilla section, a vanilla nickname commented out) are C002 ERRORs. The fcm_ prefix check is case-insensitive, so FCM_ still passes (a nit, as in r2).
  C002 false positives: none on legitimate patches I tried: set/append on vanilla keys, D-2.1 marketgood field-1 on all [BaseGood], comment_out of zone encounter lines, add_section after a vanilla section, [Room]/[MRoom]/[GF_NPC].
5 empty patch state: fixed. Gen deploy, harness add, gen undeploy, harness unpatch on real HDE leaves a byte-identical tree.
6 path escapes: fixed. All refused: `..`, absolute, backslash, drive-letter and write_data `..` paths at build; patch `..`; tampered manifest, patches.json and both state files; a DATA dir symlinked outside the install (the target dir stays empty). Deploying through a symlinked install root still works and uses the same lock as the real path. Lanes are reflink clones (lane.sh:79), so the new is_within check can't break them.
7 one-line errors: fixed. Corrupt YAML, a non-dict "files" in MANIFEST, and the flworldexport/flresdll refusals each give exactly one stderr line.
8 symlinked patch target: fixed. Refused at plan time: no state file and no DLL copied.
9 copied IDS value: fixed.

Mutation check: I reverted each of the 11 fixes in turn and every one makes its test fail (mutations.txt).

REPRODUCED:
- pytest with data: 138 passed; 2 more flake runs also 138/138.
- pytest without data: 99 passed, 39 skipped, one skip reason.
- No deploy-*.lock files leaked into the shared locks dir.
- Stage 30 through wp/P0-REPO's harness/ci.sh, on an uncommitted merge of DATATOOLS + REPO@04e73d3 + SIDECAR@1f25681 (aborted afterwards): PASS. tests-py 364, sidecar 361, gen-tests absent; public PASS on 210 files.
- check_public --tree: OK on 148 files. --commits: fails only on 463eb68 and 1a99d13 (accepted under D106).
- Play-prefix probes: 152 runs, 0 write attempts.

FINDINGS:
[MINOR] tools/fltools/validate.py:215-218 (provenance) + the _row_is_overlay overlay check — a vanilla-named reference section added by a patch unit flags vanilla findings elsewhere.
  - Repro: a unit adds `[EncounterParameters] nickname = patrolp_gunboats` to Li01 for a new fcm_ zone.
  - That adds "patrolp_gunboats" to _overlay_nicks, so the E006 rows of every vanilla zone using that encounter count as overlay.
  - Result: 3 baselined pairs in unrelated systems (Bw01/Bw09/Bw10) become ERRORs and CI fails.
  - Not a regression: 8eb78e3 gives the identical result. Reusing a vanilla encounter in a vanilla system's new zone is a legitimate pattern.
  - Required: keep reference-type sections ([EncounterParameters], [Room], [MRoom]) out of _overlay_nicks, or only count a zone row as overlay when its zone/file is overlay; add a test.
```

No BLOCKER or MAJOR findings, and every r2 MINOR is fixed. All throwaway copies are deleted and my worktree is clean at 4d9b317.
