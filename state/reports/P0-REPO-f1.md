**Fix report: P0-REPO review r1, fix round 1 (resumed after the reboot)**

There was no GPU fault in this session; the package has no game runs. All 12 package-owned findings were fixed at the pre-reboot checkpoint, and the code has not changed since. This session re-ran every check and confirmed F9, which the orchestrator owns. Evidence is in two folders: R0 is `$FLMOD_TESTRUNS/20261018T052428Z-p0-repo-fix1/` (the fix round) and R1 is `$FLMOD_TESTRUNS/20261018T063805Z-p0-repo-resume/` (this session).

| # | What changed | Covering test | Evidence | Status |
|---|---|---|---|---|
| F1 R5 misses real data | New file-wide `R5-fl-data` detector for INI, YAML and JSON forms, ignoring blank, comment and `&gt;` lines | `test_r5_fl_data_rejected_in_any_text_form`, `test_r5_corpus_hde_ini_rejected_in_four_formats`, `test_r5_authored_yaml_catalog_passes` | R0/r5-corpus.txt: 98.8% rejected (96.5% for JSON), 0 of 611 clean files flagged | DONE |
| F2 R1 checked extensions only | Content sniffing (UTF, BINI, PE, RIFF, Ogg and more), archives found by signature, unknown binaries rejected, lossy decode of NUL bytes, UTF-16 without a BOM, base64, `.dfm` | `test_r1_content_signatures_*`, `_unknown_binary_*`, `_utf16_*`, `_base64_*`, `_archives_opened_by_signature_*` | R0/synthetic-smuggle.txt | DONE |
| F3 decomp marker | Loose marker plus the header phrase, applied to all code outside `docs/` | `test_r4_decomp_marker_in_any_code_file`, `test_r4_corpus_decomp_files_rejected_in_src` | R0/realistic-smuggle-with-index.txt (96.7% caught) | DONE |
| F4 hooks / hooksPath | Hooks find the checker from their own real path; `pre-merge-commit` runs the `pre-commit` hook next to it | `test_hooks_with_absolute_hookspath_cover_pre_merge_worktrees` | R0/pytest.log | DONE |
| F5 release symlinks | `--release` rejects symlinks | `test_release_rejects_symlinks` | R0/pytest.log | DONE |
| F6 R2 header list | Any `[Section]` header now counts (more than 20 = reject) | `test_r2_ini_with_more_than_20_section_headers_rejected` | R0/pytest.log | DONE |
| F7 subdirectory / empty scans | Git now runs from the repo top level; an empty or ignored scan exits 2 | `test_staged_from_a_subdirectory_sees_root_files`, `test_empty_scans`, `test_tree_on_git_ignored_dir_is_an_error_not_ok` | R0/pytest.log | DONE |
| F8 missing patterns | Added fine-grained PAT, `gh[pousr]` tokens, the API key with spaces, `*.ts.net`, leading-zero IPs, IPs and emails in paths | `test_r4_tailnet_host_names`, `test_r4_ip_and_email_in_file_paths`, `test_r4_real_secret_shapes_*` | R0/pytest.log | DONE |
| F9 blocklist (orchestrator) | Re-probed: 12 of the reviewer's 13 infra literals are now caught. All 7 research `.md` files copied under `docs/` are rejected | probe script (not committed) | R1/f9-infra-tokens.txt (labels only), R1/f9-v8-research-under-docs.txt | PARTIAL (owned by the orchestrator; see open questions) |
| F10 other mods' content | Local fingerprint index (`--build-index`), rule `R7-refs-copy`, and an escape header that gives a warning | `test_r7_*` | R0/r7-margins.txt, R0/r7-recall.txt | DONE |
| F11 `.claude/` skip | Only `.claude/worktrees/` is skipped now | `test_r3_claude_dir_outside_worktrees_is_scanned` | R0/pytest.log | DONE |
| F12 tags | Annotated tag messages and tagger identity are checked | `test_commits_checks_annotated_tag_messages`, `test_pre_push_hook_vets_history_and_tags` | R0/pytest.log | DONE (release notes are left for W5-SHIP) |
| F13 gzip bomb | Decompression is capped at 5 MB + 1 byte | `test_r1_compression_bomb_is_bounded` | R0/pytest.log | DONE |

