# W5-SHIP: The playable install, launcher, player guide and public release v1.0.0

- **Type:** impl
- **Wave:** 5
- **Depends on:** W5-SOAK, W5-COMPAT
- **Unblocks:** F

## Goal

When Adam comes back, he types one command and plays. This package delivers:

- a clean modded install (`/home/user/freelancer/prefix-carrier`) made from his untouched play prefix;
- `/home/user/freelancer/play-carrier.sh`, which starts the copilot sidecar and then the game, and cleans up after;
- a player guide;
- the release candidate for the public GitHub release, containing only our own work. **The orchestrator publishes `v1.0.0` after gate F passes, on the exact SHA F tested** (CONVENTIONS §11). This package produces a **draft** release or an `-rc.N` tag only.

His original `prefix` and `play.sh` keep working exactly as before.

## Requirements

- **REQ-W5-SHIP-1.** `ship/install.sh`, idempotent, safe to re-run:
  1. Verify that no process uses `/home/user/freelancer/prefix`, with `tools/play_prefix_busy.sh` (it checks both the `WINEPREFIX` env and the cwd; `play.sh` runs `cd EXE; exec wine-proton …`, so `pgrep -f` misses it). Refuse otherwise.
  2. `cp -a --reflink=always /home/user/freelancer/prefix /home/user/freelancer/prefix-carrier` (if missing; `--rebuild` recreates it).
  3. Apply the profile for the **chosen track** (Gate 0a): Track A removes the FLUF-forbidden HDE DLLs from `dacom.ini`/`freelancer.ini` and installs FLUF; Track B leaves HDE intact.
  4. Deploy the release build (DLLs, generated data from *this* install, patches, resource DLL).
  5. Set flplusplus `save_folder_name` to **`FreelancerCarrier`**, so modded saves never mix with Adam's vanilla HDE saves (R4 pitfall 15; darklab8 note).
  6. **Do not** enable the devbridge.
  7. **Do not** apply the lane-only test tweaks (window size, `save_in_directory`, debug WINEDEBUG). Keep Adam's display settings from his PerfOptions. Apply the keep-running-unfocused patch **only if** the Gate 0a / P0 baseline proves it harmless; record the decision.
  8. Write a manifest.
- **REQ-W5-SHIP-2.** `ship/uninstall.sh`:
  1. Run `tools/uninstall/relocate_saves.py` on the modded save folder.
  2. Offer `--remove-prefix` to delete `prefix-carrier`. It never touches `prefix`.
- **REQ-W5-SHIP-3.** `/home/user/freelancer/play-carrier.sh` (source in `ship/play-carrier.sh`, installed by `install.sh`):
  1. Start the sidecar in its **play** profile:
     - venv python (`$FLMOD_SIDECAR_VENV`), with `LD_LIBRARY_PATH` set for the CUDA-12 cuBLAS/cuDNN wheels (R6 §4.1);
     - bound to `127.0.0.1:29170`;
     - offline models from `$FLMOD_MODELS` (`HF_HUB_OFFLINE=1`);
     - the brain sandbox per CONVENTIONS §13 (cwd `/home/user/freelancer/carrier-brain-cwd`, allowlisted env, `--tools ""`, `--strict-mcp-config`, `--disallowedTools 'mcp__*'`);
     - logs and the memory DB under `/home/user/freelancer/carrier-data/` (outside the repo and the prefix; created by `install.sh`).
  2. Wait ≤ 10 s for its health check. If that fails, continue without voice and print a notice; the game must still start.
  3. Export `FLCOPILOT_PORT`, `WINEPREFIX=/home/user/freelancer/prefix-carrier` and the same DXVK env as `play.sh`.
  4. `cd` into EXE and run `wine-proton Freelancer.exe "$@"`.
  5. On game exit or Ctrl-C (trap), stop the sidecar and run `wineserver -k` for that prefix only.

  Mirror `/home/user/freelancer/play.sh`'s style.
- **REQ-W5-SHIP-4.** Copilot config defaults, in a config file Adam can edit, documented in the guide:
  - mic = the PipeWire source matching the `mic_match` substring. `install.sh` copies Adam's value from the gitignored `local/sidecar.local.yaml` into the play config under `/home/user/freelancer/carrier-data/`. Public files (README, guide) describe the `mic_match` setting generically and never name the device (DESIGN D-11.3);
  - PTT = numpad period (`ptt_key = numpad_period`), with the alternative `numpad_minus` documented (it unbinds the hidden `USER_ZOOM_IN`);
  - LLM = Claude CLI `claude-opus-5-5` at low effort (D-11.2, D-11.3).
- **REQ-W5-SHIP-5.** `docs/PLAYER_GUIDE.md` (public). Include:
  - how to launch;
  - what's new in Sirius (carriers, classes and tiers, yards and where they are, upgrades, docked and escort travel, ambushes and distress calls, the Nomad gate, wingmen and hiring, the copilot and voice, escalation summary linking `docs/design/ESCALATION.md`);
  - controls (every new hotkey and button);
  - tunables (where the YAML files are, what to change);
  - saves (separate folder; how to back up);
  - uninstall;
  - troubleshooting (logs, sidecar status, a known-issues link to BUILD_REPORT);
  - the AGPL notice.
