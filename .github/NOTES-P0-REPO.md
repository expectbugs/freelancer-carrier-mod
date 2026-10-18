# P0-REPO notes

Package P0-REPO owns `.github/` (this file, the workflow), `tools/check_public.py`, `.githooks/`,
`harness/ci.sh`, `harness/ci.d/README.md`, `README.md` (until W5-SHIP), `tests/py/test_check_public.py` and
`requirements-dev.txt` (shared, append-only). This file moved here from `harness/ci.d/` in fix round 2 (review r2
finding 7: that directory holds CI drop-ins, and the spec owns only its README).

## RESUME POINT (follow-up `wp/P0-REPO-b`, review r3 MINORs + D112, 2026-10-18): complete

P0-REPO r3 passed and was squash-merged (`eb051ed`). `wp/P0-REPO-b` (from main `3404144`, merged `--no-ff`) fixes
the four r3 MINORs (`state/reports/P0-REPO-r3.md`) per D112 and CONVENTIONS §12. Evidence:
`$FLMOD_TESTRUNS/20261018T083220Z-p0-repo-b/` (scripts in `scripts/`). `wp/P0-REPO` is closed; never touch it.

| r3 # | What changed | Tests |
|---|---|---|
| 1 marker anywhere | The marker is a whole comment line (`#`, `//`, `;`, `--`, `<!-- -->`, `/* */`) in the first 5 lines, or a sibling file `<file>.authored-data` whose first non-blank line is the reason. `.json` takes only the sibling form. The `_check_public` JSON key is gone. Prose mentions, string values and markers buried in one-line JSON never count (r3 A14–A16). | `test_r5_authored_data_*` (sibling, comment forms, A14–A16, outside dirs, reason) |
| 2 no protection under the marker | Under the marker, non-comment lines holding a game asset file reference (`.cmp .3db .mat .txm .ale .utf .wav .thn .sph .sur .vms .dfm .bini .mp3 .ogg .wma .wmv .bik`) or a backslash path stay R5 violations. The checker prints `check_public: AUTHORED-DATA <path> (<marker>)` per escaped file; `ci.sh` adds the count to the public stage line and lists the files in `summary.md` ("Authored-data escapes"). Messages say the marker is only for our own values. Archive members never use it. | `test_r5_authored_data_marker_keeps_asset_paths_as_violations`, `..._never_rescues_r1_r2_r4_or_r7`, `test_ci_public_stage_lists_every_authored_data_escape` |
| 3 image metadata | Vetted PNG/JPEG are parsed. Metadata gets every text rule (plus base64 and R5): PNG tEXt, zTXt and iCCP (inflated, bounded), iTXt, every other non-pixel chunk, bytes after IEND; JPEG COM and APP0–15 (EXIF, XMP, ICC, IPTC), bytes after EOI. Pixel chunks/segments keep the reduced set. An image that does not parse is rejected (R1-image "malformed"). Violations show as `<image>!<chunk>`. | `test_r1_vetted_docs_image_metadata_gets_every_text_rule`, `..._pixels_get_...` |
| 4 dict-literal recall (optional) | In code, list values of literal scalars count, and string-encoded vector lines (`'1, 2',`) count as FL-shaped; plain numeric array rows still do not. | compact/dict-literal test, `test_r5_own_code_with_fl_names_passes` |

Review `P0-REPO-b-r1` (PASS, two MINORs), fixed on the same branch: (1) decompressed image metadata is capped at
5 MB per image in total (the reviewer's 80 x 5 MB zTXt PNG is rejected as malformed in about 0.5 s; it took 490 s
before); (2) under the marker, asset file names starting `fcm_` (our own generated assets, CONVENTIONS §2) are not
game-asset references; vanilla names and backslash paths still are. Tests:
`test_r1_vetted_image_metadata_inflation_is_capped_per_image`, `test_r5_authored_data_marker_allows_our_own_fcm_asset_names`.

