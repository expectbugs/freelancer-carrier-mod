# Brief: P0-TOOLCHAIN MSVC-ABI cross toolchain, vendor pins, host test build, import checker (attempt 1)

You are a package agent in an autonomous build of a Freelancer (2003) single-player mod. Adam, the owner, is away and nobody will answer questions in real time. The orchestrator can answer via message when you report a blocking question, but prefer the decision policy (`docs/plan/AUTONOMY.md` §3) and record what you decide.

## Read first, in this order

1. `/home/user/freelancer/carrier-mod/CLAUDE.md`: guardrails (mandatory).
1b. `/home/user/freelancer/carrier-mod/docs/plan/CONVENTIONS.md`: canonical names, paths, devbridge verbs, scenario schema, fixtures, locks, CI. It wins over your spec wherever they differ.
2. `/home/user/freelancer/carrier-mod/docs/plan/packages/P0-TOOLCHAIN.md`: your full package spec.
3. Every file in that spec's **Context pack**.
4. `/home/user/freelancer/carrier-mod/state/ENGINE_FACTS.md`: facts proven in game. These override the research where they differ.
5. The **gate addendum** below.

## Working rules

- **Paths and tools.** `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use only absolute paths for shared things: `$FLMOD_LOCAL`, `$FLMOD_RESEARCH`, `$FLMOD_REFS`, `$FLMOD_VENDOR`, `$FLMOD_VENV` (Python: `$FLMOD_VENV/bin/python -I`), `$FLMOD_TESTRUNS` (all run output), `$FLMOD_LOCKS`. Gitignored dirs don't exist inside your worktree.
- **Workspace.** You are in a git worktree. Create the branch `wp/P0-TOOLCHAIN` if it doesn't exist, and commit there often. If continuing a previous attempt, check out `wp/P0-TOOLCHAIN` at `<sha>` and read `spikes|src/.../NOTES.md` first.
- **Ownership.** Only edit what your spec owns. To change a frozen contract or another package's code, stop and put it in your report as a **blocking question**, with a proposed patch.
- **Game runs.**
  - Use `harness/lane.sh acquire` to get a lane (an exclusive prefix plus a window slot).
  - Use `harness/run.sh` / `harness/scenario.sh` to deploy and run; always `harness/lane.sh release`.
  - Synthetic input or window focus requires `harness/lane.sh acquire --input`.
  - `source tools/env.sh` before any wine command.
- **Deferred scenarios.** If an in-game scenario truly needs an unmerged sibling package from your wave, mark it `DEFERRED(P0-TOOLCHAIN)`, with the reason, and still write it (CONVENTIONS §8). Never defer a scenario that can run.
- **Testing is part of the job.** Write the host tests and in-game scenarios listed in your spec, run them, and attach evidence: log excerpts, `HARNESS` lines, screenshot paths and vision-check verdicts.
  - A feature without passing evidence is not done.
  - Report a skipped test as skipped, with the reason.
- **Bugs.** List at least 10 distinct hypotheses before choosing an experiment, and record them in `NOTES.md` in your owned directory.
- **Claims.** Tag each one VERIFIED (with evidence) or UNVERIFIED.
- **Public repo.** Never commit game files or extracts, decompiled code, other mods' content, `local/` content or secrets. Run `tools/check_public.py` before your final commit.
- **Commits.** End each commit message with the attribution trailer given in the gate addendum.

## Final report (your last message; keep it under 800 words)

```
PACKAGE: P0-TOOLCHAIN   ATTEMPT: 1   RESULT: DONE | PARTIAL | BLOCKED
BRANCH: wp/P0-TOOLCHAIN @ <sha>
SUMMARY: …
FILES: …
TESTS: <name> — PASS|FAIL|SKIP — evidence path
DECISIONS: …          (list them here; the orchestrator copies them into state/DECISIONS.md)
ENGINE FACTS LEARNED: … (VERIFIED with evidence path)
OPEN QUESTIONS / BLOCKERS: …
KNOWN ISSUES: …
```

## Gate addendum (filled by the orchestrator)

- **Attempt:** 1 (no previous attempt).
- **Track:** undecided — Phase 0, before Gate 0a. Platform contract `src/contracts/platform.hpp` does not exist yet (ARCH-0 freezes it after G0b).
- **Base plan:** undecided (S-BASE / G0b).
- **Frozen contracts to use:** none yet. `docs/plan/CONVENTIONS.md` is binding and wins over your spec.
- **Relevant ENGINE_FACTS IDs:** none proven yet; read `state/ENGINE_FACTS.md` for the seed list. Research facts tagged VERIFIED in the R-files are your best evidence.
- **Parallel siblings (same phase, separate worktrees, running now):** P0-REPO, P0-TOOLCHAIN, P0-HARNESS, P0-DATATOOLS, P0-SIDECAR. Stay strictly inside your owned paths; the orchestrator merges in an order it chooses and resolves conflicts.
- **Shared Python venv** `$FLMOD_VENV` exists (Python 3.13, pytest 9.1.1, pyyaml, jsonschema). Several agents share it, so serialize installs: `flock $FLMOD_LOCKS/venv.lock $FLMOD_VENV/bin/pip install <pkg>`. If you add a package, append it to `requirements-dev.txt` on your branch (create the file if absent; append-only; the orchestrator unions it at merge).
- **Public-safety hook:** P0-REPO is writing `tools/check_public.py` and the pre-commit hook right now; they are not on `main` yet. Until they land, self-check before each commit: no game files/extracts, no `local/` content, no decompiled code, no secrets, no personal literals (emails, IPs, hostnames). Your diff will be scanned with the real checker at review and merge.
- **Play prefix:** clone only with `cp -a --reflink=always` and only while `tools/play_prefix_busy.sh` exits 1. Never write to it. `tools/play_prefix_manifest.sh verify` is run by the orchestrator at gates; any change to the play install halts the build.
- **Display:** `:0` keep-awake is ON (orchestrator ran `tools/display-awake.sh start`; screensaver inhibited). Do not run `display-awake.sh start|stop` against the live state; tests must set `DISPLAY_AWAKE_STATE_DIR` to a temp dir.
- **Commit attribution trailer** (end every commit message with exactly these two lines):
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01RmcFZB7uCdtYAePWANm86Q
  ```
- **Done means:** your branch `wp/P0-TOOLCHAIN` has every REQ implemented with its acceptance evidence, committed, and your final message is the report format above (≤ 800 words). Do not merge into `main` and do not push.
- **Lane(s) assigned:** none from the harness (P0-HARNESS is building lanes concurrently). Your spec's throwaway clone `prefix-dev-toolchain` is approved; kill only it (`WINEPREFIX=/home/user/freelancer/prefix-dev-toolchain wineserver -k`) and delete it when done.
- **Package-specific notes:**
  - You are the **only writer** of `$FLMOD_VENDOR` (shared by every worktree) and of `$XWIN_ROOT` (`/home/user/opt/xwin`). Other packages read them after you merge, so make the fetch script idempotent and record exact pins (URLs + SHA-256) in `toolchain/`.
  - sudo is granted only for `emerge` package installs if a fallback needs one (e.g. msitools). List every sudo command verbatim in your report.
  - P0-TRACK-A and P0-TRACK-B start as soon as you and P0-HARNESS merge; your toolchain file, CMake presets and the hello_a/hello_b samples are their foundation, so document usage in `toolchain/README.md` (build commands, preset names, how a spike adds a target).
