**REVIEW: P0-REPO ROUND 2 — VERDICT: CHANGES_REQUIRED**

There are two MAJOR findings. First, the bulk-game-text rule (R5) blocks honest data that uses our own FL-named schemas. Second, it still misses compact JSON and flow-style YAML, the most common machine output, so F1 is only partly fixed. Everything else in the fix round holds up, and every test reproduced. I made no commits and did not push, and I deleted the temp sample repos.

Evidence: `E=/home/user/freelancer/carrier-mod/local/testruns/20261018T064356Z-review-P0-REPO-r2/`

```
REVIEW: P0-REPO ROUND 2   VERDICT: CHANGES_REQUIRED
R1 FINDINGS:
F1: partially fixed — r1 S01–S08 now blocked by --staged, --tree and --commits (E/r1-rerun/synthetic-smuggle.txt). The ≥95% HDE corpus test runs and passes. R3-data extracts as-is: 16/16 blocked with the index. But compact JSON and flow-style YAML pass (FINDING 2).
F2: fixed — S09, S14–S21, S27 blocked. The r1 harness reports S18/S19 under --tree as "MISSED", but that is a matcher artifact: the violation is reported as x.gz!x. A direct probe blocks both in all 3 modes (E/probes.txt P01/P02). HDE binaries renamed .bin: 1355/1419 blocked; the 64 that pass are text-format .thn/.sur (E/png-fp-and-v2.txt).
F3: fixed — S11–S13 blocked. Decomp code copied into src/: 96.7% blocked with the index, 91.3% without (the decomp marker rule catches 1279/1279 files that carry the header). A residual gap is FINDING 4.
F4: fixed — r1 hookspath_sim: with the absolute hooksPath, a clean commit in a pre-merge sibling worktree gives rc=0 and the check runs. test_hooks_with_absolute_hookspath… passes. The live config is absolute (D101).
F5: fixed — a symlinked .dll and a symlinked dir in --release are both rejected [R1-symlink], rc=1 (E/r1-rerun/release-symlink.txt).
F6: fixed — any [Section] header counts. Tested with [BaseGood], [MRoom] and others.
F7: fixed — --staged run from docs/ sees a root foo.cmp (rc=1). --tree on local/research exits 2 ("ignored by git").
F8: fixed — S23, S24, S28–S31 blocked.
F9: orchestrator-owned, not judged against the package. Note: blocklist entry #18 (6 chars) is a substring of 11 ordinary words and corpus tokens, so it will cause false positives (E/blocklist-fp.txt).
F10: fixed — other mods' code in src/: 797/932 blocked with the index; only 10/932 without it.
F11: fixed — test passes and CONVENTIONS §5 is amended. TESTING §CI still says "ignores .claude/" (orchestrator).
F12: fixed — tag-message and pre-push tests pass. Release notes are left to W5-SHIP.
F13: fixed — decompression is capped at 5 MB + 1; a 40 MB gzip bomb is rejected.

COVERAGE:
REQ-P0-REPO-1: covered — PUBLIC, isEmpty=true, description and 6 topics (E/gh-repo-view.json).
REQ-P0-REPO-2: covered — LICENSE is not in the fix-round diff, so the r1 verification stands.
REQ-P0-REPO-3: covered — the README change is one line; the tree scan is clean.
REQ-P0-REPO-4: partial — all modes and rules work and are tested, but R5 has false positives (FINDING 1) and misses (FINDING 2).
REQ-P0-REPO-5: covered — the hooks work with the absolute hooksPath, including in sibling worktrees branched before the merge.
REQ-P0-REPO-6: covered — --commits=main (22 commits) passes the commit-identity rule (R6).
REQ-P0-REPO-7: covered — --quick, default, --only public and --only on absent canonical stages (SKIP) all behave as specified; summary.md is under $FLMOD_TESTRUNS.
REQ-P0-REPO-8: covered locally — the workflow YAML parses (3.11/3.13 matrix). The real Actions run is UNVERIFIED.
REQ-P0-REPO-9: covered (verify only) — main's .gitignore now has build/ and out/ unanchored.

REPRODUCED:
pytest on Python 3.13.15 — reproduced — 183 passed, 0 skipped, 27 s (E/pytest-313.log).
pytest on Python 3.11.16 (fresh venv) — reproduced — 183 passed (E/pytest-311.log).
--tree on the branch checkout — reproduced — OK, 109 files, 0.34 s.
--tree on the main checkout (read-only, main @ e65c93d) — reproduced — OK, 124 files, 0.32 s.
--commits=main..wp/P0-REPO — reproduced — fails only on 95db516 and 257ef54 (decomp marker in tools/check_public.py:148). The tip alone is OK (109 files); --commits=main is OK.
ci.sh --quick / --only public / default — reproduced — exit 0, summary.md written (E/ci-*.log).
Performance — reproduced — --staged on a 48-file commit with the index takes 0.34 s; nowhere near 10 s.
Sibling tips with this checker — reproduced — TOOLCHAIN, SIDECAR and DATATOOLS (current tip) are clean. HARNESS a5bafe5 still fails the decomp rule in flhash.py and gen_fixture.py; moving those citations out of code is HARNESS's D106 item.
Actions approximation — reproduced (UNVERIFIED on GitHub) — run under env -i with no $FLMOD_LOCAL, refs, HDE or venv, and a fresh 3.11 venv with only pytest, on P0-REPO plus DATATOOLS 236b530: check_public --tree OK, 155 files; pytest tests/py: 255 passed, 43 skipped (E/actions-sim.txt).

FINDINGS (ordered by severity):
1. [MAJOR] tools/check_public.py:166-204, 611-680, 648-660 — R5 rejects honest authored content, with no escape and a wrong message ("Never paste game data").
   Each case below is synthetic and committed into a temp repo; each was blocked by --staged and --tree (E/step2.txt, E/world-variants.txt, E/probes.txt):
   - A synthetic world.json test fixture in our own fcm.world.v1 schema (gen/framework/WORLD_JSON.md), which uses ids_name, ids_info and dock_with: 3 systems × 6 objects is blocked ("42 lines"); about 7 objects is enough to block.
   - NPC definitions using the field names W1-DATA REQ-7 itself uses (ship_archetype, state_graph, npc_class): 7 or more entries are blocked.
   - Carrier YAML with hit_pts, hold_size, nanobot_limit and shield_battery_limit: 5 or more entries are blocked.
   - The table rule treats generic columns as FL columns: a TSV with system, faction and level columns and 20 or more rows is blocked. This contradicts "generic keys are weak evidence".
   D102 assumed our own YAML would avoid these keys, but ARCH-0.md and CONVENTIONS §12 never say so, and our own world.json schema uses them.
   Required change:
   - Add a reviewable escape, for example a "check_public: authored-data <reason>" header that turns R5 into a warning under data/, tests/, harness/ and docs/spec/. It must never override R1, R4 or R7.
   - Count only distinctive columns in the table rule.
   - Add tests: a world.json fixture with 12 or more objects and an NPC-definition YAML with 10 or more entries pass with the header and fail without it.
   - Orchestrator: state the key-naming rule in CONVENTIONS §12 and the ARCH-0 brief.
2. [MAJOR] tools/check_public.py:616 (lines over 4000 characters are skipped), 209-210, 630-637 — F1 is only partly fixed.
   - Compact JSON (Python's default json.dumps output): 209 of 345 real HDE INI files with 50+ key lines pass after conversion, with or without the index; R7 cannot help because a one-line file has no shingles. All 15 minified R3-data extracts pass even with the index (E/r1-rerun/realistic2-summary.txt V5m, V9m).
   - Flow-style YAML (`- {ids_name: 1, hit_pts: 2}`) is never matched.
   - Python dict literals and repr dumps pass (P05–P07).
   Required change: scan long lines in bounded chunks, match flow-style YAML pairs, apply the quoted-key matcher to code files, and add corpus tests for compact JSON and flow YAML (≥95%) and for the minified R3-data extracts.
3. [MINOR] tools/check_public.py:121-124, 1081-1087 — R4-email false positives.
   - An SSH clone URL `git@github.com:…` in docs is rejected (P11).
   - Legitimate high-entropy PNGs under docs/ trigger it from random bytes: 1 of 300 images (about 0.3% per image).
   Required change: allow SSH clone URLs of the form `git@<host>:`. For vetted docs images, apply only the blocklist and the real-secret-shape checks to binary content.
4. [MINOR] tools/check_public.py:159, 1193 — the decomp-marker exemption for .md/.txt applies anywhere, not only under docs/. Decomp code renamed `src/**/x.cpp.txt` passes that rule: 0.8% blocked without the index, 96.7% with it (V6t). Required change: limit the exemption to docs/ and NOTES*/README* files.
5. [MINOR] tools/check_public.py:653 — the table rule only reads line 1, so a CSV with a leading comment line passes; HTML tables pass too (P16, P17). Required change: find the header within the first few lines.
6. [MINOR] tools/check_public.py:241, 244, 507 — a text file starting with "Bink", "MSCF" or "8BPS" is flagged as binary content. Required change: require a NUL byte or extra header bytes for these signatures.
7. [MINOR] harness/ci.d/NOTES-P0-REPO.md — the file is outside the owned paths (the spec owns only harness/ci.d/README.md), sits in the shared drop-in directory, and is already stale: it says the DATATOOLS tip fails the decomp rule, but it now passes. Required change: move it to an owned directory (.github/ or .githooks/) and refresh it.
8. [MINOR] (spec-literal, orchestrator) tools/check_public.py:129-133 — any identifier containing `api_key` fails as a credential marker, e.g. `test_no_api_key_in_env` (P12). Tell the sidecar and brain authors, or narrow the rule to assignment form.
```

**Design check:**
- **S05 (authored INI with ≤20 sections in an allowed folder):** acceptable by design. It matches the spec's literal rule. Locally, the reference index catches 1057 of 1263 verbatim HDE INI files placed there. GitHub Actions has no index, so there only 219 of 1263 are caught. 206 small real files (rooms, mission scripts) pass even locally.
- **S32 (placeholder email):** correct. The spec explicitly allows example.com and example.org placeholders.

**GitHub CI:**
- **Assumptions:** the workflow assumes:
  - no blocklist and no index on Actions, so the local hooks are the real gate;
  - requirements-dev.txt, which no branch has yet;
  - only `tests/py` runs; sidecar/tests, harness/tests and toolchain/tests never run on Actions.
- **What siblings must do:** skip, not fail, when any of these are missing:
  - the HDE install, research, refs, the venv, llvm, wine, or a display;
  - PyYAML or jsonschema (use `importorskip`).

  They must also keep requirements-dev.txt pure Python. DATATOOLS already does all of this.
- **UNVERIFIED:** the workflow pins actions/checkout@v4 and setup-python@v5. These may need bumping once GitHub retires their Node 20 runtime.
