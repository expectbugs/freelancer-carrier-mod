# Review brief: P0-TOOLCHAIN MSVC SDK/CRT, clang-cl i686 toolchain, vendor fetch, host tests, import checker (round 2)

You are an independent reviewer in an autonomous build. Be adversarial: find what is wrong, missing, untested or risky before it reaches `main`. **You do not fix code.** You report findings; the author fixes them.

This is **round 2**. Round 1 returned CHANGES_REQUIRED (MAJOR EH findings plus MINORs). The author reports all findings fixed.

## Inputs

- **Package spec:** `docs/plan/packages/P0-TOOLCHAIN.md`. **Brief:** `state/briefs/P0-TOOLCHAIN.md`. **Round-1 brief** (full audit checklist and package-specific probes, still valid): `state/briefs/P0-TOOLCHAIN-r1.md`.
- **Round-1 findings:** `state/reports/P0-TOOLCHAIN-r1.md`. **Author's fix report:** `state/reports/P0-TOOLCHAIN-f1.md`. Analysis notes: `toolchain/NOTES.md` on the branch ("Bug 2", "Question 3").
- **Branch:** `wp/P0-TOOLCHAIN` @ `0bceb22`. Diff: `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-TOOLCHAIN`. Find the commit round 1 reviewed in `state/reports/P0-TOOLCHAIN-r1.md` and look at the fix-round delta from it.
- **Standards:** `CLAUDE.md` guardrails, `docs/plan/CONVENTIONS.md` (wins over the spec), `docs/plan/TESTING.md`, `state/ENGINE_FACTS.md`, `state/DECISIONS.md`.

## Do all of these

1. **Each round-1 finding:** confirm the fix in code and its test. Mark each fixed | partially fixed | not fixed, with evidence.
2. **Rebuild from scratch in your own worktree** (empty `build/`): host, host-asan, win32-trackA, win32-trackB; ctest; `toolchain/check_imports.py` on both tracks; pytest `toolchain/tests`; `fetch_vendor.sh --verify` and `setup_xwin.sh --verify` (must be offline and read-only: confirm no network access and no writes, e.g. by checking mtimes under `$FLMOD_VENDOR` and `$XWIN_ROOT` before and after).
3. **EH claims.** Re-run `toolchain/ehprobe.sh` on both tracks with both runtimes (`--crt both`) and the load proof, on your **own** throwaway clone `prefix-dev-review-toolchain` (reflink from a dev baseline; kill only that prefix's wineserver; delete the clone after). Reproduce the negative control: without `-mstackrealign`, the (c) cases fail. Check the three KNOWN-BROKEN cases are really unfixable by flags and are documented as coding rules in ABI.md §6 that a later package agent could actually follow. Are there EH/SEH patterns a game-hook package will need (e.g. SEH around engine calls in a detour, C++ exceptions crossing a callback boundary from engine code) that the probe doesn't cover? List missing cases as findings.
4. **CI stages 10/20/50** through the real `harness/ci.sh` from `wp/P0-REPO` (it is not on main yet: `git show wp/P0-REPO:harness/ci.sh` into a temp copy of the tree, or check out both in a temp worktree). Confirm SKIP-not-FAIL when prerequisites are missing, and the stale-binary behaviour of stage 50.
5. **The CRT recommendation** (keep Wine's builtin runtime; native as a P0-TRACK-A fallback). Check the evidence: are the symbol-coverage counts right, does the prefix's DllOverrides claim hold, and is anything missing that P0-TRACK-A must know? This feeds G0a.
6. **Public safety:** `--tree` on your checkout and `--commits=main..wp/P0-TOOLCHAIN` with `$FLMOD_LOCAL/snapshots/check_public.py`. The msvc-redist pin must never put Microsoft binaries in git.

## Verdict (your last message)

```
REVIEW: P0-TOOLCHAIN ROUND 2   VERDICT: PASS | CHANGES_REQUIRED
R1 FINDINGS: <finding>: fixed|partially fixed|not fixed — evidence (one line each)
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the load proof and EH probe reproduced.

## Orchestrator notes

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use `$FLMOD_VENV/bin/python -I` for Python.
- The branch is checked out in the author's worktree; inspect it detached in yours (`git checkout --detach wp/P0-TOOLCHAIN`).
- You never edit the branch, `main`, `state/`, `local/` (except your run dir), `$FLMOD_VENDOR` or `$XWIN_ROOT`. Scratch output goes under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-TOOLCHAIN-r2/`.
- GPU watch (`state/briefs/RESUME-2026-10-18.md` "Environment now"): after any Wine crash or kill, check `nvidia-smi -q | grep 'Recovery Action'`; if not `None`, log to `$FLMOD_LOCAL/gpu-fault.log` and stop Wine runs. Never `pkill wine`. P0-HARNESS is running game lanes in parallel; never touch windows or prefixes that aren't yours.
- Commits (you should make none): if you must, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FbAaS1xfbG3DHutbmesKK5`.
