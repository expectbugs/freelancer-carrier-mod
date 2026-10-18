# Resume: P0-REPO (attempt 1, review r1 fix round 1, continued)

Read `state/briefs/P0-REPO.md` (your brief), then `state/briefs/RESUME-2026-10-18.md` (common resume rules, which win), then this file.

- **Start point:** `git checkout wp/P0-REPO`; expect HEAD `4e02754`.
- **Read first:** the RESUME POINT in `harness/ci.d/NOTES-P0-REPO.md`, then the review `state/reports/P0-REPO-r1.md`.
- **State:** findings F1–F8 and F10–F13 are done (183 tests passed at checkpoint). Check F9 and anything else the RESUME POINT lists as open, and finish it.
- **Remaining:** re-run the whole test suite (`$FLMOD_VENV/bin/python -I -m pytest tests/py/test_check_public.py` plus anything else you own), `check_public --tree` on your worktree, and the per-finding fix report.
- **History:** your early commits (95db516, 257ef54) fail `--commits` (D106). Do not rewrite them; the orchestrator squash-merges your branch. Make sure the tip is clean.
- **After merge** the orchestrator will push main and check the first Actions run. Note in your report anything the orchestrator must do for that (e.g. `--build-index` before the first push, branch protections you did not set).
- The snapshot `$FLMOD_LOCAL/snapshots/check_public.py` is a copy of your own checker at 4e02754 for the siblings. You don't need it.