- **REQ-W5-SHIP-6.** `README.md` (public front page). **Ownership note:** P0-REPO created it. The orchestrator transfers ownership to W5-SHIP for Wave 5; this package rewrites it. Cover:
  - what the mod is;
  - requirements (Freelancer + HD Edition v0.7.1, Linux/Wine; Windows untested unless proven);
  - install/build-from-source (no game files in the repo; generators run against your install);
  - status;
  - license (AGPL-3.0);
  - credits (TheStarport/FLUF if Track A, FLHDE, adoxa, Librelancer and the other references used, per their licenses);
  - links to the guide and design docs.
- **REQ-W5-SHIP-7.** Release packaging, `ship/package_release.sh` (CONVENTIONS §11):
  - **Source only by default:** `gen/`, `data/` YAML, `tools/`, `ship/`, `sidecar/` (without venv, models or `*.db`), `src/`, and docs.
  - **Built DLLs are attached only if** you verify that FLSDK's license permits redistributing binaries linked against its import libs. FLSDK has no license file (P0 finding), so the default is **no DLLs**, and the README explains how to build. Record the decision with evidence.
  - **No game files or extracts, no `local/`, no generated overlay INIs, no CMP copies.**
  - `tools/check_public.py --release <dir>` must pass.

  Then create a **draft** GitHub release (`gh release create v1.0.0-rc.<n> --draft`, or a draft named v1.0.0) on `expectbugs/freelancer-carrier-mod`, with notes summarizing features, degraded items and known issues. **Never publish `v1.0.0` or push its tag**: the orchestrator does that after F.
- **REQ-W5-SHIP-8.** Verification: the F-gate fresh-install test (TESTING §F step 5) passes using exactly these scripts.

## Context pack (read before writing code)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §11 release policy, §13 sidecar/brain, §15 Wine safety)
- `docs/plan/DESIGN.md` (all, for the guide)
- `docs/plan/AUTONOMY.md` §1–2 (allowed paths, public-repo rules)
- `docs/plan/TESTING.md` §F, §Lanes (which tweaks are lane-only)
- `state/gates/G0a.md` (track), `state/DECISIONS.md`, `state/DEGRADED.md`
- `/home/user/freelancer/play.sh` (read-only; mirror style)
- `harness/deploy.sh` and `gen/` (reuse; don't fork logic)
- `local/research/R6-copilot-sidecar.md` §4 (audio stack, CUDA libs, mic source)
- `local/research/R4-lore-and-testloop.md` §A2.2 and §A4.6 (HDE installer options), §B6

## Ownership

- **Owns:** `ship/`, `docs/PLAYER_GUIDE.md`, `/home/user/freelancer/play-carrier.sh`, `/home/user/freelancer/prefix-carrier` and `prefix-carrier-test` (created by install), `/home/user/freelancer/carrier-data/` (play config, logs, memory DB), `README.md` (ownership transferred in Wave 5)
- **Reads:** everything
- **Must not touch:** `/home/user/freelancer/prefix`, `/home/user/freelancer/play.sh`, `installers/`, `~/.wine`

## Contract

- **Consumes:** the deploy pipeline, release build, sidecar, uninstall tool.
- **Provides:** the install, launcher, guide, README and release.

## Tasks

1. `install.sh`, `uninstall.sh`, `play-carrier.sh`; shellcheck-clean.
2. Write the guide and README.
3. Packaging and the release-safety check.
4. Fresh-install dry run (TESTING §F step 5) on a temporary name (`prefix-carrier-test`), then the real `prefix-carrier`.
5. Create the GitHub release.

## Acceptance (all automated)

- `shellcheck ship/*.sh` clean.
- A scenario `ship_fresh_install`:
  1. `install.sh` into `prefix-carrier-test`.
  2. Launch via a `play-carrier.sh` variant pointing at it.
  3. The sidecar health check is ok.
  4. Load a test save copied in, and buy a carrier.
  5. Quit; the sidecar is stopped (no process left); wineserver is gone.
  6. Delete the test prefix.
- A sha256 manifest of `/home/user/freelancer/prefix/drive_c/Games/Freelancer HD Edition/{EXE,DATA}` matches `local/play-prefix-manifest.sha256` (via `tools/play_prefix_manifest.sh verify`) (captured at build start).
- `check_public.py --release` passes. The **draft** release (or rc tag) exists on GitHub with the source package attached. `v1.0.0` is **not** published by this package.

## Engine facts to rely on / verify

- Track profile facts (G0a); the keep-running-unfocused patch effect on normal play.

## Pitfalls

- Never reflink-clone the play prefix while anything uses it: check with `tools/play_prefix_busy.sh`.
- AGPL: if Track A, the release must include the corresponding source (the repo itself), and the notice in README and guide.

## Fallbacks and degrade path

If creating the draft fails (network or auth), retry with backoff. If it is still failing, stage the package locally and record the exact `gh` command in the report. The orchestrator retries when publishing after F.

## Report

Standard, plus the paths of the install, launcher, guide and release URL.

## Gate-time addendum

(orchestrator)
