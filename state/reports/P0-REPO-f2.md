Fix round 2 is done. Every r2 finding and the workflow addition are fixed and committed on `wp/P0-REPO` @ `04e73d3`. There was no GPU fault (no game runs in this package). Evidence is in `$FLMOD_TESTRUNS/20261018T073321Z-p0-repo-fix2/` (E below); notes are in `.github/NOTES-P0-REPO.md` on the branch.

**Fix report**

| # | Change | Test | Evidence | Status |
|---|---|---|---|---|
| 1 MAJOR | D108 escape as written: `check_public: authored-data <reason>` in the first 5 lines turns R5 into a WARNING, only under data/, tests/, harness/, gen/, docs/spec/, src/**/tests/. An empty reason has no effect. It never covers R1/R2/R4/R7, base64, binary or archive members. The R5 message names the escape. Table columns: FL-distinctive only. | `test_r5_authored_data_header_*` (world.json with 12 objects, NPC YAML with 10 entries, outside dirs, reason/line 5, cannot rescue R1/R2/R4/R7), `test_r5_table_counts_only_distinctive_columns` | E/pytest-py313.log | DONE |
| 2 MAJOR | Long lines read in 4 KB chunks; quoted-key, flow-YAML and dict-literal pairs (in code: literal values only); vectors inside lists count. R7 also tries minified lines re-broken one item per line. | compact/flow/dict-literal/long-line test, two corpus tests | E/r5-recall-and-negatives.txt | DONE |
| 3 MINOR | `git@host:` and `ssh://git@` are not emails. Vetted docs images get blocklist, real secret shapes and R5 only. | `test_r4_git_ssh_*`, `test_r1_vetted_docs_image_*` | E/png-noise.txt | DONE |
| 4 MINOR | Decomp citations allowed only in docs/, NOTES*/README* doc files, and state/ doc files. | `test_r4_decomp_marker_doc_exemption_is_limited` | E/negatives-full-checker.txt | DONE |
| 5 MINOR | CSV/TSV header found in the first 10 non-comment lines; Markdown pipe and HTML tables anywhere. | `test_r5_table_header_after_comments_*` | — | DONE |
| 6 MINOR | Bink/PDB need a NUL byte; cab needs its zero header bytes; PSD needs a version. | `test_r1_text_that_starts_like_*`, `MAGIC_CASES` | — | DONE |
| 7 MINOR | Notes moved to `.github/NOTES-P0-REPO.md` and refreshed. | — | — | DONE |
| 8 + D108 | `api_key` is a marker only in assignment form; `w:` blocklist entries match whole words in text, paths, UTF-8 and UTF-16LE. | `test_r4_api_key_*`, `test_r4_blocklist_word_entries_*` | — | DONE |
| CI | `requirements-dev.txt` (pytest, PyYAML, jsonschema); workflow installs from it; actions pinned to v7; pytest runs `tests/py` and `sidecar/tests`, one run per existing directory. | `test_workflow_*` | E/actions-sim.txt | DONE |

On the action versions: checkout v4 and setup-python v5 declare `node20`, and the latest releases (checkout v7.0.1, setup-python v7.0.0) declare `node24` (VERIFIED with `gh api`). That's why I pinned v7.

On `sidecar/tests`: the workflow runs pytest once per existing directory. A single combined run fails collection with exit 2, because the sidecar tests do `from conftest import …` and pick up DATATOOLS' `conftest` (VERIFIED in E/actions-sim-combined.txt).

```
PACKAGE: P0-REPO   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-REPO @ 04e73d3
SUMMARY: Review r2 fix round 2 complete: the D108 escape, compact/flow/dict-literal
  detection, table rules, R4/R1 false-positive fixes, w: blocklist entries, CI deps and
  workflow. No R5 false positives on 777 clean files; 25 of 25 code mutations caught.
FILES: tools/check_public.py, tests/py/test_check_public.py, .github/workflows/public-safety.yml,
  .github/NOTES-P0-REPO.md (moved from harness/ci.d/), requirements-dev.txt (new)
TESTS:
  pytest test_check_public.py, Python 3.13.15: PASS, 226 passed. VERIFIED E/pytest-py313.log
  pytest, Python 3.11.16 (fresh venv, requirements-dev.txt only): PASS, 226 passed. VERIFIED E/pytest-py311.log
  R5 recall on 345 HDE INI files: md/txt/block YAML/flow YAML 98.8%; indented, compact and
    minified JSON and repr dumps 96.5%; .py dict literals 92.5% (no threshold was set).
    VERIFIED E/r5-recall-and-negatives.txt
  Minified R3-data extracts: 15/15 rejected (12 by R5, 3 by R7). VERIFIED (same file)
  False positives: R5 flags 0/777 files (main @635be56, DATATOOLS @4d9b317, HARNESS @181ebcc,
    SIDECAR @824564a, TOOLCHAIN @5825345, this worktree). The full checker passes all 5 exported
    trees. VERIFIED E/negatives-full-checker.txt
  Vetted noise PNGs: 0/300 flagged (3/300 if every rule applied). VERIFIED E/png-noise.txt
  Mutations: 25/25 caught. VERIFIED E/mutate3.txt
  --tree worktree: OK (110 files); main checkout: OK (144 files). VERIFIED E/tree-*.log
  --commits=main (54 commits): OK. VERIFIED E/commits-main-all.log
  --commits=main..HEAD: FAIL on intermediate commits 95db516, 257ef54, 32ab66a only. The tip is
    clean; the squash-merge (D106) drops them. VERIFIED E/commits-main..HEAD.log
  ci.sh --quick: PASS. VERIFIED E/ci-quick.log
  Actions approximation (clean environment, 3.11, git work tree of DATATOOLS + SIDECAR + this branch):
    check_public OK; tests/py 333 passed 13 skipped; sidecar/tests 279 passed 17 skipped.
    VERIFIED E/actions-sim.txt. The real Actions run: UNVERIFIED until the push.
DECISIONS:
  1. state/ doc files may cite the decomp. Otherwise main fails today on two r1 ledger files.
  2. api_key: lower case in all three D108 forms; upper case only as NAME=. A SIDECAR env-allowlist
     test uses "ANTHROPIC_API_KEY": "dummy" as a dict key and must stay legal.
  3. Vetted images keep R5 on their bytes (FL data in PNG text chunks; needs 20 FL key pairs, so
     noise cannot trip it).
  4. In code files, a "section" key doesn't count as INI sections unless FL key pairs are present.
     A DATATOOLS patch-ops test needs this.
  5. Escape not applied to base64, binary or archive-member content.
  6. R7 re-breaking of long lines is query-side only: the index format is unchanged and no
     rebuild is needed.
ENGINE FACTS LEARNED: none.
OPEN QUESTIONS / BLOCKERS: none. Orchestrator to-dos:
  - Convert the short tailnet-host blocklist entry to w:.
  - Amend CONVENTIONS §12 for the authored-data header. JSON has no comments, so the header goes in
    the value of a first key such as "_check_public", and the schema must allow that key.
  - Squash-merge, run --tree . and --commits=main, push, then check Actions on 3.11 and 3.13.
KNOWN ISSUES:
  - .py dict-literal recall is 92.5%: in code, lists of strings aren't counted, to avoid false positives.
  - Without the index (the case on Actions), 3 minified R3-data extracts pass; locally R7 catches them.
```
