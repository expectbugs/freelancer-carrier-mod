# Review brief: P0-DATATOOLS fltools, generator framework, validator, deploy (round 2)

You are an independent reviewer in an autonomous build. Be adversarial: find what is wrong, missing, untested or risky before it reaches `main`. **You do not fix code.** You report findings; the author fixes them.

This is **round 2**. Round 1 (on `1a99d13`) returned CHANGES_REQUIRED (MAJOR M1–M3, MINOR m1–m8). The author reports all fixed, plus an orchestrator-approved addendum (D107: `harness.*` patch units preserved by gen deploy).

## Inputs

- **Package spec:** `docs/plan/packages/P0-DATATOOLS.md`. **Brief:** `state/briefs/P0-DATATOOLS.md`. **Round-1 brief** (full audit checklist and package-specific probes, still valid, including the substitute resource-DLL loader check and the data-hygiene audit): `state/briefs/P0-DATATOOLS-r1.md`.
- **Round-1 findings:** `state/reports/P0-DATATOOLS-r1.md`. **Author's fix report + D107 addendum:** `state/reports/P0-DATATOOLS-f1.md`. Decisions D106, D107 in `state/DECISIONS.md`. Design notes: `tools/fltools/NOTES.md` §7 on the branch.
- **Branch:** `wp/P0-DATATOOLS` @ `8eb78e3`. Diff: `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-DATATOOLS`; fix-round delta: `git diff 1a99d13..8eb78e3`.
- **Standards:** `CLAUDE.md` guardrails (4: data hygiene; 5: public repo), `docs/plan/CONVENTIONS.md` §2 nicknames, §12 data hygiene (wins over the spec), `docs/plan/TESTING.md`.

## Do all of these

1. **Each round-1 finding:** confirm the fix in code and a test that would fail on the old code. Mark each fixed | partially fixed | not fixed, with evidence.
2. **Transactional deploy (M2)** — attack it: kill the deploy process (SIGKILL) at several points (use a debugger breakpoint, an env-var fault hook if one exists, or `strace -e inject=…:error=…` on a chosen write/rename) and confirm `undeploy` or the next `deploy` always restores a byte-identical install (files and directory set). Disk-full and permission-denied on one file mid-deploy. Concurrent deploys on the same install (the lock).
3. **Play-prefix guard (M3):** try every writer and CLI entry point against `/home/user/freelancer/prefix` via direct paths, `..`, symlinks, bind-like tricks (a symlinked parent dir), relative paths from a cwd inside it, and env vars unset/pointing elsewhere. It must refuse **before** reading or writing anything there (check with `strace -f -e trace=openat,open,creat,rename,unlink,mkdir` or inotify that nothing under the play prefix is opened for writing). Never actually modify the play prefix: if a guard turns out to be missing, stop that probe immediately, record it, and check `tools/play_prefix_manifest.sh verify` (read-only).
4. **Validator (m3):** the new C001 `fcm_` rule and overlay-ERROR promotions — false positives on legitimate overlay content (our own `fcm_` sections, `[Room]`, patch units adding keys to vanilla sections), and false negatives (a vanilla-named new nickname smuggled in a patch unit).
5. **D107:** gen deploy/redeploy/undeploy with a `harness.*` unit, both orders; gen refusing the namespace; undeploy keeping the patch state file while harness units remain. Is the API something `harness/lib/deploy.py` can call simply (one function, documented)?
6. **Re-run:** `pytest tests/py/fltools` with and without game data (hide the data by env var or empty install path; never move the real install); CI stage 30 through the real `harness/ci.sh` from `wp/P0-REPO` (temp checkout); the substitute resource-DLL loader check from the r1 brief if round 1 didn't complete it (see the r1 report).
7. **Data hygiene and public safety:** nothing derived from game files committed (fixtures, goldens, `baseline_findings.txt`, strings in tests/docs). `$FLMOD_VENV/bin/python -I $FLMOD_LOCAL/snapshots/check_public.py --tree <checkout>` and `--commits=main..wp/P0-DATATOOLS` (intermediate commits 463eb68/1a99d13 are expected to fail on decomp markers per D106; the tip must be clean).

## Verdict (your last message)

```
REVIEW: P0-DATATOOLS ROUND 2   VERDICT: PASS | CHANGES_REQUIRED
R1 FINDINGS: <finding>: fixed|partially fixed|not fixed — evidence (one line each)
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the test suite reproduced.

## Orchestrator notes

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use `$FLMOD_VENV/bin/python -I`.
- Inspect the branch detached in your worktree (`git checkout --detach wp/P0-DATATOOLS`).
- Deploy tests run only on throwaway reflink copies you create (e.g. `cp -a --reflink=always` of the HDE dir from `prefix-dev-base-B` into a temp dir, or a `prefix-dev-review-datatools` clone). Delete them afterwards. Wine runs (the loader probe) only in your own `prefix-dev-review-datatools`; kill only its wineserver; GPU watch per `state/briefs/RESUME-2026-10-18.md`.
- You never edit the branch, `main`, `state/`, `local/` (except your run dir) or the main checkout. Scratch output goes under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-DATATOOLS-r2/`.
- Commits (you should make none): if you must, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FbAaS1xfbG3DHutbmesKK5`.
