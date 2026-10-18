# Review brief: P0-REPO Public GitHub repo, license, public-safety checker, CI entry (round 1)

You are an independent reviewer in an autonomous build. Be adversarial: your job is to find what is wrong, missing, untested or risky before it reaches `main`.

**You do not fix code.** You report findings; the author fixes them.

## Inputs

- **Package spec:** `docs/plan/packages/P0-REPO.md`
- **Brief:** `state/briefs/P0-REPO.md`
- **Author's report:** pasted below (also `state/reports/P0-REPO-a1.md`).
- **Branch:** `wp/P0-REPO` @ `257ef54`. Review with `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-REPO`. To build or run, check it out in your own worktree.
- **Standards:**
  - `CLAUDE.md` guardrails
  - `docs/plan/DESIGN.md`
  - `docs/plan/TESTING.md`
  - `state/ENGINE_FACTS.md`
  - research pitfalls: `local/research/R4-lore-and-testloop.md` §A1, and `R2` §0 item 15

## Do all of these

1. **Requirements.** For every `REQ-P0-REPO-n`, find the code and the test that cover it. Mark each one covered, partial or missing.
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
REVIEW: P0-REPO ROUND 1   VERDICT: PASS | CHANGES_REQUIRED
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the primary scenario reproduced.

## Orchestrator notes for this review

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use `$FLMOD_VENV/bin/python -I` for Python.
- The branch is checked out in the author's worktree, so inspect it detached in yours: `git fetch` is not needed (same repo); run `git checkout --detach wp/P0-REPO` (or `git worktree add --detach <tmpdir> wp/P0-REPO`).
- Run the public-safety checker on the branch's commits: `python3 -I tools/check_public.py --commits=main..wp/P0-REPO` (from a checkout that has it) and `--tree` on the branch checkout.
- You never edit the branch, `main`, `state/` or the main checkout. Write any scratch output under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-REPO-r1/`.
- Game runs only through the harness on a locked lane, if the harness exists on the branch or main; otherwise state that in REPRODUCED.
- Package-specific: verify the GitHub repo state with read-only `gh repo view expectbugs/freelancer-carrier-mod --json visibility,url,isEmpty,repositoryTopics,description`. Do not push, edit the repo, or change git config.
- Judge the author's interpretive decisions 1–5 (plan-doc exemption scope, synthetic literal scope, R5 threshold, image policy, directory matching) against the spec's intent: "impossible to commit or push game files/extracts, decompiled code, other mods' content, local/ research, secrets, or personal infrastructure details". Try to smuggle realistic violations past `--staged`, `--tree` and `--commits` (e.g. an INI block renamed .txt or .yaml with snake_case keys disguised, a decompiled-looking .cpp with Freelancer-Decomp marker, a .utf/.3db/.mat renamed, a base64 blob, an email under docs/, a path containing local/research). Report misses as findings.
- Confirm that `harness/ci.sh` matches TESTING §CI and CONVENTIONS §5 exactly (flags, stage discovery, SKIP on missing prerequisites, summary.md path in `$FLMOD_TESTRUNS`).

## Author's report

```
PACKAGE: P0-REPO   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-REPO @ 257ef54
SUMMARY: The public repo is created and empty; nothing was pushed. The checker, git hooks, CI entry point, workflow and README are committed on the branch. Both commits went through the new pre-commit hook. Evidence dir: E=/home/user/freelancer/carrier-mod/local/testruns/20261018T043920Z-p0-repo-acceptance/
FILES: tools/check_public.py, .githooks/{pre-commit,pre-merge-commit,pre-push}, harness/ci.sh, harness/ci.d/README.md, .github/workflows/public-safety.yml, README.md, tests/py/test_check_public.py
TESTS:
- pytest test_check_public.py: 90 passed on Python 3.13 and on 3.11, 0 skipped — PASS — E/pytest.log, E/pytest-py311.log. Every rule has a positive and a negative case. 8 deliberate breakages of the checker were each caught by the tests (VERIFIED).
- --tree on my worktree (108 files) and on the main checkout (100 files) — PASS — E/check-tree-*.log. The main checkout has local/, vendor/, .venv/ and .claude/worktrees/, and none were scanned.
- Commits blocked in my worktree for a dummy foo.cmp [R1-ext], a 30-line [Ship] markdown file [R5-bulk-ini] and the synthetic 192.168.1.77 [R4-ip] — PASS — E/neg1..3-*.log. Each was reset and deleted afterwards.
- A real blocklist line written only into tmp_path and scanned with --tree: rejected, never printed, file deleted — PASS (pytest; ran, not skipped).
- 6 MB file in a temp repo, .dll needing --allow-binaries, a drop-in exiting 77 shows SKIP, one exiting 1 fails the run (via CI_D_DIR) — PASS (pytest).
- ci.sh --quick and --only public: exit 0, summary.md written — PASS — E/ci-quick.log, E/ci-only-public.log.
- History scan of every commit on all refs (trees, identities, messages) — PASS — E/check-history.log. A raw `git log -p` dump also has no blocklist or email hits.
- gh repo view: PUBLIC, isEmpty=true, 6 topics — PASS — E/gh-repo-view.json
- Workflow YAML parses — PASS — E/workflow-yaml.log. The Actions run itself is UNVERIFIED until you push.
VERIFIED FACTS:
- gh api user is login expectbugs, id 206848374. Token scopes: repo, workflow, gist, read:org. The hosts.yml label is different and I left it out.
- Repo: https://github.com/expectbugs/freelancer-carrier-mod. origin and core.hooksPath=.githooks are set in the shared repo config.
- Every author and committer email in history is 206848374+expectbugs@users.noreply.github.com, matching the configured user.email.
- LICENSE is byte-identical (sha256 0d96a4ff…abcb0) to Gentoo's AGPL-3 and to Debian's common-licenses/AGPL-3.0.
- If .githooks is missing, as in sibling worktrees branched before this merge, commits still work.
DECISIONS:
1. "Plan doc" scope is docs/plan/ and state/. There, mentioning the owner's other projects or naming bare secret markers is allowed. Real secret shapes (sk-ant keys, gh tokens, PEM headers) are rejected everywhere. Read literally, the spec fails on docs/plan/packages/P0-REPO.md:43 [R4-secret] and state/briefs/P0-SIDECAR.md:68 [R4-personal-project]. Those are the only hits in the current tree.
2. The synthetic values 10.1.2.3 and 192.168.1.77 are allowed only under docs/plan/, state/ and tests/. The spec says "always allowed", but its acceptance test requires a staged 192.168.1.77 file to fail. someone@example.net passes everywhere because example.com/.org/.net are allowed as placeholder domains.
3. R5: a file is rejected when more than 24 lines (three 8-line runs' worth) of INI-looking text sit in runs of 8+ lines. A literal "more than 3 runs" misses the spec's own 30-line fixture, which is one run. A run counts only if at least 3 keys (and 25%) are fingerprint keys. Code and template values don't count. .ini files are left to R2.
4. Images are allowed only as png/jpg under docs/, at most 512 KB, with a `.source` file. Everything else is rejected, including .dds and .tga. .wma, .wmv and .bik are added to the forbidden extensions.
5. Forbidden directories (local, build, out, vendor, refs, .venv) are matched at any depth, case-insensitive. IPs need valid octets, so Windows SDK version strings don't match. Secret identifiers are case-sensitive.
6. Added beyond the spec: a `--commits` mode, a pre-push hook and a pre-merge-commit hook. A file added and later deleted on a branch stays in history, and `git merge` skips pre-commit. Archives are opened and their members vetted.
7. ci.sh stops at the first FAIL (TESTING §CI) and lists the rest as NOT RUN. `--only` ignores the mode cutoff, and a canonical stage with no drop-in reports SKIP. A non-executable drop-in is a FAIL, and the exit code wins over the printed verdict. It sources tools/env.sh first.
8. The ci.sh tests live in test_check_public.py, the only test file I own.
OPEN QUESTIONS / BLOCKERS: none blocking.
- Before every merge, run `python3 -I tools/check_public.py --commits=main..wp/<ID>`. The first push vets main's whole history, and AUTONOMY forbids rewriting main, so a bad intermediate commit must be fixed on the branch. All current wp/* commits pass (snapshot).
- If you'd rather edit the briefs than keep the state/ exemption, remove state/ from PLAN_DOC_PREFIXES. Future sidecar briefs copy specs that name those projects, so they will trip it too.
- .gitignore covers every REQ-9 item. Gap: build/, out/ and vendor/ are anchored at the root, so a nested spikes/*/build/ shows as untracked and fails the public stage. I suggest unanchored `build/` and `out/`, and optionally `*.dll *.exe *.lib *.dmp *.mdmp`.
KNOWN ISSUES:
- `--no-verify` bypasses the hooks (AUTONOMY forbids it).
- `--commits` arguments that start with `--` need the `=` form.
- Sibling tests under tests/py must skip when local resources are absent, because Actions runs `pytest tests/py`.
- Large inline INI samples in .py tests trip R5; the message points to tests/fixtures-authored/*.ini.
- No bug needed a 10-hypothesis analysis: the one self-flag pointed at its exact line, so there is no NOTES.md.
```