Measurements (`20261018T083220Z-p0-repo-b/`): R5 recall unchanged for text forms (98.8% / 96.5%); `.py` dict
literals 92.5% → 94.2%; minified R3-data 15/15. R5 false positives 0 of 1204 text files (main @6bb6ef7,
DATATOOLS @496fa64, HARNESS @e666b6d, SIDECAR @1f25681, TOOLCHAIN @5825345, this worktree); the full checker
passes all five trees. Real HDE data converted and committed under `data/` WITH the marker: 70.1% (YAML + comment)
and 68.4% (compact JSON + sibling) still rejected, against 0% in r3. Random-pixel PNG/JPEG with ordinary
metadata: 0/300 and 0/300 flagged when vetted. Mutation check: 19 of 19 caught.

## Fix round 2 (`wp/P0-REPO`, 2026-10-18): complete

Review r2 (`state/reports/P0-REPO-r2.md`) and D108 are addressed on `wp/P0-REPO`. Nothing is left open for
P0-REPO in this round. Evidence: `$FLMOD_TESTRUNS/20261018T073321Z-p0-repo-fix2/` (scripts in `scripts/`).
Earlier rounds: `20261018T052428Z-p0-repo-fix1/` (r1 fixes), `20261018T063805Z-p0-repo-resume/` (re-check after
the reboot).

If interrupted again: re-run `pytest tests/py/test_check_public.py` (3.13 and 3.11), `check_public --tree` on the
worktree and the main checkout, `scripts/r5eval.py` (recall and false positives) and `harness/ci.sh --quick`.

### Review r2 findings

| # | What changed | Tests |
|---|---|---|
| 1 R5 blocks our own schemas | D108 escape: `check_public: authored-data <reason>` in the first 5 lines turns R5 into a warning, only under `data/ tests/ harness/ gen/ docs/spec/ src/**/tests/`. The reason must contain a letter or digit. It never applies to R1, R2, R4 or R7, to base64-embedded text, to binary content or inside archives. The R5 message names the escape. The table rule counts only FL-distinctive columns. | `test_r5_authored_data_header_*`, `test_r5_table_counts_only_distinctive_columns` |
| 2 compact JSON, flow YAML, dict literals | Lines over 4000 characters: line-anchored forms read the head, inline pairs are read in 4 KB chunks with a 512-byte overlap (a pair counts in the chunk where it starts). Inline matchers: quoted keys (JSON, `'k': v` repr/dict literals) and flow-style keys after `{`/`,`. In code, only pairs with literal values count, and the plain "sections + any keys" rule is off (patch-op dicts use a `section` key). Numeric vectors inside list values count as FL-shaped values. R7 also tries lines over 1000 characters re-broken one item per line (query side only; the index format is unchanged). | `test_r5_compact_json_flow_yaml_dict_literals_and_long_lines_rejected`, `test_r5_own_code_with_fl_names_passes`, `test_r5_corpus_hde_ini_rejected_in_every_text_form`, `test_r5_r7_corpus_minified_r3data_extracts_rejected` |
| 3 R4-email false positives | `git@<host>:` and `ssh://git@<host>` are clone URLs. Vetted `docs/` images get the blocklist, real secret shapes and R5 on their bytes (R5 kept: FL data in a PNG text chunk; it needs 20 FL key pairs, so noise cannot trip it). | `test_r4_git_ssh_clone_urls_are_not_emails`, `test_r1_vetted_docs_image_bytes_get_blocklist_secret_shapes_and_r5_only` |
| 4 decomp exemption too wide | Citations allowed only under `docs/`, in documentation files (`.md .markdown .rst .txt`) under `state/` (the ledger cites the decomp in reviews and briefs), or in files named `NOTES*`/`README*`. | `test_r4_decomp_marker_doc_exemption_is_limited`, `test_r4_decomp_marker_may_be_cited_in_docs` |
| 5 table header position, HTML | CSV/TSV/semicolon header within the first 10 non-blank, non-comment lines; Markdown pipe tables and HTML tables (`th` or first-row `td`) anywhere. | `test_r5_table_header_after_comments_and_markdown_and_html_tables` |
| 6 short signatures | Bink (`BIK`/`KB2`) and both PDB headers need a NUL byte; cab needs `MSCF` plus 4 zero bytes; PSD needs version 1 or 2. | `test_r1_text_that_starts_like_a_short_signature_is_text`, `MAGIC_CASES` |
| 7 notes location | This file. | n/a |
| 8 + D108 | `api_key` is a marker only in assignment/value form: lower-case `name = …`, `"name": …`, `name: …`, and upper-case `NAME=…`. An upper-case env-var name as a dict key or string (env allowlists in sidecar tests) is not a marker. `w:<literal>` blocklist entries match whole words (no letter, digit or underscore on either side) in content, paths and UTF-8/UTF-16LE bytes. | `test_r4_api_key_names_are_markers_only_in_assignment_form`, `SECRET_MARKERS`, `test_r4_blocklist_word_entries_match_whole_words_only` |
| CI | `requirements-dev.txt` (pytest, PyYAML, jsonschema). The workflow installs it, pins `actions/checkout@v7` and `actions/setup-python@v7`, and runs pytest once per existing directory among `tests/py` and `sidecar/tests`. | `test_workflow_*` |

