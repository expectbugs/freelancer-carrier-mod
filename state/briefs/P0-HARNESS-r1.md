# Review brief: P0-HARNESS Dev baselines, lanes, run/deploy, fixtures, devbridge core, crash triage (round 1)

You are an independent reviewer in an autonomous build. Be adversarial: your job is to find what is wrong, missing, untested or risky before it reaches `main`. **You do not fix code.** You report findings; the author fixes them.

Every later package runs the game through this harness, and Adam's desktop and play install share the machine with it. Safety bugs here are BLOCKERs.

## Inputs

- **Package spec:** `docs/plan/packages/P0-HARNESS.md`. **Brief:** `state/briefs/P0-HARNESS.md`, plus the resume files `state/briefs/RESUME-2026-10-18.md` and `state/briefs/P0-HARNESS-resume.md`.
- **Author's reports:** `state/reports/P0-HARNESS-a1.md` (session 1, PARTIAL) and `state/reports/P0-HARNESS-a1b.md` (session 2, PARTIAL, final). Experiment record: `harness/NOTES.md` on the branch; overview `harness/README.md`.
- **Decisions:** D103–D107 and **D109** in `state/DECISIONS.md`. D109 carries two items out of this package: the Track A save-load crash (to P0-TRACK-A) and the post-campaign gate/bar check (to W1-HARNESS once a `target` verb exists). Do not fail the package for those two items; do check that the evidence and hand-off notes for them are accurate and sufficient.
- **Branch:** `wp/P0-HARNESS` @ `181ebcc`. Diff: `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-HARNESS`.
- **Standards:** `CLAUDE.md` guardrails (1 Wine, 2 lanes/input, 5 public, 7 tests), `docs/plan/CONVENTIONS.md` §1, §4 devbridge, §5 run output, §6 fixtures, §7 locks/lanes/ports, §14 ownership, §15 Wine safety (CONVENTIONS wins over the spec), `docs/plan/TESTING.md`, `state/ENGINE_FACTS.md`.

## Do all of these

1. **Requirements.** For every `REQ-P0-HARNESS-n` (18), find the code and the test or evidence that covers it. Mark each covered, partial or missing.
2. **Re-run the tests yourself:** `harness/selftest.sh` (on lanes you acquire), `test_guards.sh`, `test_lanes.sh`, `test_display_awake.sh` (ONLY with `DISPLAY_AWAKE_STATE_DIR=<tmpdir>`; never touch the live inhibitor), pytest, the devbridge doctest, `baseline.sh verify A` and `verify B`. Compare with the author's evidence; flag anything you can't reproduce.
3. **Safety audit (BLOCKER class):**
   - Play prefix: nothing in the harness can write to `/home/user/freelancer/prefix`, `play.sh` or `~/.wine`; clones only while `tools/play_prefix_busy.sh` says idle; run `tools/play_prefix_manifest.sh verify` (read-only) before and after your review.
   - Wine: every wine/wineserver/winedbg invocation goes through the guards with an allowed `WINEPREFIX`; kills are scoped (`WINEPREFIX=<lane> wineserver -k`), never `pkill wine` / `pkill -f Freelancer`.
   - Input (D104/D105): every synthetic input is gated on the lane window's PID, `_NET_WM_DESKTOP`, geometry and pointer target, under the `input` lock; XTEST to the focused window only (never `xdotool key --window`); no desktop switching, no moving or raising windows on other desktops. Try to make the gate send input to a wrong window: a second lane's window, a non-game window with the same title, a window on another desktop, a vdesk window not owned by the lane's explorer.exe. It must refuse. Do this with harmless targets you create yourself (e.g. an `xmessage` window you then close) and never with Adam's applications.
   - Locks: `lane.sh acquire|release|reap`, `--input`, `--perf`; stale-lock recovery after SIGKILL; two concurrent acquirers never get the same lane.
   - GPU (D103): gamescope absent from the harness; the renderer switch is recorded per run; `LANES=4` on DXVK and `LANES_SW=2` justified by evidence (NOTES N11, N14).
4. **Verdict logic.** `verdict.py`/`triage.py`: can a crash, hang, spew ERROR outside the allow-list, or runner exception ever yield PASS? Judge the "≥ 25 % of a core = slow start-up, not hang" rule and the HANG-vs-CRASH attribution. Feed synthetic logs to prove your claims.
5. **Devbridge core and protocol** (`harness/devbridge/PROTOCOL.md`): is it exactly what CONVENTIONS §4 says (line formats, `ev=` not `evt=`, ack shape, `va_free_mb` keys)? Is it complete enough to be frozen into `docs/spec/devbridge.md` by ARCH-0? Is the DLL-side code engine-safe (main thread only, no blocking I/O on the game thread, null checks)?
6. **Fixtures** (`gen_fixture.py`, CONVENTIONS §6): system, base and position always explicit; `HARNESS_<name>` naming; no game data committed (fixtures generated at run time from the local install, per §12).
7. **Spew allow-lists:** not so broad that a real new ERROR would pass; per track and renderer.
8. **Public safety:** `$FLMOD_VENV/bin/python -I $FLMOD_LOCAL/snapshots/check_public.py --tree <your checkout>` and `--commits=main..wp/P0-HARNESS` (expected: only intermediate a5bafe5 fails per D106; the tip must be clean).
9. **Orchestrator-owned files** (`tools/env.sh`, `tools/bin/`, `tools/display-awake.sh`, `tools/watchdog.sh`): the branch must not modify them. Check `git diff main...wp/P0-HARNESS -- tools/`.

## Verdict (your last message)

```
REVIEW: P0-HARNESS ROUND 1   VERDICT: PASS | CHANGES_REQUIRED
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the selftest reproduced (with the two D109 items BLOCKED as expected).

## Orchestrator notes

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use `$FLMOD_VENV/bin/python -I` for Python.
- The branch is checked out in the author's worktree; inspect it detached in yours (`git checkout --detach wp/P0-HARNESS`). Run the harness from your checkout; lanes and locks are shared under `$FLMOD_LOCKS`, so always go through `lane.sh acquire` and release what you take.
- Other agents may run Wine in parallel (P0-TOOLCHAIN's reviewer uses its own `prefix-dev-review-toolchain`). Never touch windows, prefixes or locks that aren't yours.
- GPU watch (RESUME-2026-10-18.md): after any crash or kill, `nvidia-smi -q | grep 'Recovery Action'`; if not `None`, log to `$FLMOD_LOCAL/gpu-fault.log`, stop DXVK runs, switch to `FLMOD_RENDERER=wined3d-sw`, and say so at the top of your verdict.
- You never edit the branch, `main`, `state/`, `local/` (except your run dirs) or the main checkout. Scratch output goes under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-HARNESS-r1/`. Delete any prefix clones you create (`prefix-dev-review-harness*`).
- Commits (you should make none): if you must, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FbAaS1xfbG3DHutbmesKK5`.
