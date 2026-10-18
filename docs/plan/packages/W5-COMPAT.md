# W5-COMPAT: Save compatibility, migrations, uninstall and HDE option variants

- **Type:** impl (+ test)
- **Wave:** 5
- **Depends on:** gate M3 PASSED (`state/gates/M3.md`, written by the orchestrator)
- **Unblocks:** W5-SHIP, F

## Goal

Adam's saves are safe:

- every mod state survives save/load;
- pre-mod saves load into the modded game;
- old mod-state files migrate forward;
- broken files never crash the game;
- he can uninstall the mod without saves crashing in unmodded HDE.

The mod also works under HDE's other install options (Open SP).

## Requirements

- **REQ-W5-COMPAT-1 (D-14.1, D-14.3).** Implement and run the full TESTING §SaveCompat matrix:
  - carrier states × locations × fleet sizes 0/1/3/8/max, where max is the fleet cap **measured by S-BASE** (ENGINE_FACTS), never assumed;
  - UnderAttack while docked aboard (the held fight): reload spawns the solar and the held attackers before launch is allowed (W2-CARRIER-GAME REQ-7, W3-AMBUSH);
  - pre-mod saves (`HARNESS_new_story`, a mid-campaign vanilla save produced by the harness, `HARNESS_osp`);
  - missing, truncated and invalid JSON;
  - schema migrations from **every** released or earlier schema version to current (golden files);
  - the save-delete hook.

  Each cell is an automated scenario tagged `compat`.
- **REQ-W5-COMPAT-2 (D-14.2).** Verify no save can point at a missing base:
  - Scan every save written during the matrix and soaks: `[Player] base` must exist in universe.ini, and if it is a carrier base, its carrier must exist in the paired JSON.
  - Loading such an inconsistent save (constructed by fixture) must recover through W2-CARRIER-GAME REQ-7's recovery: restore a minimal carrier and its solar, or rewrite `base=` in the save and reload, with a toast. **Never `ForceLand` a docked player.** Never crash.
- **REQ-W5-COMPAT-3 (D-14.4).** `tools/uninstall/relocate_saves.py`:
  - For a given save directory (default: the modded profile's save dir; **never** Adam's play prefix unless he runs it explicitly), move the player out of any carrier base to the yard base it was bought at, or the last real base (`lastBaseId` if recorded, else Manhattan `Li01_01_Base`).
  - Strip mod-only `[mPlayer]` keys.
  - Keep `.bak` copies.
  - Idempotent; `--dry-run` supported.
  - Then those saves load in an **unmodded** lane (`prefix-dev-base-B` baseline, no mod deployed) without crash: an automated scenario per relocated save.
- **REQ-W5-COMPAT-4.** HDE option variants:
  - Build a lane variant with HDE **Open SP** (normal and pirate) applied the way the HDE installer does it (`mod_options.iss::EnableOpenSP`: swap `newplayer.fl` Mission and `m13.ini` with `m13_opensp_*`; R3 §7, R5 §6).
  - Verify the campaign-complete detection fires, escalation activates, and yards work.
  - Also: a lane with HDE's alternate save folder setting (`/NewSaveFolder` = `FreelancerHDE`) to confirm our JSON follows the active save path.
- **REQ-W5-COMPAT-5.** Deploy robustness:
  - Re-running the deploy/patchers on an already-modded install is a no-op (idempotence test).
  - Deploying over an HDE install whose resource-DLL list differs (e.g. another DLL appended) detects the correct IDS index (R4 pitfall 9) and fails loudly if the assumption breaks.
- **REQ-W5-COMPAT-6.** Write `docs/COMPATIBILITY.md` (public, short): what's compatible, what isn't (multiplayer is not supported), uninstall steps.

## Context pack (read before writing code)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §6 fixtures, §10, §12, §14)
- `docs/plan/DESIGN.md` §14
- `docs/plan/TESTING.md` §SaveCompat, §Fixtures, §Scenarios
- `state/ENGINE_FACTS.md` (save/load hook facts from S-BASE)
- `docs/spec/persistence.md` (all schema versions and migrations)
- `local/research/R5-sp-architecture.md` §3 (save system, fields, hooks, missing base), §6 (campaign end, Open SP)
- `local/research/R3-game-data.md` §7
- `local/research/R4-lore-and-testloop.md` §A1.4.5 (save crash causes), §A4.6 (HDE installer options mutate files)
- `/home/user/freelancer/refs/freelancer-hd-edition-installer/` (`mod_options.iss`, `silent_options.iss`)

## Ownership

- **Owns:** `tools/uninstall/`, `tests/compat/` (CONVENTIONS §14: not all of `tests/`), `harness/scenarios/compat/`, `harness/fixtures/compat/` (fixture **definitions** only, named `HARNESS_compat_*`, rendered by the W1-HARNESS generator `gen_fixture.py`; CONVENTIONS §6), `docs/COMPATIBILITY.md`
- **Reads:** everything
- **Must not touch:** product code (a bug found ⇒ FIX proposal), `harness/fixtures/gen_fixture.py` itself (propose changes), `state/**`, and Adam's play prefix

## Contract

- **Consumes:** persistence schema, devbridge, harness.
- **Provides:** the compat suite, the uninstall tool, the compatibility doc.

## Tasks

1. Generate the matrix scenarios (data-driven from a YAML table).
2. Fixtures for each schema version, built through the real schema code at historical commits (`git worktree` at the tag or commit), never hand-written.
3. Relocation tool plus its pytest (pure text transforms on `.fl` fixtures).
4. Open-SP and save-folder lane variants.
5. Run everything; file FIX proposals; re-run after fixes.

## Acceptance (all automated)

- Every `compat`-tagged scenario PASSES on the release-candidate commit.
- pytest: `test_relocate_idempotent`, `test_relocate_dry_run`, `test_relocate_keeps_backup`, `test_strip_mod_keys`.
- Unmodded-lane loads of relocated saves: zero crashes.
- The Open-SP variant: campaign-complete detected within 10 s of load; the yard is purchasable.

## Engine facts to rely on / verify

- Whether a save made while in combat is allowed in SP. Record it.
- What vanilla does with an unknown base on load (expected crash; R4 §A1.4.2). Never test this on anything but a lane.

## Pitfalls

- The save filename hash: Console mirrors FL's `%x.fl` naming (R5 §3.1). Pair the JSON by exact save filename.
- flplusplus `always_regenerate_restart_file = true`: never rely on `Restart.fl`.

## Fallbacks and degrade path

If an old schema version can't be migrated, load it with mod state reset plus a backup and a toast. Document it in COMPATIBILITY.md.

## Report

Standard, plus the matrix summary table.

## Gate-time addendum

(orchestrator)
