# P0-DATATOOLS working notes (attempt 1)

Investigations of surprises during the build, per the ten-explanations rule: hypotheses first,
then the experiment that separated them, then the result.

## 1. Nickname count: 24,900 found vs R4's 24,877

Observation: the hash scan found 24,900 unique nicknames; R4 §A1.3 says 24,877 (both on HDE DATA).

Hypotheses:
1. R4 counted a different file set (DATA only vs DATA + EXE).
2. R4 skipped some file extensions or case variants of `.ini`.
3. R4's regex stopped at blanks, so nicknames containing spaces were truncated and merged.
4. Our parser reads nicknames inside disabled `[;Section]` blocks.
5. Our parser misses comment handling (`;` inside values).
6. Lower-casing differs (str.lower vs ASCII-only) so some names merge differently.
7. Different handling of commas (R4 regex stops at `,`).
8. Duplicate files (`*_vanilla` copies) counted by one method only.
9. The install changed between R4's scan and now.
10. Nicknames in the preamble (before the first section) counted by the regex only.
11. Non-latin-1 bytes decoded differently.

Experiment: compute both counts in one process on the same files and diff the sets.
Result: R4's regex method gives exactly 24,877 here (so 1, 2, 8, 9 are out); the set difference is
26 nicknames containing spaces (e.g. `Br03_Com Sat_1`) on our side versus their 3 truncated forms
on R4's side: 24,877 - 3 + 26 = 24,900. Hypothesis 3 confirmed. The engine reads the parameter up
to `;` and trims only the ends (decomp `parsers.md`), so 24,900 is the engine's view (source: §6).
`HashScan.legacy_regex_count` keeps R4's number; `test_stock_hde` checks the arithmetic.

## 2. Forced CreateID collision search found nothing in 2M names

Observation: a birthday search over `fcm_hc_<hex counter>` names found no collision within
2^21 tries, while a 30-bit hash should collide after ~2^15.

Hypotheses:
1. CreateID is linear (CRC-like): names that differ only in a short suffix map to distinct hashes.
2. The search loop compared lower-cased vs original names incorrectly.
3. The hash has more than 30 effective bits.
4. Python dict keyed on the hash silently overwrote entries.
5. The counter formatting produced duplicate names (same name -> "collision" filtered).
6. The table generation is wrong, making the hash injective on short inputs.
7. The `0x80000000` bit makes all hashes share a prefix but that cannot reduce collisions.
8. Name length is constant, and CRCs of equal-length messages differing in < 32 bits never collide.
9. The assertion bound was mis-computed.
10. Random variation (unlikely at 2^21 vs 2^15).

Experiment: switch to seeded random 10-letter suffixes (differences spread over all bytes).
Result: with seed 1234 the first CreateID collision appears after 6,212 names (faction id: 203
names), in line with a ~30-bit / 16-bit birthday bound; the goldens still pass, so 3 and 6 are out.
Hypotheses 1/8 (linearity on structured inputs) explain the first run. The test now uses seeded
random names.

## 3. `llvm-rc` rejected non-ASCII strings

Observation: R4's recipe (`#pragma code_page(65001)`) failed with "Non-ASCII 8-bit codepoint can't
be interpreted in the current codepage" for a string with `Ü`.

Hypotheses: 1. llvm-rc ignores the pragma unless preprocessing runs; 2. the pragma must precede
`LANGUAGE`; 3. the file needs a BOM; 4. llvm-rc wants `L"..."` wide literals; 5. `/l 0x409` resets
the codepage; 6. the `.rc` was written in the wrong encoding; 7. llvm-rc only supports 1252/65001 via
`/C`; 8. the clang preprocessor is not found; 9. the string needs escapes; 10. a bug in llvm-rc 22.

Experiment: same file with `/C 65001`. Result: compiles, strings read back correctly. R4's test only
used ASCII strings, so the recipe was never exercised with non-ASCII. The llvm backend now passes
`/C 65001` (pragma kept). The default backend is pure Python and is unaffected.

