# Brief: P0-TRACK-A Platform bake-off, Track A (FLUF on HDE minus forbidden DLLs) (attempt 1)

You are a package agent in an autonomous build of a Freelancer (2003) single-player mod. Adam, the owner, is away and nobody will answer questions in real time. The orchestrator can answer via message when you report a blocking question, but prefer the decision policy (`docs/plan/AUTONOMY.md` §3) and record what you decide.

## Read first, in this order

1. `/home/user/freelancer/carrier-mod/CLAUDE.md`: guardrails (mandatory).
1b. `/home/user/freelancer/carrier-mod/docs/plan/CONVENTIONS.md`: canonical names, paths, devbridge verbs, scenario schema, fixtures, locks, CI. It wins over your spec wherever they differ.
2. `/home/user/freelancer/carrier-mod/docs/plan/packages/P0-TRACK-A.md`: your full package spec.
3. Every file in that spec's **Context pack**.
4. `/home/user/freelancer/carrier-mod/state/ENGINE_FACTS.md`: facts proven in game. These override the research where they differ.
5. The **gate addendum** below.

## Working rules

- **Paths and tools.** `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use only absolute paths for shared things: `$FLMOD_LOCAL`, `$FLMOD_RESEARCH`, `$FLMOD_REFS`, `$FLMOD_VENDOR`, `$FLMOD_VENV` (Python: `$FLMOD_VENV/bin/python -I`), `$FLMOD_TESTRUNS` (all run output), `$FLMOD_LOCKS`. Gitignored dirs don't exist inside your worktree.
- **Workspace.** You are in a git worktree. Create the branch `wp/P0-TRACK-A` if it doesn't exist, and commit there often. If continuing a previous attempt, check out `wp/P0-TRACK-A` at `<sha>` and read `spikes|src/.../NOTES.md` first.
- **Ownership.** Only edit what your spec owns. To change a frozen contract or another package's code, stop and put it in your report as a **blocking question**, with a proposed patch.
- **Game runs.**
  - Use `harness/lane.sh acquire` to get a lane (an exclusive prefix plus a window slot).
  - Use `harness/run.sh` / `harness/scenario.sh` to deploy and run; always `harness/lane.sh release`.
  - Synthetic input or window focus requires `harness/lane.sh acquire --input`.
  - `source tools/env.sh` before any wine command.
- **Deferred scenarios.** If an in-game scenario truly needs an unmerged sibling package from your wave, mark it `DEFERRED(P0-TRACK-A)`, with the reason, and still write it (CONVENTIONS §8). Never defer a scenario that can run.
- **Testing is part of the job.** Write the host tests and in-game scenarios listed in your spec, run them, and attach evidence: log excerpts, `HARNESS` lines, screenshot paths and vision-check verdicts.
  - A feature without passing evidence is not done.
  - Report a skipped test as skipped, with the reason.
- **Bugs.** List at least 10 distinct hypotheses before choosing an experiment, and record them in `NOTES.md` in your owned directory.
- **Claims.** Tag each one VERIFIED (with evidence) or UNVERIFIED.
- **Public repo.** Never commit game files or extracts, decompiled code, other mods' content, `local/` content or secrets. Run `tools/check_public.py` before your final commit.
- **Commits.** End each commit message with the attribution trailer given in the gate addendum.

## Final report (your last message; keep it under 800 words)

```
PACKAGE: P0-TRACK-A   ATTEMPT: 1   RESULT: DONE | PARTIAL | BLOCKED
BRANCH: wp/P0-TRACK-A @ <sha>
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
- **Track:** this IS the bake-off; the track is decided at G0a from your RESULTS.md and the sibling's.
- **Main at spawn:** `{{MAIN_SHA}}` (P0-REPO, P0-TOOLCHAIN, P0-HARNESS, P0-DATATOOLS and P0-SIDECAR merged; check `git log --oneline -8 main`). Create `wp/P0-TRACK-A` from main in your worktree.
- **Base plan:** undecided (S-BASE / G0b). **Frozen contracts:** none yet; `docs/plan/CONVENTIONS.md` is binding.
- **Parallel sibling:** P0-TRACK-B runs at the same time in its own worktree. The common header `spike_platform.hpp` and `harness/scenarios/bakeoff_vmstat.yaml` must be byte-identical between you; whoever commits the yaml first, the other copies it verbatim (the orchestrator checks both at merge).
- **Lanes:** `LANES=4` on DXVK (measured by P0-HARNESS: ~195 fps each with 4 games). You share them with P0-TRACK-B: hold **at most 2 lanes at a time**, release promptly, and use `--perf` only for timing-sensitive measurements. `--input` for any focus or synthetic input (always through the harness input gate: PID, `_NET_WM_DESKTOP`, geometry; never `xdotool key --window`; never switch desktops; D104).
- **Renderer:** `FLMOD_RENDERER=auto` = DXVK (GPU healthy since the 2026-10-18 reboot). gamescope is banned (D103). GPU watch after any crash or kill: `nvidia-smi -q | grep 'Recovery Action'`; if not `None`, append to `$FLMOD_LOCAL/gpu-fault.log`, stop DXVK runs, switch to `FLMOD_RENDERER=wined3d-sw` (`LANES_SW=2`), and put it at the top of your report. Quit games gracefully (devbridge `quit`) before any `wineserver -k` when the game responds.
- **Harness:** read `harness/README.md` and `harness/devbridge/PROTOCOL.md` first. Fixtures exist for `HARNESS_endgame_eagle`, `HARNESS_endgame_eagle_space`, `HARNESS_endgame_crete`, `HARNESS_ew06_space`, `HARNESS_lvl1_rich_fp9`, `HARNESS_new_story` (`harness/fixtures/specs/`). You don't own `harness/`: propose fixes (with a patch) in your report.
- **Harness facts (P0-HARNESS fix round 1, harness/NOTES.md N11–N19):**
  - Devbridge wire format per CONVENTIONS §4 and D111: acks are `ack id= ok= [err="…"] [verb=] [results…]`; while a command is pending > 5 s the core emits `ev=pending id= verb= elapsed_s=` every 5 s. Your spike DLL's verbs go through the same core, so long verbs (e.g. the 60-minute soak loop, `perf <s>`) are safe from false HANGs; give a per-command budget with the `[timeout_s=N]` prefix when needed. `ev=hb` every 10 s lets the runner detect a frozen game even when nothing is pending: keep it running in your DLL.
  - Lanes run DXVK with `d3d9.maxFrameRate = 60` (DXVK 3.1.1 has no `DXVK_FRAME_RATE`). Renderer classes never mix on the host. `state` reports the in-game rank (`pub::Player::GetRank`).
  - Crash triage: `bt all` text backtraces work; attaching winedbg for a minidump kills the WoW64 game (N18), so the backtrace is the primary artifact.
  - Deploy writes our `dacom.ini [Libraries]` entry through the `harness.dacom` fltools.patch unit (D107) and the verdict fails with `dll_not_loaded` if the DLL didn't load.
