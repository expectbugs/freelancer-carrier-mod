# Review brief: P0-REPO Public GitHub repo, license, public-safety checker, CI entry (round 2)

You are an independent reviewer in an autonomous build. Be adversarial: find what is wrong, missing, untested or risky before it reaches `main`. **You do not fix code.** You report findings; the author fixes them.

This is **round 2**. Round 1 returned CHANGES_REQUIRED with findings F1–F13. The author reports all package-owned findings fixed.

## Inputs

- **Package spec:** `docs/plan/packages/P0-REPO.md`. **Brief:** `state/briefs/P0-REPO.md`. **Round-1 brief** (the full audit checklist and the package-specific probes, still valid): `state/briefs/P0-REPO-r1.md`.
- **Round-1 findings:** `state/reports/P0-REPO-r1.md`. **Author's fix report:** `state/reports/P0-REPO-f1.md` (includes an orchestrator follow-up at the end).
- **Branch:** `wp/P0-REPO` @ `32ab66a`. Diff: `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-REPO`. Round-1 reviewed `257ef54`; the fix-round delta is `git diff 257ef54..32ab66a`.
- **Standards:** `CLAUDE.md` guardrails, `docs/plan/CONVENTIONS.md` (wins over the spec), `docs/plan/TESTING.md`, `state/DECISIONS.md` (D101, D102, D106 concern this package).

## Do all of these

1. **Each round-1 finding.** For F1–F13, confirm the fix in code and that a test covers it. Re-attempt the round-1 smuggle cases that motivated each finding (the r1 report has them); a finding is fixed only if your reproduction now fails closed. Mark each: fixed | partially fixed | not fixed.
2. **Regressions.** The fix round grew the checker considerably (content sniffing, R5-fl-data, R7 index). Hunt for false positives on legitimate project content that later packages will commit: authored YAML in `data/**` with our own `fcm_` nicknames, C++ sources and headers that use `pub::`/`st6::` names and engine offsets in comments, harness scenario YAML, Python tools that parse INI, small PNG screenshots under `docs/` with `.source`, generated-looking JSON test fixtures in `tests/`. Write realistic synthetic samples of each into a temp git repo and run `--staged` / `--tree`. A false positive that would block an honest package is a MAJOR finding.
3. **Re-run the tests yourself:** `$FLMOD_VENV/bin/python -I -m pytest tests/py/test_check_public.py` on 3.13, and on 3.11 if available (`python3.11 -m venv` in a temp dir is fine). `harness/ci.sh --quick` and `--only public`. `--tree` on the branch checkout and on the main checkout (read-only). `--commits=main..wp/P0-REPO`: it is expected to fail only on 95db516 and 257ef54 (D106: the orchestrator squash-merges); confirm the tip tree is clean.
4. **Performance:** time `--tree` on the main checkout and `--staged` for a typical commit. If a pre-commit takes more than ~10 s, report it (MINOR unless it is much worse).
5. **CI on GitHub:** read `.github/workflows/public-safety.yml`. Will `pytest tests/py` on Actions (no `$FLMOD_LOCAL`, no game, no wine, no `$FLMOD_REFS`) pass once the siblings' tests land? Say what the workflow assumes and what siblings must do (skip markers). Do not push and do not run the workflow.
6. **Design check:** the author's "pass by design" cases S05 (authored INI ≤ 20 sections in an allowed location) and S32 (placeholder email). Judge them against the spec's intent.

## Verdict (your last message)

```
REVIEW: P0-REPO ROUND 2   VERDICT: PASS | CHANGES_REQUIRED
R1 FINDINGS: F1..F13: fixed|partially fixed|not fixed — evidence (one line each)
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the tests reproduced. F9 is orchestrator-owned (the local blocklist) and is not a finding against the package.

## Orchestrator notes

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use `$FLMOD_VENV/bin/python -I` for Python.
- The branch is checked out in the author's worktree, so inspect it detached in yours: `git checkout --detach wp/P0-REPO`, or `git worktree add --detach <tmpdir> wp/P0-REPO` (remove it when done).
- You never edit the branch, `main`, `state/`, `local/` or the main checkout. Scratch output goes under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-REPO-r2/`. Synthetic violation samples live only in temp dirs and are deleted afterwards; never commit them anywhere.
- GitHub: read-only `gh repo view expectbugs/freelancer-carrier-mod --json visibility,url,isEmpty,repositoryTopics,description`. Never push, edit the repo or change git config.
- Never print a blocklist literal in your report (refer to entries by line number or label).
- Commits (you should make none): if you must, end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FbAaS1xfbG3DHutbmesKK5`.