## 4. UTF preserve-layout writer failed on 1,030 of 3,284 files at first

Observation: the first writer round-tripped every `.cmp` but not some `.ale/.sph/.utf/.3db/.mat`.

Hypotheses: 1. blocks not contiguous (tree not at offset 56); 2. unreachable tree entries;
3. shared data between leaves; 4. compressed leaves; 5. name block holes; 6. data block padding
after EOF; 7. different entry size; 8. peer links pointing backwards; 9. non-zero header unknowns;
10. intermediate nodes with non-zero size fields; 11. trailing bytes after the data block.

Experiment: classify every failing file by header layout and reachability.
Result: two classes only: tree after a gap (`.ale` tree at 96, voice `.utf` at ~1-8 KB; 1) and
`.3db` files with unreachable garbage entries (2). The writer now keeps the original bytes and
rewrites entries/leaves in place when nothing grows, and only falls back to the compact layout
when growth is needed on a non-standard layout. All 3,284 files now round-trip; the ship models
(our editing target) use the standard layout.

## 5. Validator false positives on stock HDE (first run)

Observation: B005 "no dock solar" for planet bases (e.g. `Ew06_02_Base`), A001 for shiparch
`separation_explosion`, N010 for faction_prop `space_costume`.

Hypotheses (B005): 1. planets are docked through `dock_with` rings; 2. base objects use a
different key; 3. solar archetypes of planets lack `docking_sphere`; 4. the base is attached via
`missioncreatedsolars.ini`; 5. object-to-base matching is case-sensitive; 6. objects in another
system; 7. universe base nickname differs from the object's; 8. bases spawned by story missions;
9. intro-scene bases are never dockable; 10. our object parser skipped sections.
Experiment: dump that base's planet object, its ring, and their archetypes. Result: 1 (dock ring with
`dock_with = <base>`) for planets; 4/8/9 for the 7 remaining bases, which are baselined.
A001: shiparch `separation_explosion` names an `[Explosion]`, not a `[Sound]` (equipment uses
sounds there) -> accept either. N010: `space_costume` lists body parts, not costume nicknames ->
checked against bodyparts. After the fixes stock HDE has 79 findings, all baselined
(`baseline_findings.txt`).

## 6. Reference-source citations (moved out of the code per D106)

Code files cite this section instead of naming the reference sources directly.

- `fltools.ini` grammar: the retail `INI_Reader` text mode as documented in
  `$FLMOD_REFS/Freelancer-Decomp/docs/ini/parsers.md` (line terminators, blanks = space/tab only,
  key up to `=`/`;`, params up to `;`, `[;Name]` disabled sections). VERIFIED independently by the
  byte-exact round trip of all 1,254 HDE DATA INIs.
- `fltools.hash.create_id`: Librelancer `FLHash.cs`, corroborated by the Freelancer-Decomp
  reconstruction of `CFLIDMaker` (Common.dll `CreateID`). VERIFIED against game-written hashes in
  `newplayer.fl` / `Restart.fl`.
- `fltools.hash.faction_id`: Librelancer `FLFacHash` and the Freelancer-Decomp `MakeId`
  (`common_id.cpp`, cited by review r1 at line 409). UNVERIFIED against a game-produced value.
- `fltools.hashscan` counting note: the engine reads a parameter up to `;` and trims only the ends
  (Freelancer-Decomp `docs/ini/parsers.md`), see §1.

## 7. Fix round 1 design notes (review r1)

- **Deploy durability.** Two crash windows existed: files copied before any state was written,
  and a patched file written before its patch-state record was saved. Now: (1) `_deploy` runs
  every check and plans every unit in memory first; (2) it saves an `in_progress` deploy state
  listing every file and every directory it will create, then copies; (3) `patch.commit_plans`
  saves a file's record *before* writing a file that gains regions and drops it *after* writing
  a restored file (`_commit_durable`). A record whose write never happened is harmless (strip
  finds no regions; the pristine sha256 still matches). `undeploy` also removes our
  `*.carrier-mod.tmp` / `*.json.tmp` leftovers (exact names only) and empty directories the
  state says we created.
