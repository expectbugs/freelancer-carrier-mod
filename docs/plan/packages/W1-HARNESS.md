# W1-HARNESS: scenario runner, assertion library, regression suite, playbot, soak runner, metrics

- **Type:** test (tooling)
- **Wave:** 1
- **Depends on:** ARCH-0 (devbridge spec `docs/spec/devbridge.md`), P0-HARNESS (lanes, deploy, fixtures, crash triage); sub-wave 1a (CONVENTIONS §8) → **Unblocks:** every package's in-game acceptance, gates G1/M1/M2/M3/F, W5-SOAK

## Goal

Make in-game testing as easy and trustworthy as unit testing, for an unattended build:

- **One YAML scenario** describes a fixture, devbridge steps, waits, assertions, screenshots with vision rubrics, and metrics. One command runs it on a free lane and returns a machine-readable verdict with evidence.
- **The playbot framework** lets an agent "play" a journey with screenshots and vision judgements, replacing Adam's playtests.
- **The soak runner** loops scenario mixes for hours and catches crashes, hangs and leaks.
- **Metrics extraction** turns `HARNESS` lines into numbers that gates compare against TESTING §Metrics targets.

## Requirements

- **REQ-W1-HARNESS-1: Scenario YAML schema = TESTING §Scenarios, exactly** (CONVENTIONS §5).
  - Fields: `name`, `package`, `tags`, `lane: any|input`, `fixture` (a `HARNESS_*` name, CONVENTIONS §6), `mod_state`, `timeout_s`, `setup`, `steps`, `asserts`, `evidence`.
  - Step kinds: `do` (+`expect`), `wait` (`ev`/key-values/`within_s`), `expect_state`, `shot`, `vision` (rubric file under `harness/rubrics/`), `input`.
  - Publish `harness/scenarios/SCHEMA.md` plus a JSON-Schema file, and a linter (`harness/scenario.sh lint`).
  - **Additive optional keys** (document them in SCHEMA.md, and propose them for TESTING in your report): `sleep_game`, `sleep_real`, `metric`, `save`, `load`, `restart_game` (full process restart, for persistence tests), `include` (shared step lists), `repeat`, `config` (mod config overrides for the run), `profile` (`track`/`base_plan`, default from the ledger).
  - Unknown keys are lint errors.
