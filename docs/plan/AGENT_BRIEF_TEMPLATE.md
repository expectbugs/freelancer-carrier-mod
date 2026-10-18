# Brief: <ID> <Title> (attempt <n>)

You are a package agent in an autonomous build of a Freelancer (2003) single-player mod. Adam, the owner, is away and nobody will answer questions in real time. The orchestrator can answer via message when you report a blocking question, but prefer the decision policy (`docs/plan/AUTONOMY.md` §3) and record what you decide.

## Read first, in this order

1. `/home/user/freelancer/carrier-mod/CLAUDE.md`: guardrails (mandatory).
1b. `/home/user/freelancer/carrier-mod/docs/plan/CONVENTIONS.md`: canonical names, paths, devbridge verbs, scenario schema, fixtures, locks, CI. It wins over your spec wherever they differ.
2. `/home/user/freelancer/carrier-mod/docs/plan/packages/<ID>.md`: your full package spec.
3. Every file in that spec's **Context pack**.
4. `/home/user/freelancer/carrier-mod/state/ENGINE_FACTS.md`: facts proven in game. These override the research where they differ.
5. The **gate addendum** below.

## Working rules

- **Paths and tools.** `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use only absolute paths for shared things: `$FLMOD_LOCAL`, `$FLMOD_RESEARCH`, `$FLMOD_REFS`, `$FLMOD_VENDOR`, `$FLMOD_VENV` (Python: `$FLMOD_VENV/bin/python -I`), `$FLMOD_TESTRUNS` (all run output), `$FLMOD_LOCKS`. Gitignored dirs don't exist inside your worktree.
- **Workspace.** You are in a git worktree. Create the branch `wp/<ID>` if it doesn't exist, and commit there often. If continuing a previous attempt, check out `wp/<ID>` at `<sha>` and read `spikes|src/.../NOTES.md` first.
- **Ownership.** Only edit what your spec owns. To change a frozen contract or another package's code, stop and put it in your report as a **blocking question**, with a proposed patch.
- **Game runs.**
  - Use `harness/lane.sh acquire` to get a lane (an exclusive prefix plus a window slot).
  - Use `harness/run.sh` / `harness/scenario.sh` to deploy and run; always `harness/lane.sh release`.
  - Synthetic input or window focus requires `harness/lane.sh acquire --input`.
  - `source tools/env.sh` before any wine command.
- **Deferred scenarios.** If an in-game scenario truly needs an unmerged sibling package from your wave, mark it `DEFERRED(<ID>)`, with the reason, and still write it (CONVENTIONS §8). Never defer a scenario that can run.
- **Testing is part of the job.** Write the host tests and in-game scenarios listed in your spec, run them, and attach evidence: log excerpts, `HARNESS` lines, screenshot paths and vision-check verdicts.
  - A feature without passing evidence is not done.
  - Report a skipped test as skipped, with the reason.
- **Bugs.** List at least 10 distinct hypotheses before choosing an experiment, and record them in `NOTES.md` in your owned directory.
- **Claims.** Tag each one VERIFIED (with evidence) or UNVERIFIED.
- **Public repo.** Never commit game files or extracts, decompiled code, other mods' content, `local/` content or secrets. Run `tools/check_public.py` before your final commit.
- **Commits.** End each commit message with the attribution trailer given in the gate addendum.

## Final report (your last message; keep it under 800 words)

```
PACKAGE: <ID>   ATTEMPT: <n>   RESULT: DONE | PARTIAL | BLOCKED
BRANCH: wp/<ID> @ <sha>
SUMMARY: …
FILES: …
TESTS: <name> — PASS|FAIL|SKIP — evidence path
DECISIONS: …          (list them here; the orchestrator copies them into state/DECISIONS.md)
ENGINE FACTS LEARNED: … (VERIFIED with evidence path)
OPEN QUESTIONS / BLOCKERS: …
KNOWN ISSUES: …
```

## Gate addendum (filled by the orchestrator)

- **Track:** A (FLUF) | B (own DLL). Platform contract: `src/contracts/platform.hpp`
- **Base plan:** A (re-point) | B (proxy per system)
- **Frozen contracts to use:** …
- **Relevant ENGINE_FACTS IDs:** …
- **Lane(s) assigned:** …
- **Previous attempt notes / reviewer findings:** …
- **Commit attribution trailer:** copy the orchestrator session's attribution lines here, verbatim.