- **Validator severities.** `Validator.add(..., overlay=...)`: a finding is overlay when its
  file is an overlay file, its subject (or the part before `:`) is an overlay nickname, or the
  caller says so. Overlay D002/H001/E006 are upgraded to ERROR. E006 groups zone rows per
  (system, faction) and prefers an overlay row, so an overlay zone in a pair stock HDE already
  has (baselined) is still reported, as ERROR. The E003 faction/class finding is overlay when
  the zone or encounter is. C001 (`fcm_` prefix): candidates are nicknames in overlay files and
  in sections patch units add, minus `[Room]`/`[MRoom]`; "new" = not defined anywhere in the
  pristine install (computed only if some candidate lacks the prefix).
- **D107 merge order.** `_merge_preserved(old, new)` anchors every preserved unit after the
  last overlay unit that preceded it in the old list and still exists in the new one (else
  first). Unchanged overlay -> same list -> byte-exact file. If gen re-orders its own units, two
  harness units anchored to different gen units could swap; harness uses one unit per file, so
  this is accepted and documented.
- **Data hygiene.** IDS finding subjects are `<nickname>:<key>` (the value is in the message,
  never in the baseline). The worldexport spot test selects the lane by ring nickname.

## RESUME POINT (fix round 1 of review r1, session 2, 2026-10-18)

Review: `state/reports/P0-DATATOOLS-r1.md`. Every finding is addressed; see the table. Tests
that need no game data use the synthetic install in `conftest.py` (`synth_install`), so they
also run on GitHub Actions.

| # | Finding | Status / test |
|---|---|---|
| M1 | CI stage 30 one process per root | DONE (session 1): `harness/ci.d/30-pytest.sh`, `test_ci_stage.py` |
| M2 | Transactional deploy | DONE: `gen/framework/core.py` `_deploy`/`undeploy`, `fltools/patch.py` `_commit_durable`; `test_deploy_txn.py` (failing unit, corrupt patch/deploy state via build and via overlay, tampered overlay, copy failing at file 1/2/3, redeploy over a half deploy, patch write failing at file 1/2, temp leftovers), `test_patch.py::test_commit_saves_state_before_patching_and_after_restoring` |
| M3 | Play-prefix guard on every write path | DONE: `fltools/safety.py`; `test_safety.py` (every writer against a fake prefix that must stay byte-identical; `..` and symlink; hard-coded prefix with the env unset or elsewhere; siblings allowed; run.py one-line refusals; the `hde` view is read-only and outside the prefix) |
| m1 | Stage log clobbered | DONE with M1 |
| m2 | Data hygiene | DONE: subjects, baseline (same 79 keys), worldexport lane by nickname, display strings out of peres/utf/NOTES/WORLD_JSON |
| m3 | Validator severities | DONE: `validate.py` (`OVERLAY_ERRORS`, `check_prefix`); `test_validate.py` (`test_overlay_warnings_become_errors`, `test_encounter_formation_rules`, `test_mod_prefix_rule`) |
| m4 | deploy `--overlay` ids_index | DONE: `test_deploy_txn.py::test_overlay_ids_index_mismatch_is_refused` |
| m5 | text_ids.json flock | DONE: `core.TEXT_IDS_LOCK_TIMEOUT`; `test_text_ids_lock_is_taken_and_times_out`, `test_default_text_ids_lock_lives_in_flmod_locks` |
| m6 | run.py tracebacks | DONE: `test_run_py_reports_corrupt_inputs_in_one_line` |
| m7 | world.json thrown away | DONE (session 1) |
| m8 | Report accuracy | Report text: Controls.dll's base is 0x070E0000; our DLL's is 0x07100000 |
| D106 | Decomp citations in code | DONE: moved to §6; `check_public --tree` clean |
| D107 | Reserved `harness.*` unit namespace (orchestrator-approved marker-clash fix) | DONE: `patch.PRESERVED_PREFIXES`, `is_preserved`, `_merge_preserved` in `plan_overlay_patches`; gen refuses `harness.*` ids; `undeploy` keeps the patch state while harness units remain; README section; `test_harness_units.py` (mutation-checked: disabling the merge fails 3 tests, deleting the state on undeploy fails 2) |

