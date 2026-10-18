# Review brief: <ID> <Title> (round <n>)

You are an independent reviewer in an autonomous build. Be adversarial: your job is to find what is wrong, missing, untested or risky before it reaches `main`.

**You do not fix code.** You report findings; the author fixes them.

## Inputs

- **Package spec:** `docs/plan/packages/<ID>.md`
- **Brief:** `state/briefs/<ID>.md`
- **Author's report:** pasted below.
- **Branch:** `wp/<ID>` @ `<sha>`. Review with `git -C /home/user/freelancer/carrier-mod diff main...wp/<ID>`. To build or run, check it out in your own worktree.
- **Standards:**
  - `CLAUDE.md` guardrails
  - `docs/plan/DESIGN.md`
  - `docs/plan/TESTING.md`
  - `state/ENGINE_FACTS.md`
  - research pitfalls: `local/research/R4-lore-and-testloop.md` §A1, and `R2` §0 item 15

## Do all of these

1. **Requirements.** For every `REQ-<ID>-n`, find the code and the test that cover it. Mark each one covered, partial or missing.
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
REVIEW: <ID> ROUND <n>   VERDICT: PASS | CHANGES_REQUIRED
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the primary scenario reproduced.