- **Toolchain (P0-TOOLCHAIN, D110):**
  - Run `toolchain/ehprobe.sh --crt both` on your track as part of your acceptance, and test the in-game EH items in `toolchain/ABI.md` §6.8 where your hooks make that possible.
  - Every hook body follows the ABI.md §6.7 template (work under `flmod_seh_guard`, try/catch inside the guarded body, `catch(...)` logged as "possibly SEH"). Rules (a)/(b) in §6.1–6.2 are coding rules, not optional.
  - Keep Wine's builtin MSVC runtime by default. If an in-game run shows the "exception leaving a catch into a try in the same function" signature in foreign frames (FLUF/HDE), the fallback is the app-local native redist from `$FLMOD_VENDOR/msvc-redist/x86` (all nine DLLs into the lane's EXE dir; the prefix's DllOverrides switch it process-wide); report which you used.
  - A stray CRT DLL in the EXE dir silently switches the runtime: check for `msvcp1?0*`, `vcruntime140*`, `ucrtbase*`, `concrt140*` in your lane's EXE dir before trusting a result.
- **Public safety:** `tools/check_public.py` and the git hooks are on main now; never `--no-verify`. Cite reference sources (FLUF, FLHook, adoxa, the decompilation) in `spikes/track_a/NOTES.md`, never in code comments (D106). Don't copy AGPL/GPL code verbatim.
- **Commit attribution trailer** (end every commit message with exactly these two lines):
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FbAaS1xfbG3DHutbmesKK5
  ```
- **Done means:** `spikes/track_a/RESULTS.md` complete and honest (13 items, absolute evidence paths, every PASS backed by a `verdict.json`), the platform lib and scenarios committed on `wp/P0-TRACK-A`, and your final message in the report format above, with the RESULTS table inline. Do not merge into `main` and do not push.
- **Package-specific (Track A):**
  - **Blocker to solve first (item 2, a hard-veto item):** with FLUF core loaded, **any `.fl` file in the save folder** crashes HDE ~2 s after the main menu (`dacom.dll+0x5e6c`, a stricmp), even the game's own `newplayer.fl`; the same install without FLUF.dll is fine. P0-HARNESS's triage (15 runs) is in `harness/NOTES.md` N7 and `state/reports/P0-HARNESS-a1b.md`. Apply the ten-hypotheses rule (record it in `spikes/track_a/NOTES.md`). Candidate directions, not conclusions: FLUF's save-list/CharacterSelect handling, a FLUF core patch that reads save headers, the removed HDE DLLs (FLSharp's `save_crash_fix` is gone on A), the commented-out `callsign.dll` line, nightly vs stable 2.0 (the spec's fallback: "repeat the failing items on stable 2.0 and report both"), LAA/stripped builds. If it can't be fixed within the profile rules, report item 2 FAIL with the evidence: G0a then applies the hard veto honestly.
  - **Display mode:** Track A must use `--display vdesk` (in x11 mode FLUF sizes the game to the whole screen and ignores `windowsize`; harness N2). The vdesk window sometimes opens fullscreen when several lanes start at once (N19, cause unknown); the runner detects it and re-places the window. If it recurs in your runs, note how often.
  - **Frame function:** on Track A, `0x5B2890` already starts with a jump (FLUF's own hook), so don't detour it; use FLUF's tick facilities (harness devbridge log `…-064006-…-E1`).
  - **Toolchain items for A:** confirm FLUF's non-CRT imports (d3dcompiler_47, opengl32, imm32, bcrypt, crypt32, …) resolve in the lane prefix (`toolchain/check_imports.py` covers only our binaries); a binary scan of FLUF.dll's catch funclets for rethrow / `_CxxThrowException` calls would settle its exposure to EH rule (c) (P0-TOOLCHAIN r2/r3 notes).
  - **Address space (item 12):** measure early (spec Task 3); FLUF nightly is ~404 MiB of image and Freelancer.exe isn't LAA.
