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