- **REQ-W1-HARNESS-2: Runner.** `harness/scenario.sh <file|dir> [--lane N] [--keep] [--suite <tag>]`. It:
  1. acquires a lane via `harness/lane.sh` (and the input lock for `lane: input`; `--perf` when the scenario is tagged `perf`);
  2. deploys the current build (`harness/deploy.sh`, which calls W1-DATA's `gen/run.py deploy --prefix <lane>`);
  3. writes the fixture save with `harness/fixtures/gen_fixture.py`;
  4. launches with `--save-file=HARNESS_<name>` on Track A (the FLUF debugger module), or uses the devbridge `load` on Track B;
  5. drives the steps;
  6. collects evidence: the TESTING §Scenarios file list, including the FLSpew diff, `carrier.log`, the devbridge log, the wine log (`+seh,+loaddll`), screenshots and crash dumps;
  7. kills the lane prefix's wineserver;
  8. releases the lane;
  9. writes `$FLMOD_TESTRUNS/<UTC stamp>-<name>/verdict.json` plus a short `summary.txt`. **Never** write under `harness/out/`.

  Verdicts are PASS, FAIL, CRASH, HANG or ERROR. Exit codes: 0 pass, 1 fail, 2 crash, 3 hang, 4 harness error. Scenarios are discovered recursively under `harness/scenarios/` and `src/**/scenarios/`.
- **REQ-W1-HARNESS-3: Assertion library** (Python, `harness/lib/assertions.py`):
  - HARNESS regex with capture groups;
  - ordered-sequence asserts;
  - numeric comparisons with tolerances;
  - "eventually within N game seconds";
  - absence assertions (e.g. no `ev=docked base=intro…`);
  - state-expression asserts over the last `state` line (safe expression evaluator, no `eval`);
  - spew diff against the allow-list baseline;
  - crash signatures. Per R4 B7/B10: process gone, `c0000005`, `dw15.exe` running, a "Fatal Crash" window, a new `.dmp`. Crash RVAs are resolved through `/home/user/freelancer/carrier-mod/local/research/scratch/` crash-offset tables or the KB JSON (`/home/user/freelancer/refs/starport-kb-payload/` / `StarportKnowledgeBase/static/payloads/crash-offsets.json`).
- **REQ-W1-HARNESS-4: Vision checks** (TESTING §Vision).
  - `shot` steps capture the game window via the P0-HARNESS method (`import -window <wid>`, or the in-game screenshot path via devbridge `shot`), plus a 50% downscale.
  - The rubric text is stored alongside.
  - Judgement is performed by an agent: the scenario's runner agent, or a dedicated vision step when the runner is a script.
  - Automatic pre-checks run first (TESTING §Vision): not black, not frozen, correct size. These are in `harness/vision_precheck.py`, owned here.
  - The script writes `vision_pending.json` listing each image plus its rubric (`harness/rubrics/<name>.yaml`). The calling agent views each image with its Read tool and writes per-item `yes|no|unclear` judgments. `scenario.sh finalize <run-dir>` merges them into `vision.json` and the verdict.
  - A scenario with pending vision checks is never reported as passed.
- **REQ-W1-HARNESS-5: Suites and CI.** `harness/suite.sh <tag> [--lanes N]` runs every scenario with the tag, in parallel across free lanes. Input-lock scenarios run serially. It produces an aggregate report (`$FLMOD_TESTRUNS/<stamp>-suite-<tag>/report.md`).
  - Built-in suites: `smoke` (≤ 5 min), `ci` (the per-merge subset; each scenario < 4 min), `regression`, `m1`, `m2`, `m3`, `f`.
  - **Quarantine.** Scenarios listed in `state/QUARANTINE.md` run, but are reported as `SKIP(quarantined)` and don't fail the suite (CONVENTIONS §10).
  - **CI wiring** (CONVENTIONS §5; the CLI is TESTING §CI: `harness/ci.sh [--quick|--full] [--lanes N] [--only <stage>]`). This package owns these drop-in stages:
    - `harness/ci.d/60-scenarios-quick.sh`: in-game smoke plus the `ci` tag;
    - `70-scenarios-full.sh`: the `regression` tag, with `--full` only;
    - `80-soak-smoke.sh`: a 10-minute mini-soak, with `--full` only.

    A stage whose prerequisites don't exist yet reports SKIP.
- **REQ-W1-HARNESS-6: Playbot framework** (TESTING §Playbot). A CLI `harness/playbot/pb.py` that an agent uses to play interactively:

  | Command | Does |
  |---|---|
  | `pb start <fixture> [--lane]` | start a session |
  | `pb cmd '<devbridge>'` | run a devbridge command |
  | `pb wait '<regex>' [--timeout]` | wait for a log line |
  | `pb state` | current game state |
  | `pb shot <name>` | screenshot path, ready for the agent to view |
  | `pb key <keys>` / `pb click <ui-id|x,y>` / `pb type <text>` | input; requires the input lock. Real XTEST input: `xdotool windowactivate --sync <wid>`, then `xdotool key/type/mousemove/click` with no `--window` (CONVENTIONS §7). Coordinates come from `ui.find`. |
  | `pb fly-to <system> <x,y,z>` | uses devbridge autopilot/teleport helpers |
  | `pb note '<observation>'` | appends to the journal |
  | `pb stop` | end the session |

  - **Journeys** live in `harness/playbot/journeys/<owner>/*.md` (milestone packages own `harness/playbot/journeys/<id>/`): a human-readable script of goals and checkpoints with expected observations (e.g. "buy a Fleet Carrier at Norfolk; travel aboard to Texas; stop; undock; it is visible behind you").
  - The playbot agent follows the journey, takes screenshots at checkpoints, and judges them. It writes `$FLMOD_TESTRUNS/playbot-<journey>-<ts>/JOURNAL.md` (the TESTING §Playbot entry format) plus `verdict.json`, with pass/fail per checkpoint and evidence.
  - It must also do "exploratory" sweeps: for each open panel, try every button once and screenshot the result.
- **REQ-W1-HARNESS-7: Soak runner** (TESTING §Soak). Owns `harness/soak/` (W5-SOAK only adds `harness/soak/mixes/w5_*.yaml`).
  - **Journey generator** `harness/soak/journey.py`: seeded random sequences of devbridge actions covering everything merged so far (the TESTING §Soak list). Actions whose verbs don't exist yet are skipped (it reads `help`).
  - **Runner:** `harness/soak/soak.sh --hours H --lanes L --seed S [--mix harness/soak/mixes/<name>.yaml]`.
    - Runs journeys back to back per lane, restarting the game every 45 minutes.
    - Collects the `ev=hb`, `ev=perf` and `ev=mem` series into `soak.csv` per lane.
    - Hang = no `ev=hb` for 60 s while not paused → minidump through the guard (`WINEPREFIX=<lane> winedbg --minidump …`), then kill the lane.
    - Writes `$FLMOD_TESTRUNS/<stamp>-soak/report.md`: crash count and signatures, `va` trend (MB/h), mean and 1%-low FPS, and the post-soak load check of 20 random saves.
  - **Mixes:** ship `harness/soak/mixes/w1.yaml`, plus `m1.yaml`, `m2.yaml` and `m3.yaml` skeletons that milestones fill.
  - Pass/fail uses exactly the TESTING §Soak crash-free criteria.
- **REQ-W1-HARNESS-8: Metrics extraction.** `harness/lib/metrics.py` parses `HARNESS metric=<name> value=<v> [unit=…]`, `ev=perf`/`ev=mem` lines and scenario `metric` steps across runs into `metrics.json`.
  - It compares them against `harness/metrics_targets.yaml`, the **single source** of numeric targets: it encodes TESTING §Metrics verbatim, including the 10 sample routes. It is owned here and changed only by orchestrator decision.
  - Each metric is marked in-range or out-of-range, and gates consume this. Package specs must not restate conflicting numbers.
- **REQ-W1-HARNESS-9: Evidence hygiene.**
  - All run output goes to `$FLMOD_TESTRUNS/` (outside every worktree, gitignored).
  - Gate summaries are copied into `state/gates/` by the orchestrator only (CONVENTIONS §10). Screenshots are never committed.
- **REQ-W1-HARNESS-10: Fixtures** (CONVENTIONS §6, TESTING §Fixtures). From Wave 1 this package owns `harness/fixtures/gen_fixture.py`, which P0-HARNESS created with a base set. It implements the **full** required set:
  - `HARNESS_new_story`, `HARNESS_lvl1_rich_fp9`, `HARNESS_endgame_eagle`;
  - all nine `HARNESS_yard_<base>`;
  - `HARNESS_ew06_space`, `HARNESS_hostile_frontier`, `HARNESS_friendly_frontier`, `HARNESS_poor`, `HARNESS_osp`;
  - mod-state fixtures (`carrier_json:`) produced through the real schema.

  Fixtures always set system, base and position explicitly; `newplayer.fl` starts in FP7. Every fixture is validated against the lane's DATA. Prove in game that `post_campaign: true` opens the gates and that the campaign-complete detector reads 1 (the detector is W1-CORE, sub-wave 1b, so `DEFERRED(W1-CORE)`).
- **REQ-W1-HARNESS-11: Lane infrastructure** (CONVENTIONS §7, §14). From Wave 1 this package owns `harness/` except `harness/devbridge/` (W1-CORE) and per-package scenario folders, and may modify the Phase-0 scripts.
  - `harness/lane.sh acquire [--input] [--perf] [--lane N] | release | reap`, with absolute lock files under `$FLMOD_LOCKS`. `--perf` is exclusive: it waits for all other lanes to finish and blocks new acquisitions.
  - Per-lane environment: `FLCOPILOT_PORT=29170+N`. Any sidecar a lane starts runs `--profile test`: fake LLM, null audio sink, file mic (CONVENTIONS §13).
  - `harness/deploy.sh` calls `gen/run.py deploy --prefix <lane prefix>` (W1-DATA's CLI, same sub-wave). Until W1-DATA merges, keep the Phase-0 deploy path and mark the switch-over `DEFERRED(W1-DATA)`.
  - Shared assets owned here: `harness/rubrics/`, `harness/spew_allow.txt`, `harness/config.sh` (`LANES`), `harness/triage.py`.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §5–§7 and §10 especially)
- `docs/plan/BUILD_PLAN.md` §3, §5, §7
- `docs/plan/TESTING.md` (all sections, especially §Lanes, §Devbridge, §Fixtures, §Scenarios, §Playbot, §Vision, §Metrics, §Soak, §CrashTriage, §CI)
- `docs/spec/devbridge.md` (ARCH-0)
- The P0-HARNESS deliverables: `harness/lane.sh`, `harness/deploy.sh`, `harness/run.sh`, `harness/fixtures/`, crash triage, baseline spew allow-lists, and the headless-lane evaluation result (in its `NOTES.md` and `state/ENGINE_FACTS.md`)
- Research: `/home/user/freelancer/carrier-mod/local/research/R4-lore-and-testloop.md` §B6 (launching, window detection, input under Proton, screenshots, the keep-running patch, `--save-file`), §B7 (logs, crash detection, Wine diagnostics), §B10 (harness design and `fltest.sh` sketch, devbridge recommendation), §A5 (universal-modder methodology: oracles, journal, command-file bridge)
- Reference: `/home/user/freelancer/refs/universal-modder/skills/game-automation/SKILL.md` and `knowledge/techniques/*.md` (methodology only; its `um win` tooling is Windows-only)

## Ownership

- **Owns:** `harness/` (CONVENTIONS §14), including `lane.sh`, `deploy.sh`, `run.sh`, `config.sh`, `fixtures/`, `rubrics/`, `lib/`, `playbot/`, `soak/`, `scenario.sh`, `suite.sh`, `vision_precheck.py`, `triage.py`, `spew_allow.txt`, `ci.d/60-*`/`70-*`/`80-*`, `scenarios/SCHEMA.md`, `scenarios/selftest/` and cross-package suite lists. It owns **no** per-package scenario folders.
- **Reads:** everything else.
- **Must not touch:**
  - `harness/devbridge/` (W1-CORE);
  - per-package scenario folders (`harness/scenarios/<area>/` of other packages, and `src/**/scenarios/`);
  - `harness/ci.sh` itself (P0-REPO's CLI, except a bug fix proposed in the report);
  - the mod code;
  - `tools/` (orchestrator-owned).

## Contract

- **Provides:** the scenario schema plus runner, assertion library, suites, `ci.sh` smoke integration, playbot CLI plus journey format, soak runner, metrics pipeline.
- **Consumes:** the devbridge protocol, lanes, deploy and fixtures.

## Tasks

1. Schema (Markdown plus JSON-Schema) and validator (`scenario.sh lint`).
2. Runner with the evidence bundle and exit codes. A dry-run mode on a fake game (a Python stub that consumes `cmd-<seq>.txt` files and emits HARNESS lines) for host tests.
3. Assertion library plus unit tests against recorded logs.
4. Vision pending/verdict flow.
5. Suites, parallel lane scheduling, quarantine handling, and the `ci.d/60`, `70` and `80` stages.
6. Playbot CLI plus 3 starter journeys (platform tour, UI kit tour, save/load tour).
7. Soak runner (`journey.py`, `soak.sh --seed`, mixes), hang detection, memory and FPS sampling.
7b. Fixture generator: the full TESTING §Fixtures set (REQ-10). Lane infrastructure: the `--perf` lock, per-lane sidecar port, the `gen/run.py deploy` hook (REQ-11).
8. Metrics pipeline plus `metrics_targets.yaml`.
9. Self-test: run the `smoke` suite on 2 lanes in parallel, plus one input-lock scenario.

## Acceptance

- **Host tests (pytest):**
  - `test_schema_examples_valid`
  - `test_runner_fake_game_pass_fail_crash_hang` (exit codes 0/1/2/3 with the stub)
  - `test_assert_sequence_and_absence`
  - `test_metrics_targets_compare`
  - `test_vision_pending_blocks_pass`
  - `test_suite_parallel_lane_allocation` (no two runs share a lane; input runs are serialized)
- **In-game:**
  1. The `smoke` suite passes on the current `main` (with whatever scenarios exist) on 2 lanes concurrently. Report the wall time.
  2. A deliberately crashing run is detected as a crash, with the RVA resolved against the offsets table.
     - Now: the fake-game stub, plus a raw Phase-0 crash if one is available.
     - In game: `debug crash` from W1-CORE, marked `DEFERRED(W1-CORE)` (sub-wave 1b) and run in the wave integration pass.
  3. A hang is detected and produces a minidump. Same split: stub now, `debug hang` `DEFERRED(W1-CORE)`.
  4. A playbot dry journey: an agent (you) runs the "platform tour" journey with `pb`, views 3 screenshots, writes the journal and verdict.
  5. A 15-minute soak with a 3-scenario mix: the report contains the memory slope and zero crashes.

## Engine facts to rely on / verify

- Under Proton, only real focused input reliably reaches the game (R4 pitfall 14). Input steps therefore need the input lock and `xdotool windowactivate --sync`.
- The HDE keep-running-unfocused patch on lanes (`Freelancer.exe` @0x1B264C) lets non-input scenarios run unfocused in parallel. Verify with the parallel smoke suite.
- `--save-file` autoload works only with the FLUF debugger module (Track A). On Track B, the devbridge `load <desc>` after the main menu is reached, or a P0-HARNESS-proven method.

## Pitfalls

- Never `pkill wine` or `pkill -f Freelancer`: kill only the lane's wineserver.
- Wine file-delete lag on `cmd-<seq>.txt`: the protocol remembers the last seq; the client never reuses a seq.
- Screenshots of covered or minimized DXVK windows can be black. Use `DXVK_CONFIG="d3d9.presentInterval = 0"` and window placement per P0-HARNESS.
- Don't leave lanes locked on runner crash: use trap-based release plus the stale-lock reaper (`lane.sh reap`).

## Fallbacks and degrade path

1. If parallel lanes are unreliable, run serially and record the wall-time impact (gates take longer; nothing is skipped).
2. If window screenshots fail, use the in-game PNG screenshot through the devbridge `shot` (flplusplus path) or the overlay capture.
3. If vision judgement is unavailable in some context, the verdict is "pending" and blocks the gate. Never auto-pass.

## Report

Use the standard report. Include the schema link, the suite timings, a sample `verdict.json`, and a sample playbot journal.

## Gate-time addendum

The orchestrator fills:

- the lane count and headless decision (P0-HARNESS fact);
- the track autoload method;
- the devbridge spec version;
- the Phase-0 deploy path still in use (if W1-DATA hasn't merged yet);
- attempt notes;
- the commit trailer.