### Measurements (fix round 2)

- HDE INI files with 50 or more key lines (345), rejected by R5 alone: Markdown, text, block YAML and flow YAML
  98.8%; indented, compact and minified JSON and repr dumps 96.5%; Python dict literals in a `.py` file 92.5%
  (`r5-recall-and-negatives.txt`).
- R3-data JSON extracts minified to one line: 15 of 15 rejected (12 by R5; the other 3 by R7 through the re-broken
  query).
- False positives: R5 flags 0 of 777 text files (main @635be56, DATATOOLS @4d9b317, HARNESS @181ebcc,
  SIDECAR @824564a, TOOLCHAIN @5825345, this worktree). The full checker passes every one of those trees
  (`negatives-full-checker.txt`). Random-byte PNGs under `docs/`: 0 of 300 flagged when vetted; the same bytes
  under every rule give 3 of 300 (`png-noise.txt`).
- Mutation check: 25 of 25 mutations of the new code are caught (`mutate3.txt`).
- Actions approximation (scrubbed environment, Python 3.11, only `requirements-dev.txt`, git work tree of
  DATATOOLS + SIDECAR + this branch): `check_public --tree` OK; `tests/py` 333 passed, 13 skipped;
  `sidecar/tests` 279 passed, 17 skipped (`actions-sim.txt`). A single combined pytest run fails collection
  (sidecar tests import `conftest` by name and get DATATOOLS'; `actions-sim-combined.txt`), hence one run per
  directory.

### Decisions (fix round 2)

- D108 escape implemented as written, plus: no escape for base64-embedded, binary or archive-member content.
- `state/` documentation files may cite the decomp (the ledger does), besides `docs/` and `NOTES*`/`README*`.
- `api_key`: upper case counts only in `NAME=` form (D108's list), so env allowlist code can name the variable.
- Vetted images keep R5 on their bytes, besides the blocklist and real secret shapes.
- In code files, a `section` key does not make INI sections count without FL key pairs.

### For the orchestrator (done, kept for the record)

- The tailnet-host blocklist entry was converted to the `w:` form and CONVENTIONS §12 documents the marker
  (D112, superseding the `_check_public` JSON key suggested here in fix round 2).
- `wp/P0-REPO` was squash-merged (D106: its intermediate commits failed `--commits`).

## History

- Review r1 (F1–F13): fixed in `0ecf9b4`; see `20261018T052428Z-p0-repo-fix1/` and `state/reports/P0-REPO-r1.md`.
- Session 2 re-check after the GPU-reset reboot: `32ab66a`.
- Review r2: fixed in fix round 2; r3 PASS, squash-merged as `eb051ed`.
- Review r3 MINORs + D112: `wp/P0-REPO-b` (RESUME POINT above).
