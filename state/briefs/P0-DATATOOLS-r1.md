# Review brief: P0-DATATOOLS fltools (INI, hashes, resource DLLs, UTF/CMP, validation, patches, world export) (round 1)

You are an independent reviewer in an autonomous build. Be adversarial: your job is to find what is wrong, missing, untested or risky before it reaches `main`.

**You do not fix code.** You report findings; the author fixes them.

## Inputs

- **Package spec:** `docs/plan/packages/P0-DATATOOLS.md`
- **Brief:** `state/briefs/P0-DATATOOLS.md`
- **Author's report:** pasted below (also `state/reports/P0-DATATOOLS-a1.md`).
- **Branch:** `wp/P0-DATATOOLS` @ `1a99d13`. Review with `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-DATATOOLS`. To build or run, check it out in your own worktree.
- **Standards:**
  - `CLAUDE.md` guardrails
  - `docs/plan/DESIGN.md`
  - `docs/plan/TESTING.md`
  - `state/ENGINE_FACTS.md`
  - research pitfalls: `local/research/R4-lore-and-testloop.md` §A1, and `R2` §0 item 15

## Do all of these

1. **Requirements.** For every `REQ-P0-DATATOOLS-n`, find the code and the test that cover it. Mark each one covered, partial or missing.
2. **Tests.** Re-run the host tests and at least the package's primary in-game scenario yourself, on your own lane. Compare with the author's evidence. Flag any claim you can't reproduce.
3. **Engine-safety audit:**
   - main-thread-only game calls;
   - deferral of spawn, destroy and relocate inside callbacks;
   - validated spawns;
   - `st6` at the Common.dll boundary;
   - no blocking I/O on the game thread;
   - save/load and SP⇄MP lifecycle resets;
   - null and dead-object checks after every engine lookup.
4. **Contract conformance.** It doesn't modify frozen contracts. Events are used as specified.
5. **Data hygiene and public safety.** Run `tools/check_public.py`. No game files or extracts are committed. Nicknames are unique (hash scan).
6. **Design fidelity.** Does the behavior match DESIGN.md's words, especially "never forced", "earned danger" and "no artificial restrictions"?
7. **Failure paths:**
   - sidecar absent;
   - corrupt or missing JSON;
   - pre-mod saves;
   - player dies mid-operation;
   - F1 pause;
   - alt-tab.

## Verdict (your last message)

```
REVIEW: P0-DATATOOLS ROUND 1   VERDICT: PASS | CHANGES_REQUIRED
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the primary scenario reproduced.

## Orchestrator notes for this review

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use `$FLMOD_VENV/bin/python -I` for Python.
- The branch is checked out in the author's worktree, so inspect it detached in yours: `git fetch` is not needed (same repo); run `git checkout --detach wp/P0-DATATOOLS` (or `git worktree add --detach <tmpdir> wp/P0-DATATOOLS`).
- Run the public-safety checker on the branch's commits: `python3 -I tools/check_public.py --commits=main..wp/P0-DATATOOLS` (from a checkout that has it) and `--tree` on the branch checkout.
- You never edit the branch, `main`, `state/` or the main checkout. Write any scratch output under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-DATATOOLS-r1/`.
- Game runs only through the harness on a locked lane, if the harness exists on the branch or main; otherwise state that in REPRODUCED.
- Package-specific: the harness is not merged yet, so no in-game run is possible. **Do this substitute loader check instead.**
  1. With P0-TOOLCHAIN's toolchain, build a tiny i686 console probe that does `LoadLibraryExW(fcm_text.dll, LOAD_LIBRARY_AS_DATAFILE)` and also a plain `LoadLibraryW`, then `LoadStringW` for both IDS. Its sources are in `$XWIN_ROOT` and `$FLMOD_VENDOR`; read `git show wp/P0-TOOLCHAIN:toolchain/README.md` and build in a temp dir outside the repo.
  2. Do the same for the infocard resource (`FindResource`/`LoadResource` of the HTML/XML resource type FL uses).
  3. Run the probe under Wine in your own throwaway clone `prefix-dev-review-datatools`. Pipe its stdout, because Wine drops console stdout redirected to a file. Kill only that prefix's wineserver and delete the clone after.
  4. Also check the generated DLL against HDE's own resource DLLs with `llvm-readobj --file-headers --sections`.
  5. Mark the in-game load itself `DEFERRED(P0-HARNESS)`.
- Verify data hygiene hard. Nothing derived from game files may be committed, including test fixtures, goldens, `baseline_findings.txt` and any HDE-derived strings in tests or docs.
  - `baseline_findings.txt` lists stock-HDE findings: judge whether it embeds game data (nicknames are references; values copied from files are not allowed, CONVENTIONS §12).
  - Run P0-REPO's latest checker from its branch (`git show wp/P0-REPO:tools/check_public.py > /tmp/...`, run it with `-I`) with `--tree` and `--commits=main..wp/P0-DATATOOLS`.
- Re-run the full pytest suite with and without game data. Hide the data with an env var or by pointing the install path at an empty dir, if the code supports that; never move or rename the real install.
- Test deploy/undeploy idempotency and the refusal to touch the play prefix: try `--install` pointing into `/home/user/freelancer/prefix` and confirm it refuses before reading or writing anything there.

## Author's report

