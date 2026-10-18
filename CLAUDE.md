# Freelancer Carrier & Endgame Mod: project rules

This repo is built **autonomously** by an orchestrator session plus parallel agents, while Adam is away. These rules extend the global `~/.claude/CLAUDE.md`. Where they conflict, `docs/plan/AUTONOMY.md` wins, but only for this build.

## If you are the orchestrator

- Read `docs/plan/BUILD_PLAN.md`, `docs/plan/CONVENTIONS.md`, `docs/plan/AUTONOMY.md` and `state/BUILD_STATE.md`, then continue from the ledger's "Next actions".
- You are pre-authorized (AUTONOMY §1); never stop to ask Adam.
- Run `date -Is > /home/user/freelancer/carrier-mod/local/heartbeat` at the start and end of every turn.
- Keep your context lean:
  - Delegate reading and building to agents.
  - Read final reports, not transcripts.
  - Keep the ledger as your memory.

## If you are a package agent or reviewer

- Your brief (`state/briefs/<ID>.md`) is your contract. Read it, `docs/plan/CONVENTIONS.md` (which wins over any spec text), and every file in its context pack before writing code.
- You run in a git worktree, so gitignored paths (`local/`, `vendor/`, `.venv/`) don't exist there. Always use the absolute paths from CONVENTIONS §1 (`$FLMOD_LOCAL`, `$FLMOD_VENDOR`, `$FLMOD_VENV`, `$FLMOD_TESTRUNS`, `$FLMOD_LOCKS`, …). They are exported by `tools/env.sh`.
- Only edit paths your brief says you own. If you need a change elsewhere (e.g. a frozen contract), stop and report it as an open question.
- Work in your git worktree on branch `wp/<ID>`, and commit often with clear messages. Never merge into `main`; the orchestrator merges.
- Tag every claim in your report VERIFIED (with evidence) or UNVERIFIED. Never present a guess as fact.
- On any bug, write at least 10 distinct hypotheses before choosing an experiment.
- Finish with the report format in your brief.

## Hard guardrails (everyone)

1. **Wine.** Run `source /home/user/freelancer/carrier-mod/tools/env.sh` in any shell that runs wine tools.
   - It puts guards first on PATH, and they refuse any `WINEPREFIX` other than `prefix-dev*`, `prefix-lane*` or `prefix-carrier`.
   - **Never touch `/home/user/freelancer/prefix`, `play.sh` or `~/.wine`.**
   - Kill only your own lane: `WINEPREFIX=<lane> wineserver -k`. Never `pkill wine` or `pkill -f Freelancer`.
2. **Game runs go through the harness on a locked lane** (`harness/lane.sh acquire|release`). Synthetic input and window focus are allowed only while holding the `input` lock.
3. **Engine safety.**
   - Every game call runs on the game's main thread.
   - Spawns, destroys, ForceLand and relocates triggered inside engine callbacks are deferred one tick.
   - Every spawn is validated (archetype, loadout with an engine, faction, pilot, base) before the call.
   - Cross the Common.dll boundary only with `st6::` containers.
   - MSVC ABI only (clang-cl `/MD`); never mingw for module code.
4. **Data hygiene.**
   - Data is additive and generated at deploy time from the local install.
   - Never overwrite HDE files wholesale, never edit HDE's resource DLLs, and never rename a nickname that has shipped.
5. **The repo is public.** Never commit game files or extracts, decompiled code, other mods' content, `local/` content, secrets, or personal infrastructure details. `tools/check_public.py` must pass.
6. **Network.** The mod talks only to `127.0.0.1`. The sidecar talks only to `127.0.0.1`, plus the Claude Code CLI it launches for the brain, which uses Adam's subscription. The brain gets no tools, MCP or connectors. Never import aria code.
7. **Tests.**
   - Never trigger real outbound side effects.
   - Mock at the defining module.
   - Use temporary dirs and prefixes, never the play install or saves.
8. **Logs.** Use the module logger (`[carrier] <subsystem>: …`). The devbridge emits `HARNESS key=value …` lines that tests assert on.

## Key paths

| What | Path |
|---|---|
| Plan | `docs/plan/` (BUILD_PLAN, DESIGN, AUTONOMY, TESTING, packages/) |
| Ledger and state | `state/` (BUILD_STATE.md, DECISIONS.md, ENGINE_FACTS.md, DEGRADED.md, gates/, briefs/) |
| Research (read-only) | `/home/user/freelancer/carrier-mod/local/research/` |
| Reference source (read-only) | `/home/user/freelancer/refs/` |
| Play install (**do not touch**) | `/home/user/freelancer/prefix` |
| Toolchain | `/usr/lib/llvm/22/bin/{clang-cl,lld-link,llvm-rc}`; MSVC SDK via xwin under `~/opt/xwin` (P0-TOOLCHAIN) |
| Wine binaries | `/usr/lib/wine-proton-11.0.1/bin/` (use through `tools/env.sh`) |