### Review r2 (PASS) polish round: all 9 MINORs closed

Review: `state/reports/P0-DATATOOLS-r2.md`. Mutation check of every fix: 12/12 caught
(`$FLMOD_TESTRUNS/20261018T075212Z-p0-datatools-r2polish/mutations.txt`).

| # | Change | Test |
|---|---|---|
| 1 | `core.deploy_lock_path` / `_deploy_lock` around deploy and undeploy | `test_deploy_r2.py::test_deploy_and_undeploy_wait_for_the_install_lock`, `::test_concurrent_deploys_serialise` |
| 2 | undeploy deletes the deploy state last; MANIFEST_COPY tmp and state `.tmp` files are leftovers | `test_kill_matrix_{first_deploy,redeploy,undeploy}` (39 + 42 + 20 write points; audit hook stops before each), `test_undeploy_deletes_the_state_last` |
| 3 | `_temp_base()`: no tempfile probe, refused in a protected prefix | `test_temp_overlay_never_touches_a_protected_tmpdir` (audit hook: 0 writes in the fake prefix) |
| 4 | validator: provenance by region, C001 per namespace, new C002 | `test_validate.py::test_patch_unit_provenance` |
| 5 | `PatchState.save_or_remove` (own state, commit_plans, CLI) | `test_harness_units.py` (whole install byte-identical), `test_patch.py` |
| 6 | `safety.contained_rel` / `is_within`; Context, manifest, state, patch targets | `test_build_refuses_escaping_paths` (5 forms), `test_deploy_refuses_escaping_overlay_and_state`, `test_deploy_refuses_a_directory_symlinked_outside` |
| 7 | YAML errors -> StringsError; manifest `files` shape; flresdll/flworldexport mains | `test_more_one_line_errors`, `test_cli_play_prefix_refusals_are_one_line` |
| 8 | `plan_file` refuses the resolved target | `test_symlinked_patch_target_is_refused_before_any_write` |
| 9 | IDS number removed from peres.py / test_resources.py | `git grep` for it finds only `docs/plan/` (not ours) |

**r2b MINOR (polish check PASS, `state/reports/P0-DATATOOLS-r2b.md`):** a unit declaring a
vanilla encounter for a new `fcm_` zone made E006 rows of unrelated vanilla zones overlay
ERRORs. Fixed twice over: `REFERENCE_SECTIONS` ([EncounterParameters], [Room], [MRoom],
[BaseInfo]) added by units don't put their nickname in `_overlay_nicks`, and `_row_is_overlay`
ignores the encounter nickname (zone, system file or encounter file only). Test:
`test_validate.py::test_vanilla_encounter_reused_in_a_new_zone_flags_nothing_else` (0
ERROR/WARNING; each half asserted alone; 3/3 mutations caught,
`$FLMOD_TESTRUNS/20261018T081455Z-p0-datatools-r2b/mutations.txt`). Real overlay E006 stays an
ERROR (`test_overlay_warnings_become_errors`).

Tests now run with a private `$FLMOD_LOCKS` (autouse session fixture in conftest). An earlier
run of this round created 44 empty `deploy-*.lock` files in the shared `$FLMOD_LOCKS`; they were
mine (0 bytes, created in that run's 34 s window) and were deleted.

Next steps: none in code. If resumed: re-run pytest with and without data, a 5x flake loop,
CI stage 30, check_public `--tree` / `--commits=main..HEAD` into a new
`$FLMOD_TESTRUNS/<stamp>-p0-datatools-*/`.

Outside the repo (created by this package): `$FLMOD_GOLDEN/route_exposure/route_exposure.json`;
run dirs under `$FLMOD_TESTRUNS/*-p0-datatools*`. Nothing in `$FLMOD_LOCAL/gen/`, no lock file
in `$FLMOD_LOCKS`, no wine prefixes, lanes or background processes.