```
PACKAGE: P0-DATATOOLS   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-DATATOOLS @ 1a99d13
SUMMARY: Every REQ (1 to 11) is implemented with tests. fltools is stdlib-only and covers:
INI read/write (lossless), BINI decoder, hashes, PE resource reader, resource-DLL builder
(pure Python by default, llvm optional), UTF read/write with hardpoint add, install+overlay view,
validator plus baseline, hashscan, patch framework, geometry/route exposure and world.json export.
Also: gen/run.py (build/deploy/undeploy/validate/list), gen/framework (plugins, strings
registry -> text_ids.json, MANIFEST), gen/example_strings, and CI stage 30.
FILES: tools/fltools/* (modules, bin/fl*, README.md, NOTES.md, baseline_findings.txt),
gen/run.py, gen/framework/{core,strings,__init__}.py + README.md + WORLD_JSON.md,
gen/example_strings/generator.py, tests/py/fltools/*, harness/ci.d/30-pytest.sh. Nothing outside owned paths.
TESTS (evidence: local/testruns/20261018T051201Z-p0-datatools/):
- pytest tests/py/fltools: 86 passed — PASS — pytest.log. Flake check 20/20 green — flake20.txt.
  Without game data: 52 passed, 34 skipped with reasons.
- INI round-trip of all 1,254 HDE DATA INIs (copied to tmp): 100% byte-identical — PASS
- CreateID: 5 goldens plus every locked_gate hash/name pair in newplayer.fl — PASS
- resdll: 2 strings + 1 infocard read back; llvm-readobj shows I386 + IMAGE_FILE_DLL; llvm backend gives identical resources — PASS — fcm_text_readobj.txt
- UTF: byte-exact round-trip of rh_battleship/li_dreadnought/or_osiris (found via shiparch);
  +2 hardpoints re-read correctly — PASS. Extra scan: all 3,284 UTF files round-trip, and
  hardpoint add works on all 2,022 cmp/3db models.
- Validator, stock HDE: ERROR=0 WARNING=0 BASELINE=79 — PASS — validate_hde.txt.
  Broken overlay reports L001, N002, B005, I001 and D001, plus encounter rules E001/E002 — PASS
- Hashscan: 0 collisions, 55 factions, 24,900 nicknames (explained below); forced
  CreateID and faction collisions in an overlay are both reported — PASS
- worldexport: 53 systems, 232 links, 124 lanes, 3,801 zones, 6,608 rows, all equal to R3's
  JSON at test time. Hi02_to_Ew06_hole and the Fort Bush lane spot checks pass. Route exposure
  matches R3's reference script — PASS. Golden written to local/golden/route_exposure/route_exposure.json
- gen/run.py example build twice: identical MANIFEST sha256 (e5822f83…) — PASS.
  Deploy, redeploy and undeploy on a temp install come back byte-identical — PASS
- CI stage 30: PASS/FAIL/SKIP exit codes tested — PASS — ci_stage30.txt
- check_public: P0-REPO's checker, taken from its branch, passes on --tree . and on --commits main..HEAD — PASS
DECISIONS:
1. The resource DLL is fcm_text.dll, built in pure Python. Its header copies HDE's
   Controls.dll: chars 0x210E, entry 0, base 0x07100000, timestamp 0.
2. The llvm backend passes `/C 65001`. llvm-rc 22 ignores the R4 pragma for non-ASCII text.
3. Validator: stock-HDE findings live in a baseline file and count as BASELINE. Overlay
   content never matches the baseline.
   - Raw stock HDE without the baseline: 11 ERROR-class findings (intro/story bases with no
     MBase or no dock solar) and 68 warnings.
   - E006 (patrol faction needs a [BaseFaction]) is a WARNING heuristic.
4. [Data] additions go right after the last line of the same key (`after_key`), so load
   order holds (solar before universe).
5. Text ids: provisional rules until text_ids.md exists. Ids are persistent and never reused;
   YAML keys are allocated first, in sorted order. The example generator is on by default and
   gives IDS 524289/524290.
6. No on-disk INI cache. Parsing all 1,254 INIs takes about 0.8 s.
7. deploy/undeploy refuse any path inside the play prefix. Builds read a "pristine" view of
   the install (marker regions stripped, our deployed files hidden).
8. world.json goes to <overlay>/world.json and is not copied into the game. W1-WORLD picks
   its runtime location.
ENGINE FACTS LEARNED (host-side only, no game runs):
- VERIFIED: the HDE nickname count is 24,900. R4's 24,877 came from a regex that stopped at
  blanks (26 names with spaces merged into 3) — NOTES.md §1, test_hashscan.
- VERIFIED: every one of 19,704 loadout hardpoint references resolves on its model (104 models).
- VERIFIED: vanilla often points ids_info at a string resource (466 cases; INFO I004).
OPEN QUESTIONS / BLOCKERS: none blocking.
- `python -I -m fltools.x` cannot work because -I ignores PYTHONPATH. Use the bin/ wrappers
  or gen/run.py; the spec wording should be amended.
- .gitignore lacks .pytest_cache; the CI stage passes `-p no:cacheprovider` to avoid it.
KNOWN ISSUES (UNVERIFIED in game):
- DLL loading in-game (needs a lane test; IDS 524289 is the probe).
- Added hardpoints in-game (S-LOADOUT's job).
- Faction-hash golden: no game-produced value exists anywhere to check against.
- UTF growth on non-standard layouts (some .ale/.sph/.utf files) falls back to the compact writer.
- R3's "exclusion 5000" for Gammu was not reproduced; its source is unknown.
```

