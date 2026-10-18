# Resume: P0-DATATOOLS (attempt 1, review r1 fix round 1, continued)

Read `state/briefs/P0-DATATOOLS.md` (your brief), then `state/briefs/RESUME-2026-10-18.md` (common resume rules, which win), then this file.

- **Start point:** `git checkout wp/P0-DATATOOLS`; expect HEAD `463eb68`.
- **Read first:** the RESUME POINT in `tools/fltools/NOTES.md`, then the review `state/reports/P0-DATATOOLS-r1.md`.
- **Remaining (per the ledger):** MAJOR 1 is done; MAJOR 2/3 code is done but has no tests; the data-hygiene and validator-severity MINORs are not started; then the remaining MINORs with tests, the report text, and the marker-clash proposal.
- **D106:** move the decomp citations out of `tools/fltools/hash.py` and `tools/fltools/ini.py` into `tools/fltools/NOTES.md` ("see NOTES.md §x" in code). Re-run `check_public --tree` on your worktree afterwards.
- **Never** write to the play prefix; tests use temp dirs and read-only views (your branch already has the play-prefix guard on write paths — keep it covered by a test).
