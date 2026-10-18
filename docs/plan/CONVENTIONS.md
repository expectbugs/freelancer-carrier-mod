# Conventions: the single source for names, paths, protocols and procedures

Specs, briefs and code **must** use exactly these names. Where a package spec disagrees with this file, this file wins. The spec is wrong; fix it, or report it as a blocking question.

This file was created from the plan review of 2026-10-17. Its finding numbers (#n) are cited in brackets.

## 1. Environment and absolute paths [#4, #24, #34]

Agents run in **git worktrees**, where gitignored paths (`local/`, `vendor/`, `.venv/`) don't exist. **Always use these absolute paths.** `tools/env.sh` exports them, and the session also loads that file via `CLAUDE_ENV_FILE` (see §15).

| Variable | Value | Purpose |
|---|---|---|
| `FLMOD_REPO` | `/home/user/freelancer/carrier-mod` | main checkout (merges, ledger, state) |
| `FLMOD_LOCAL` | `$FLMOD_REPO/local` | gitignored local data |
| `FLMOD_RESEARCH` | `$FLMOD_LOCAL/research` | research (read-only) |
| `FLMOD_REFS` | `/home/user/freelancer/refs` | reference source (read-only) |
| `FLMOD_LOCKS` | `$FLMOD_LOCAL/locks` | flock files (lanes, input, perf) |
| `FLMOD_TESTRUNS` | `$FLMOD_LOCAL/testruns` | every harness/scenario/soak run dir |
| `FLMOD_GOLDEN` | `$FLMOD_LOCAL/golden` | golden files derived from game data (never committed) |
| `FLMOD_VENDOR` | `$FLMOD_REPO/vendor` | fetched SDKs (FLUF pkg, FLSDK, reflect-cpp, nlohmann/json, doctest), shared by all worktrees |
| `FLMOD_VENV` | `$FLMOD_REPO/.venv` | the one shared Python venv (pytest, pyyaml, jsonschema, …) |
| `FLMOD_SIDECAR_VENV` | `$FLMOD_LOCAL/sidecar-venv` | sidecar venv (CUDA-12 libs, faster-whisper, kokoro-onnx) |
| `FLMOD_MODELS` | `$FLMOD_LOCAL/models` | voice models and caches (never committed) |
| `XWIN_ROOT` | `/home/user/opt/xwin` | MSVC CRT/STL + Windows SDK splat |
| `DISPLAY` | `:0` | |
| `WINEPREFIX` | **unset**; the guards refuse anything but `prefix-dev*`, `prefix-lane*`, `prefix-carrier*` | |

- **Python.** Use `$FLMOD_VENV/bin/python -I` for all tools and tests. To add a package: `$FLMOD_VENV/bin/pip install <pkg>`, then append it to `requirements-dev.txt` (an append-only shared file).
- **Builds.** Each worktree builds into its own `build/`. Vendor trees are shared read-only; only P0-TOOLCHAIN's fetch script writes them.
- **Heartbeat:** `$FLMOD_LOCAL/heartbeat`. **Watchdog log:** `$FLMOD_LOCAL/watchdog.log`.

## 2. Nicknames, flags, IDs [#16, #19]

- **Nicknames.** Every new game nickname starts with `fcm_` (Freelancer Carrier Mod): goods, archetypes, loadouts, bases, NPC defs, factions, sounds. Examples: `fcm_salvage_pod`, `fcm_carrier_fleet_li_t1`. Run the hash-collision scan on every data build.
- **Persistent flags** (mod JSON; critical ones mirrored in the `.fl` `[mPlayer]` block):

  | Flag | Meaning |
  |---|---|
  | `campaign_complete` | D-13.1 |
  | `nomad_gate_unlocked` | D-12.1; the only name used for the Nomad unlock |
  | `fleet_cap_warned` | Fleet cap warning shown |
  | `army_scale_warned_session` | Army-scale warning shown (session-scoped, not saved) |

- **Text.** Strings use keys like `carrier.*`, `upgrade.*`, `yard.*`, `ui.*`, `crew.*`, `nomad.*`, `enc.*` in `data/<area>/strings.yaml`. The text pipeline assigns IDS from `docs/spec/text_ids.md` and writes the generated map `$FLMOD_LOCAL/gen/text_ids.json`.

## 3. Contracts and specs that ARCH-0 must deliver (exact files) [#3]

**`src/contracts/`** (header-only interfaces):

- `platform.hpp`, `clock.hpp`, `events.hpp`, `persistence.hpp`, `config.hpp`, `log.hpp`, `devbridge.hpp`
- `spawn.hpp`, `ai.hpp`, `ui_kit.hpp`, `text.hpp`, `world.hpp`, `inventory.hpp`
- `carrier.hpp`, `encounter.hpp`, `reflex.hpp`, `wingmen.hpp`, `yard.hpp`, `loadout.hpp`, `ipc.hpp`, `escalation.hpp`

ARCH-1/2/3 may refine later ones; ARCH-0 must create every file, even as a skeleton.

**`docs/spec/`:**

| File | Contents |
|---|---|
| `devbridge.md` | wire protocol + the verb/event table, §4 |
| `persistence.md` | JSON layout, versioning, `.bak`, corrupt-file handling (TESTING §SaveCompat wins) |
| `world_json.md` | `world.json` schema |
| `data_schemas.md` | YAML schemas for `data/**`, with placeholder YAML committed so W1-DATA and W1-CARRIER-DESIGN agree |
| `events.md` | the event bus catalog |
| `ui.md` | UI kit and overlay rules |
| `text_ids.md` | IDS allocation |
| `ipc.md` | the sidecar protocol (from P0-SIDECAR) |
| `scenario_schema.md` | = TESTING §Scenarios |
| `fixtures.md` | = §6 |
| `balance_sim.md` | the balance simulator interface |
| `ownership.md` | **moved: the ownership map is `docs/plan/OWNERSHIP.md`** |

- **JSON library:** nlohmann/json (single header, MIT), vendored under `FLMOD_VENDOR`.
- **Host tests:** doctest.

## 4. Devbridge: wire protocol, verbs, events [#13]

- **Wire protocol:** as in P0-HARNESS REQ-12 (`harness/devbridge/PROTOCOL.md`), copied to `docs/spec/devbridge.md`.
- **Line format:**
  - `HARNESS t=<game s> wall=<unix ms> …`
  - acks: `HARNESS ack id=<id> ok=1|0 [err="…"]`
  - events: **`ev=<name>`** (never `evt=`)

**Verbs.** Owners implement them; ARCH packages freeze the arguments and outputs.

| Verbs | Owner |
|---|---|
| `ping`, `echo`, `sleep_frames`, `seq`, `state`, `load`, `save`, `quit`, `shot`, `vmstat`, `perf` | Phase 0 core / tracks, then W1-PLATFORM |
| `wait_in_space`, `wait_docked`, `pause on\|off`, `time`, `time.skip <s>`, `time.scale <x>` (may answer `err=unsupported`), `config get\|set\|reload`, `log level`, `assert <expr>`, `rng.seed <n>`, `debug crash` (test-only: deliberate crash for triage tests), `help` | W1-CORE |
| `base <nick>`, `system <nick> [x,y,z]`, `pos x,y,z`, `rep <faction> <v>`, `cash <n\|+n\|-n>`, `give <good> <n>`, `godmode on\|off`, `launch` | W1-CORE (test cheats) |
| `spawn <npc_def> [n] [near=player\|x,y,z] [tag=<t>]`, `despawn <tag\|id>`, `freeze <tag>`, `thaw <tag>` | W1-SPAWN |
| `ui.find <control>`, `ui.click <control>`, `ui.open <panel>`, `ui.list` | W1-UI |
| `carrier.*` (`buy`, `status`, `list`, `travel`, `stop`, `escort`, `loadout`, `resupply`, `teleport_model`) | W2-CARRIER-* |
| `yard.*` | W2-YARD |
| `enc.*` (`define`, `trigger`, `list`, `resolve`) | W2-ENCOUNTER |
| `reflex.*`, `ipc.*` | W2-REFLEX |
| `ambush.*` | W3-AMBUSH |
| `escort.*` | W3-ESCORT |
| `nomad.*` | W3-NOMAD |
| `loss.*` | W3-LOSS |
| `wing.*`, `hire.*` | W4-WINGMEN / W4-HIRING |
| `brain.*` (`context`, `say`) | W4-BRAIN |
| `esc.*` | W4-ESC-* |
| `wait_menu`, `wait_event <ev> [timeout_s]`, `log <text>`, `perf.sample`, `mem.sample`, `debug hang` (test-only) | W1-CORE |
| `take <good> <n>`, `equip <item> <hp>` (test cheats) | W1-CORE |
| `target <id\|tag>`, `kill <id\|tag>` | W1-SPAWN |
| `platform.*` | W1-PLATFORM |
| `world.probe` | W1-WORLD |
| `inv.*` | W1-INVENTORY |

- **Spawn arguments:** canonical `near=` and `tag=`. `rel=`, `at=` and `id=` are accepted as aliases.
- **Platform event names** are frozen by ARCH-0 in `docs/spec/events.md`. Seed list: `ev=docked base=`, `ev=undocked`, `ev=launched`, `ev=jump.out`, `ev=jump.in system=`, `ev=save file=`, `ev=load file=`, `ev=death`, `ev=pause on=0|1`, `ev=menu`.

**Periodic events** (W1-CORE emits):

- `ev=hb` every 10 s
- `ev=perf fps_avg= fps_p1= ships= window_s=10` every 10 s
- `ev=mem va_free_mb= va_largest_free_mb= heap_mb=` every 60 s

Key names are **`va_free_mb` / `va_largest_free_mb`**; `vmstat` prints the same keys.

## 5. Scenarios, run output, CI [#7, #8, #14]

- **Scenario YAML schema** = TESTING §Scenarios (`package`, `do`, `asserts`, …). One runner: `harness/scenario.sh <file|dir> [--lane N]`.
- **All run output** goes to `$FLMOD_TESTRUNS/<UTC stamp>-<name>/`. Nothing is ever written to `harness/out/`, which is gitignored as a safety net.
- **CI CLI** = TESTING §CI: `harness/ci.sh [--quick|--full] [--lanes N] [--only <stage>]`. It writes `$FLMOD_TESTRUNS/<stamp>-ci/summary.md`. Stages are drop-ins in `harness/ci.d/NN-<name>.sh`; only `public` is built in.

  | Number | Stage | Owner |
  |---|---|---|
  | 10 | build | P0-TOOLCHAIN |
  | 20 | host-tests | P0-TOOLCHAIN |
  | 30 | pytest | P0-DATATOOLS |
  | 40 | data-validate | W1-DATA |
  | 50 | import-check | P0-TOOLCHAIN |
  | 60 | scenarios-quick | W1-HARNESS |
  | 70 | scenarios-full | W1-HARNESS |
  | 80 | soak-smoke | W1-HARNESS |

  A stage whose prerequisites don't exist yet reports **SKIP**, not FAIL.
- **`tools/check_public.py`** lists files with `git ls-files -co --exclude-standard`, never walks the tree, and ignores `.claude/worktrees/` (amended 2026-10-18, P0-REPO review r1 F11: other `.claude/` files are scanned). It rejects files larger than 5 MB.

## 6. Fixtures [#15]

- **One namespace:** `HARNESS_<name>` (the save description).
- **One generator:** `harness/fixtures/gen_fixture.py`. P0-HARNESS creates it with the base set; W1-HARNESS owns it from Wave 1 and adds the full TESTING §Fixtures set, including all 9 yard fixtures.
- Fixtures always set `system`, `base` and position explicitly. HDE's `newplayer.fl` starts in FP7, so never rely on its defaults.

## 7. Locks, lanes, ports [#4, #21, #37]

- **Locks** are absolute, under `$FLMOD_LOCKS`, managed by `harness/lane.sh`:

  | Command | Gives |
  |---|---|
  | `lane.sh acquire` | an exclusive lane N |
  | `lane.sh acquire --input` | plus the global input lock (synthetic input and focus) |
  | `lane.sh acquire --perf` | exclusive perf lock: waits until no other lane runs, and blocks others; for S-PERF and FPS metrics |
  | `lane.sh reap` | frees stale locks |

- **Synthetic input** uses XTEST: `xdotool key` to the focused window, after `windowactivate --sync`. Never `xdotool key --window`, because XSendEvent is invisible to `GetAsyncKeyState`.
- **Sidecar port per lane:** `FLCOPILOT_PORT = 29170 + N` (lane N). The play install uses 29170.

## 8. Wave ordering and deferred scenarios [#1, #2]

**Sub-waves:** a sub-wave starts when its deps are merged. These dependencies are also in BUILD_PLAN §6 and the ledger.

| Sub-wave | Packages | Depend on |
|---|---|---|
| 1a | W1-PLATFORM, W1-HARNESS, W1-DATA, W1-WORLD, W1-CARRIER-DESIGN, W1-SIDECAR, W1-INVENTORY | ARCH-0 (+ listed) |
| 1b | W1-CORE, W1-SPAWN, W1-UI | W1-PLATFORM, W1-HARNESS |
| 2a | W2-CARRIER-LOGIC, W2-LOADOUT, W2-ENCOUNTER, W2-REFLEX | ARCH-1 |
| 2b | W2-CARRIER-GAME | W2-CARRIER-LOGIC, W2-LOADOUT |
| 2c | W2-YARD, W2-CARRIER-UI | W2-CARRIER-GAME |
| 3a | W3-ESCORT, W3-NOMAD, W3-LOSS | ARCH-2 |
| 3b | W3-AMBUSH | W3-ESCORT, W3-LOSS |
| 4a | W4-WINGMEN, W4-BRAIN, W4-ESCALATION-DESIGN | ARCH-3 |
| 4b | W4-HIRING | W4-WINGMEN |
| 4b | W4-ESC-* | W4-ESCALATION-DESIGN |

- W1-PLATFORM registers its own `platform.*` verbs through the Phase-0 devbridge core. The devbridge API (`DevbridgeRegister`) is stable from Phase 0, so 1b packages register commands the same way before W1-CORE's promotion lands.
- **Deferred scenarios.** An in-game scenario that genuinely needs an unmerged same-wave sibling is marked `DEFERRED(<sibling ID>)` in the report. The reviewer passes the package on host tests plus the non-deferred scenarios. After the last merge of the wave, the orchestrator runs every deferred scenario (the **wave integration pass**). Failures become FIX packages. "Deferred" is never used to dodge a scenario that could run.

## 9. State machine (canonical, = DESIGN D-7.11 as amended) [#17]

**States:** Stopped, DockedTravel, EscortTravel, Away, AmbushWaiting, UnderAttack, Destroyed.

**Edges:**

| From → To | Trigger |
|---|---|
| Stopped → DockedTravel / EscortTravel | travel order |
| DockedTravel → DockedTravel | re-route (new order while travelling) |
| DockedTravel → Stopped | arrive or Stop |
| DockedTravel → UnderAttack | ambush; forced stop, fight holds until launch |
| EscortTravel → Stopped | arrive or Stop |
| EscortTravel → Away | player leaves |
| EscortTravel → UnderAttack | ambush, or attacked |
| Away → EscortTravel | player returns |
| Away → Stopped | arrives while the player is elsewhere |
| Away → AmbushWaiting | ambush roll |
| AmbushWaiting → UnderAttack | player arrives |
| Stopped → UnderAttack | attacked while stopped: hostiles engage it, or an escalation event |
| UnderAttack → Stopped | win (all attackers destroyed or fled) |
| UnderAttack → AmbushWaiting | player leaves a live fight; it freezes again |
| UnderAttack → Destroyed | hull reaches 0 |
| Stopped → Destroyed, EscortTravel → Destroyed | hull reaches 0 outside a formal fight (pass through UnderAttack for one tick) |

**Reflex healing:** the carrier's auto-nanobots run whenever the carrier exists in space (Stopped, EscortTravel, UnderAttack) and its hull is below the policy threshold.

## 10. Reports, gates, failures, quarantine [#22, #23, #39, #40]

- **Reports on disk.** The orchestrator saves every agent final report verbatim to `state/reports/<ID>-a<n>.md` and every review to `state/reports/<ID>-r<n>.md` before acting on it. "Report paths" in specs mean these files.
- **Gate files.** `state/gates/<G>.md` are written **only by the orchestrator**. Agents put evidence in their run dirs and reports.
- **The ledger.** Edits keep **line 1** (the `BUILD_STATUS:` line) intact, except for deliberate status changes. Never insert a header above it.
- **Failed gates and playtests:**
  - A playtest **continues past a failed step**, records every failure, and finishes.
  - Each failure becomes a `FIX-<n>` package. Its spec lives in `state/briefs/FIX-<n>.md`, and its owned paths are those of the package that owns the failing code.
  - "Feel" observations that are within the metric ranges go to `state/TUNING.md`, not into FIX packages.
- **Quarantine.**
  - After 3 failed fix rounds on the same criterion, the feature is degraded (AUTONOMY §4) and the failing scenarios are listed in `state/QUARANTINE.md`, with reason and FIX ID.
  - `ci.sh` reports quarantined scenarios as **SKIP(quarantined)** and stays green.
  - Gates pass with a documented exception.
- **Gate F** is run by the orchestrator itself, not by a worktree agent. Agents may collect evidence. Only the orchestrator tags, publishes and sets `COMPLETE`.

## 11. Release policy [#6, #25, #26]

- **P0-REPO** creates the empty public repo (`gh repo create expectbugs/freelancer-carrier-mod --public`, no `--push`) and prepares the remote config. The orchestrator runs `git push origin main` after merging. Never push a `wp/*` branch. The `gh` token's scopes are VERIFIED to include `repo` and `workflow` (2026-10-17).
- **W5-SHIP** produces release notes and a **draft** release or `-rc.N` tag only.
- **The orchestrator** publishes `v1.0.0` after gate F passes, on the exact SHA F tested.
- **Release assets:**
  - Source only by default.
  - Built DLLs are attached only if W5-SHIP verifies FLSDK's license permits redistributing binaries linked against its import libs. Otherwise the README explains how to build.
  - `check_public.py --release <dir>` vets the assets.

## 12. Game-data hygiene [#28]

- **No values copied from game files into committed code or data.** That covers npcships fields, loadouts, positions and prices.
- The generators read them from the local install at deploy time (`gen/plugins/*`).
- Golden files derived from game data live in `$FLMOD_GOLDEN`.
- Committed YAML holds only our own design values and references by nickname.

## 13. Sidecar safety in tests [#27]

- **Offline models.** Set `HF_HUB_OFFLINE=1`; faster-whisper uses `local_files_only=True`, with models from `$FLMOD_MODELS`.
- **Harness profile** (`--profile test`): fake LLM (deterministic responder), null audio sink (no speaker output), file mic (`--mic-file <wav>`). Lanes, soaks and milestones always use this profile, except M3's single live-brain smoke step.
- **Brain sandbox:**
  - cwd is an empty directory **outside the repo**: `/home/user/freelancer/carrier-brain-cwd`.
  - The environment is an **allowlist**: `HOME`, `PATH`, `LANG`, `USER`, `XDG_RUNTIME_DIR`, plus the CLI's auth.
  - Flags: `--tools ""`, `--strict-mcp-config`, `--disallowedTools 'mcp__*'`, `--setting-sources ""` (or `--restricted`).
  - The first-run test inspects the stream-json init message and asserts zero tools and zero MCP servers.

## 14. Ownership changes (supersede spec text) [#36]

| Path | Owner |
|---|---|
| `state/**` | orchestrator only |
| `tools/env.sh`, `tools/display-awake.sh`, `tools/watchdog.sh`, `tools/start-build.sh`, `tools/play_prefix_*.sh`, `tools/bin/` | orchestrator only. Packages propose changes in their report. P0-HARNESS tests them, but never against the live build state (use a temp state dir). |
| root `CMakeLists.txt` and `cmake/` | P0-TOOLCHAIN → ARCH-0 → (ARCH-1/2/3). Discovery is by glob, so feature packages never edit it. |
| `src/module/` | ARCH-0 skeleton → W1-PLATFORM |
| `harness/soak/` | W1-HARNESS. W5-SOAK adds only `harness/soak/mixes/w5_*.yaml`. |
| `tests/compat/` | W5-COMPAT, not all of `tests/` |
| `requirements-dev.txt` | shared, append-only |
| `.gitignore` | orchestrator |

## 15. Wine safety [#5, #32]

- `start-build.sh` launches the orchestrator with these exported, so every Bash call inherits them:
  - `CLAUDE_ENV_FILE=$FLMOD_REPO/tools/env.sh`
  - `PATH=$FLMOD_REPO/tools/bin:$PATH`
  - the sentinel `WINEPREFIX=/home/user/freelancer/prefix-UNSET`

  If an unguarded wine is ever invoked, it creates a junk prefix there instead of touching `~/.wine`. The guards refuse that sentinel.
- **Raw paths.** Never call `/usr/lib/wine-proton-11.0.1/bin/*` or `/etc/eselect/wine/bin/*` directly. `winedbg` goes through the guard.
- **Prefix check.** The guard resolves `WINEPREFIX` with `realpath -m` before matching. Allowed: `prefix-dev*`, `prefix-lane*`, `prefix-carrier*`.