```
PACKAGE: P0-REPO   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-REPO @ 32ab66a
SUMMARY: Fix round 1 complete. Resumed at 4e02754 (HEAD matched), re-verified every
  acceptance item, re-probed F9, and committed a session-2 RESUME POINT plus notes for
  the first push (notes only, no code change).
FILES: .githooks/{pre-commit,pre-push,pre-merge-commit}, .github/workflows/public-safety.yml,
  README.md, harness/ci.sh, harness/ci.d/{README.md,NOTES-P0-REPO.md}, tools/check_public.py,
  tests/py/test_check_public.py
TESTS:
  pytest tests/py/test_check_public.py: PASS, 183 passed. VERIFIED R1/pytest.log
  pytest on Python 3.11: PASS at the checkpoint (R0/pytest-py311.log). Not re-run; the code
    is unchanged since 0ecf9b4.
  check_public --tree <worktree>: PASS, 109 files. VERIFIED R1/tree-worktree.log
  check_public --tree <main checkout> (read-only, main @ 21f5f70): PASS, 122 files, including
    docs/plan, state and CLAUDE.md. VERIFIED R1/tree-main-checkout.log
  check_public --commits=main (20 commits): PASS. VERIFIED R1/commits-main-all.log
  check_public --commits=main..HEAD: FAIL in 95db516 and 257ef54 only (the old checker spelled
    the decomp name); the tip is clean. Accepted under D106 (squash-merge).
    VERIFIED R1/commits-main..HEAD.log
  ci.sh --quick and --only public: PASS, exit 0, summary.md written.
    VERIFIED R1/ci-quick.log, R1/ci-only-public.log
  Hook negative tests, 6 MB file, --release .dll, ci.d drop-ins returning 77 and 1: PASS
    (inside the pytest run).
  gh repo view: PUBLIC, empty, description and 6 topics. VERIFIED R1/gh-repo-view.json
  History emails (all refs): only the noreply address. VERIFIED R1/history-emails.txt
  public-safety.yml: parses as YAML. VERIFIED (yaml.safe_load). The Actions run itself is
    UNVERIFIED until the push.
  Snapshot checker (RESUME rule): SKIP. It is a copy of this checker at 4e02754 and the
    checker code has not changed since.
DECISIONS: none new. D101 (absolute hooksPath), D102 and D106 are already recorded.
ENGINE FACTS LEARNED: none (no game runs).
OPEN QUESTIONS / BLOCKERS (orchestrator):
  1. F9: the phone's tailnet hostname (the global CLAUDE.md's 3rd tailnet host) is still not
     in local/public_blocklist.txt. VERIFIED: it occurs in no tracked or untracked file of any
     worktree, so adding it is safe today. Matching is a case-insensitive substring, so it
     would also flag longer words that contain it.
  2. Sibling histories (R1/sibling-commits-scan.txt): DATATOOLS @463eb68 (tools/fltools/hash.py
     and ini.py) and HARNESS @a5bafe5 (harness/fixtures/flhash.py and gen_fixture.py) tips still
     fail R4-decomp. D106 says those citations move out of code. SIDECAR @dbc1c9f and
     TOOLCHAIN @ad47bb5 pass. VERIFIED.
  3. First push: squash-merge wp/P0-REPO, run --tree . and --commits=main, push, then check
     Actions (matrix of Python 3.11 and 3.13). --build-index is not needed for CI: with no
     $FLMOD_LOCAL on Actions, R7 and the blocklist only warn and the generic rules still
     run (VERIFIED in code). The local index exists. No branch protection is set (the spec
     doesn't ask for it). After the merges, the workflow's `pytest tests/py` also runs the
     siblings' tests, which must skip without the game, wine or $FLMOD_REFS (UNVERIFIED).
KNOWN ISSUES:
  - The reviewer's synthetic cases S05 (an authored INI with at most 20 sections in an allowed
    location) and S32 (placeholder email) pass by design.
  - Nested build/ and out/ are not ignored, because the .gitignore patterns are anchored
    (orchestrator-owned).
```

---
Orchestrator follow-up (2026-10-18T01:55): F9 — the remaining tailnet host literal was added to `local/public_blocklist.txt` (gitignored); `--tree .` on main still clean (122 files). The nested build/out item is already fixed on main (`build/`, `out/` are unanchored in main's .gitignore).
