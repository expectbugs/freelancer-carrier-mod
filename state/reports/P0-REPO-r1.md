The verdict is CHANGES_REQUIRED: four MAJOR findings, no BLOCKER. Everything the author claimed reproduced. The problem is that the gate misses most realistic leaks: most real game data, unmarked decompiled code, renamed game binaries, and right now no commit hook runs at all. Evidence is in E=/home/user/freelancer/carrier-mod/local/testruns/20261018T044811Z-review-P0-REPO-r1/.

```
REVIEW: P0-REPO ROUND 1   VERDICT: CHANGES_REQUIRED
COVERAGE:
REQ-P0-REPO-1: covered. PUBLIC, isEmpty=true, description exact, 6 topics, 0 branches (pushedAt is 1 s after createdAt), origin set (E/gh-repo-view.json).
REQ-P0-REPO-2: covered. LICENSE sha256 0d96a4ff…abcb0, cmp-identical to Gentoo AGPL-3.
REQ-P0-REPO-3: covered. Every required README item is present; no IPs, emails or personal paths.
REQ-P0-REPO-4: partial. All modes are implemented and unit-tested against the spec's wording, but R1, R4-decomp and R5 miss most realistic violations, and --release accepts a symlinked .dll (findings 1-3, 5).
REQ-P0-REPO-5: partial. The hook is correct when hooksPath is relative. The live shared config holds an absolute path, so no hook runs anywhere today, and after the merge sibling worktrees cannot commit (finding 4).
REQ-P0-REPO-6: covered. `git log --all --format='%ae%n%ce'` gives only the noreply address. user.email is that noreply address.
REQ-P0-REPO-7: covered. CLI, NN-<name> lexical discovery, quick <60 / default <=60 / full, SKIP 77, canonical stage via --only with no drop-in = SKIP, stop at first FAIL, CI_MODE/LANES/RUNDIR/QUARANTINE, $FLMOD_TESTRUNS/<stamp>-ci/summary.md and exit codes all match TESTING §CI and CONVENTIONS §5.
REQ-P0-REPO-8: covered. Runs on push and PR on ubuntu-latest, check_public --tree then pytest tests/py, no secrets, no game, YAML parses. The Actions run itself is UNVERIFIED until the orchestrator pushes.
REQ-P0-REPO-9: covered (verify only). Every listed pattern is present. The author's note stands: nested build/ and out/ are not ignored because the patterns are anchored.
REPRODUCED:
pytest test_check_public.py (venv 3.13): reproduced. 90 passed, and 20 of 20 repeat runs green (E/pytest.log, E/pytest-20x.log).
pytest on Python 3.11.16: reproduced. 90 passed (E/pytest-py311.log).
check_public --tree on the branch (108 files) and on the main checkout (102 files; local/, vendor/, .venv/ and .claude/worktrees exist but none were scanned): reproduced, OK (E/tree-*.log).
--commits=main..wp/P0-REPO, --commits=--all (16 commits) and main..wp/<each sibling>: reproduced, all OK (E/commits-*.log).
ci.sh --quick and --only public: reproduced. Exit 0, summary.md under $FLMOD_TESTRUNS (E/ci-*.log).
Hook blocks for foo.cmp, the 30-line [Ship] .md and 192.168.1.77: reproduced in temp repos (pytest, plus E/synthetic-smuggle.txt S01). In the shared repo the hooks are currently inactive (finding 4).
gh repo view, LICENSE, emails, workflow YAML: reproduced.
Primary in-game scenario: not applicable. The package has no game runs, and harness/lane.sh exists on neither main nor the branch.
"8 deliberate breakages caught": not re-run.
FINDINGS (ordered by severity):
1. [MAJOR] tools/check_public.py:152-165, 658-686 — R5 misses real game data.
   Problem:
   - Pasted into .md or .txt, 1185 of 1263 real HDE INI files pass (94%), including all of npcships.ini, loadouts.ini, goods.ini and market_*.ini. These are exactly the CONVENTIONS §12 classes.
   - Why: blank lines between sections close a run (:682-684), and a run needs at least 3 fingerprint keys (:668). NPCShipArch and Loadout blocks have only 2.
   - Prefixing lines with "> " also bypasses it.
   - Extracts in YAML or JSON form (`key: value`, `"key": v`) are not matched at all. All 15 research R3-data JSON/TSV extracts pass when copied under docs/ (E/smuggle-V3, V5, V8; E/r5-analysis.txt; E/synthetic-smuggle.txt S02-S08).
   Required change:
   - Blank and comment lines must not break a run.
   - Also count FL section headers in text files, and fingerprint-key lines file-wide.
   - Match YAML and JSON key forms against the fingerprint keys (the spec's own YAML rationale implies this).
   - Add a local-corpus test over $FLMOD_REFS/freelancer-hd-edition DATA/**/*.ini (skip if absent) that rejects at least 95% of files with 50 or more key/value lines, while the repo tree still passes.
2. [MAJOR] tools/check_public.py:55-61, 299-308, 441-459, 563-570 — R1 is extension-only, so renamed game binaries pass.
   Problem:
   - .dfm is missing from the list. These are FL meshes, and all 204 real HDE .dfm files pass as-is.
   - All 1419 real HDE binaries (cmp/3db/mat/txm/ale/utf/wav/dll…) pass when renamed .bin or *.cmp.txt.
   - Archives with unlisted names also pass: a .gz with no inner extension, or a zip named .jar.
   - So do MZ or PNG data under other extensions, base64 of a game file, and UTF-16 text without a BOM.
   - One NUL byte turns off every text rule: a 30-line INI with \x00 appended passes (E/smuggle-V1, V2; E/magic-survey.txt; synthetic S09, S14-S21, S27).
   Required change:
   - Sniff content: reject b"UTF " (one check covers 1354 HDE files), BINI, MZ, RIFF/WAVE, OggS, ID3, MDMP, "DDS ", MSF and \x1bLua.
   - Treat image signatures as images whatever the extension. Open PK/gzip/xz/bz2 data as archives whatever the name.
   - Add .dfm to the list.
   - Apply the text rules to a lossy decode of NUL-containing data and to UTF-16 detected without a BOM.
   - Add a test for each case.
3. [MAJOR] tools/check_public.py:148-149, 630-633 — the decompilation marker never matches the real decomp source.
   Problem:
   - 0 of 1413 code files in $FLMOD_REFS/Freelancer-Decomp contain "Freelancer-Decomp". 1279 carry the header "Freelancer Decomp: … reconstructed by reverse engineering".
   - Copied verbatim into src/, 1402 of 1413 pass; only 11 are caught, and only by the email rule.
   - The rule's scope also excludes spikes/, gen/, tools/, harness/ and tests/ (E/smuggle-V6, V6b; synthetic S11-S13).
   Required change:
   - Match the marker case-insensitively, allowing a space, dash or underscore between the words, plus the "reconstructed by reverse engineering" phrase.
   - Apply it to every code file outside docs/.
   - Add a corpus test against $FLMOD_REFS (skip if absent).
4. [MAJOR] .githooks/pre-commit:7-12, pre-push:10-15, pre-merge-commit:5 — no hook runs today, and siblings will be locked out after the merge.
   Problem:
   - The live shared .git/config holds core.hooksPath = <absolute main checkout>/.githooks, not ".githooks" as the spec and the author's report say. Main has no .githooks yet, so no hook runs in any worktree right now.
   - After the merge, the hooks look only for $top/tools/check_public.py. Every worktree branched before the merge then fails every commit (simulated: rc=1, "checker missing"; with a relative path rc=0; E/hookspath-sim.txt).
   - Who changed it is UNVERIFIED. The config mtime is 23:44:13, after the author's 23:36 negative tests, which could only have fired with a per-worktree path. No code on any branch sets it.
   - Candidate causes: Claude Code's worktree creation normalising the path, the orchestrator, a sibling's test leaking into the shared config, or the author after collecting evidence.
   Required change:
   - Hooks fall back to the checker next to the hook directory ($(dirname "$0")/../tools/check_public.py).
   - pre-merge-commit execs "$(dirname "$0")/pre-commit".
   - Add a test with an absolute hooksPath and a pre-merge worktree.
   - Orchestrator: decide which hooksPath value to keep.
5. [MINOR] tools/check_public.py:435-438, 694-701 — --release accepts a symlinked carrier.dll without --allow-binaries (rc=0). gh release upload follows symlinks. Required change: in --release mode, follow symlinks or reject them (E/release-symlink.txt).
6. [MINOR] tools/check_public.py:74-78 — the R2 header list lacks [BaseGood], [MBase], [MRoom] and others. A complete market file passes in tests/fixtures-authored/; overall 1184 of 1263 real INI files are accepted there (synthetic S05, E/smuggle-V4). Required change: count any [Section] header in authored .ini fixtures, or extend the list.
7. [MINOR] tools/check_public.py:770-815, 968 — zero-file scans pass silently. --staged run from a subdirectory reports "OK: 0 file(s)" while foo.cmp is staged, because ls-files paths are cwd-relative and diff paths are root-relative. --tree on an ignored dir (e.g. local/research) also reports OK with 0 files (E/staged-subdir.txt). Required change: run git from the toplevel, and warn or fail on an empty scan.
8. [MINOR] tools/check_public.py:122-135, 423-429 — misses (synthetic S23, S24, S28-S31). Required change: add these patterns and match paths against the IP and email rules.
   - Not matched: github_pat_ and ghs_/ghu_ tokens, "ANTHROPIC_API_KEY = " with a space, *.ts.net tailnet names, and leading-zero IPs.
   - Never checked: IPs and emails in file paths.
9. [MINOR] (orchestrator) local blocklist — 7 of 13 personal infrastructure details from the owner's global CLAUDE.md pass (hostnames, mount points, interface and device names). Research file R4-lore-and-testloop.md, whose title names the build machine, passes when copied under docs/ (E/infra-tokens.txt, E/smuggle-V8). Required change: add those literals to the blocklist.
10. [MINOR] (spec gap, orchestrator) — no rule covers other mods' content. 922 of 932 FLHook/FLUF source files pass in src/, and HDE .fx, .fxh and .ttf pass as-is (E/smuggle-V7, V1). Suggestion: a local fingerprint index of $FLMOD_REFS, gitignored like the blocklist.
11. [MINOR] tools/check_public.py:84, 759 — --tree skips all of .claude/ (the spec allows it). A tracked .claude/settings*.json would bypass the CI public stage and Actions; only pre-commit checks it. Required change: narrow the skip to .claude/worktrees/ (needs a CONVENTIONS amendment).
12. [MINOR] .githooks/pre-push — annotated tag messages are never checked, and gh release notes bypass the hooks. Note this for W5-SHIP.
13. [MINOR] tools/check_public.py:534 — a single-file .gz is fully decompressed before the 5 MB check. A compression bomb can exhaust memory; the checker fails closed but may be OOM-killed.
DECISIONS 1-5:
1 (plan-doc scope): acceptable.
2 (synthetic literal scope): acceptable; it resolves the spec's own contradiction.
3 (R5 threshold): not acceptable, see finding 1.
4 (image policy): acceptable, but extension-only (finding 2).
5 (directory matching): acceptable; case-sensitive identifiers cause finding 8.
N/A: engine safety, design fidelity, game failure paths and the nickname hash scan. The package has no game or runtime code. Ownership: only owned paths are touched, commit trailers are correct, and no frozen contracts exist yet.
```
