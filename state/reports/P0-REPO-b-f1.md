The follow-up is done and committed on `wp/P0-REPO-b` @ `2358ae4`, branched from main `3404144`; `wp/P0-REPO` was not touched. All four r3 items are fixed per D112. `--commits=main..HEAD` is fully clean, so the branch is ready for the `--no-ff` merge. Evidence is in `$FLMOD_TESTRUNS/20261018T083220Z-p0-repo-b/` (E below).

**Fix report**

| # | Change | Test | Evidence | Status |
|---|---|---|---|---|
| 1 Marker form | The marker now counts only as a whole comment line (`#`, `//`, `;`, `--`, `<!-- -->`, `/* */`) in the first 5 lines, or as a sibling file `<file>.authored-data` holding the reason. `.json` files take only the sibling form, and the `_check_public` JSON key no longer works. Prose mentions, YAML string values and markers buried in one-line JSON never count. | `test_r5_authored_data_*`: every comment form; A14 (one-line JSON, old key form, a `//` line in .json); A15 (prose); A16 (two string-value cases); outside the allowed dirs; reason required; line 6 too late | E/pytest-py313.log | DONE |
| 2 Protection under the marker | Lines outside comments that hold a game-asset file reference (`.cmp .3db .mat .txm .ale .utf .wav .thn …`) or a backslash path stay R5 violations. The rejection message says the marker is only for our own values. The checker prints `check_public: AUTHORED-DATA <path> (<marker>)` for each escaped file. ci.sh adds the count to the public stage line and lists each file in a summary.md section. Archive members can never use the marker. | `..._keeps_asset_paths_as_violations`, `..._never_rescues_r1_r2_r4_or_r7` (now includes a zip), `test_ci_public_stage_lists_every_authored_data_escape` | E/marker-attack.txt | DONE |
| 3 Image metadata | Vetted PNG and JPEG files are parsed. Metadata gets every text rule (plus base64 and R5): PNG tEXt, zTXt/iCCP (decompressed, capped), iTXt, any other non-pixel chunk, bytes after IEND; JPEG COM and APP0–15 (EXIF, XMP, ICC, IPTC), bytes after EOI. Pixel data keeps the reduced rule set. An image that doesn't parse is rejected as malformed. Hits are reported as `<image>!<chunk>`. | `test_r1_vetted_docs_image_metadata_gets_every_text_rule` | E/image-noise.txt | DONE |
| 4 Dict-literal recall (optional) | In `.py` files, lists of literal values and string-encoded vector lines (`'1, 2',`) now count; plain numeric array rows still don't. Recall went from 92.5% to 94.2%. The remaining misses need the "many sections, any keys" rule, which code can't use without flagging patch-op dicts. | dict-literal cases in the compact/flow test; numeric-row and enum-list negatives in `test_r5_own_code_with_fl_names_passes` | E/r5-recall-and-negatives.txt | DONE (94.2%, short of 95%) |

**What the r3 attack looks like now:** with the marker present, real HDE data converted and committed under `data/` is still rejected 70.1% of the time as YAML with a comment marker and 68.4% as compact JSON with a sibling file. In r3 the same attack got 0% rejected. The files that still pass carry FL key names but no asset paths.

**Verification (all VERIFIED with logs in E):**
- **Tests:** pytest 243 passed on Python 3.13.15 and on 3.11.16 (fresh venv from `requirements-dev.txt`).
- **Recall:** text forms unchanged at 98.8% / 96.5%; minified R3-data extracts 15 of 15 rejected.
- **False positives:**
  - R5 flags 0 of 1204 text files. The set is main @6bb6ef7, DATATOOLS @496fa64, HARNESS @e666b6d, SIDECAR @1f25681, TOOLCHAIN @5825345 and this worktree.
  - The full checker passes all five trees.
  - Random-pixel images with ordinary metadata: 0 of 300 PNG and 0 of 300 JPEG flagged when vetted. The same bytes under every rule flag 3 and 8.
- **Mutations:** 19 of 19 caught (`mutate4.txt`).
- **Tree checks:** `--tree` passes on the branch (161 files) and on the main checkout (312 files), using the live blocklist, which now has 1 `w:` entry.
- **History:** `--commits=main..HEAD` is clean (1 commit).
- **CI:** `ci.sh --quick` passes.

**Decisions:**
1. The asset-path rule skips comment lines, so a comment such as "meshes come from vanilla x.cmp" stays legal.
2. The asset extension list leaves out `.ini` and `.dll`, because our own data may name our own generated INI files.
3. A vetted image that doesn't parse is now rejected outright.

**Known issue:** nothing stops someone from writing converted game data that has no asset paths and adding the marker. Reviewers have to check every listed escape; that check is what CONVENTIONS §12 now requires.
