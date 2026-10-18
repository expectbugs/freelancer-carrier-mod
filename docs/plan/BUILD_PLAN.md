# Freelancer Carrier & Endgame Mod: Master Build Plan

> **This is an autonomous build.** Adam is away. A fresh Claude Code session (the **orchestrator**) reads this plan and builds the whole mod with parallel Opus 5.5 agents at **xhigh** effort.
>
> The orchestrator tests everything itself and never stops to ask Adam. Every authorization it needs is in `AUTONOMY.md`, and every design answer is in `DESIGN.md`.
>
> If something is not covered, apply the decision policy in `AUTONOMY.md` §3, log it, and keep going.

**Read order for any session (fresh, resumed or after compaction):**

1. `CLAUDE.md`
2. this file
3. `CONVENTIONS.md`: canonical names, paths, protocols, sub-waves, and the gate/failure procedure. It **wins** over any package spec.
4. `AUTONOMY.md`
5. `../../state/BUILD_STATE.md` (the ledger)
6. `DESIGN.md` and `TESTING.md` as needed
7. package specs in `packages/` when briefing

## 0. Mission and definition of done

Build the mod described in `DESIGN.md` on Freelancer: HD Edition (Wine/Proton, Linux).

**The build is COMPLETE when all of the following hold:**

1. Every package in §6 is `MERGED` or `DEGRADED`. Degraded packages are logged in `state/DEGRADED.md` with the reason, the fallback shipped, and what a future session would need to finish them.
2. Gates 0a, 0b and 1, and milestones M1, M2 and M3 are `PASSED`, and the final gate F is `PASSED` (§7).
3. A modded play install `/home/user/freelancer/prefix-carrier` exists. `/home/user/freelancer/play-carrier.sh` launches it together with the copilot sidecar, and Adam's original `/home/user/freelancer/prefix` + `play.sh` are untouched and still work.
4. The public GitHub repo `expectbugs/freelancer-carrier-mod` holds the source, with a release tag `v1.0.0`.
5. `docs/BUILD_REPORT.md` summarizes what was built, what was degraded, test evidence, known issues and how to play. A push notification has been sent.
6. The first line of `state/BUILD_STATE.md` reads `BUILD_STATUS: COMPLETE`. The watchdog stops on this.

## 1. Ground truth (verified 2026-10-17)

| Thing | Value |
|---|---|
| Host | Gentoo, OpenRC, X11/XFCE on `:0`, RTX 3090, 32 GB RAM; sudo available (see AUTONOMY) |
| Play prefix (**never modify**) | `/home/user/freelancer/prefix`; HDE at `drive_c/Games/Freelancer HD Edition`; launcher `/home/user/freelancer/play.sh` |
| Wine | wine-proton 11.0.1 (`/usr/lib/wine-proton-11.0.1/bin/{wine,wineserver,winedbg}`), DXVK, WoW64 |
| HDE | v0.7.1.1, Story Mode, saves in `drive_c/users/steamuser/Documents/My Games/Freelancer/Accts/SinglePlayer/` |
| FLSpew log | `drive_c/users/steamuser/AppData/Local/Freelancer/FLSpew.txt` (per prefix) |
| Repo | `/home/user/freelancer/carrier-mod` (git; public remote created in P0-REPO) |
| Reference repos (read-only) | `/home/user/freelancer/refs/`: FLUF, FLSDK (inside FLUF/vendor), FLHook*, DiscoveryFLHook, FLHook-88Flak, Freelancer-Decomp, Librelancer, FLSharp, flplusplus, adoxa-*, StarportKnowledgeBase, HDE repo + installer + wiki, wine sources, universal-modder |
| FLUF binaries | `refs/FLUF-release-nightly-2026-10-16/FLUF.tar.xz` (pin) and `refs/FLUF-release-stable-2026-03-28/FLUF.tar.xz` (fallback) |
| Research (read-only, gitignored) | `/home/user/freelancer/carrier-mod/local/research/`: `00-brief.md`, `R1-fluf.md`, `R2-engine-api.md`, `R3-game-data.md` (+ `R3-data/`), `R4-lore-and-testloop.md`, `R5-sp-architecture.md`, `R6-copilot-sidecar.md`, `scratch/` (disassembly, IAT maps, tools) |
| Toolchain | clang-cl / lld-link / llvm-rc 22 at `/usr/lib/llvm/22/bin`; cmake, ninja, cargo, python3.13; xwin (to install) for the MSVC CRT/STL and Windows SDK |
| Claude CLI | `/home/user/.local/bin/claude` 2.1.302 |
| GitHub | `gh` authenticated; the token resolves to account **`expectbugs`** |

**Key research conclusions** (details in the R-files; verify in Phase 0):

- **SP architecture.** Single player runs `Server.dll` in-process on the main thread, once per frame.
  - Only the F1/Esc menu pauses the game.
  - Hooks fire with client id 1.
- **FLUF:**
  - Server event hooks work in single player, but there is **no server tick** there.
  - FLUF **refuses to load next to `jflp`, `flsharp`, `delaydisplay`, `mp3codec`, `storyfactions` and `callsign`**, all of which HDE ships.
  - Its nightly build is 404 MiB of image because of debug info, against a 2 GB address limit since the exe isn't large-address-aware.
  - It is AGPL-3.0.
- **Bases.**
  - Bases are static data with a fixed `system=`.
  - Launching requires the base's solar to be in space.
  - The campaign's Osiris is six separate bases.
  - Discovery and '88 Flak use proxy bases.
  - A runtime solar's visibility in single player is uncertain: FLUF's builder only sends the client packet in multiplayer.
- **Simulation.**
  - Systems without the player are not simulated: API-spawned NPCs freeze in place, and Content NPCs despawn beyond 2.5 km.
  - Capital AI: probably no cruise, local avoidance only, and some gates are `npc_locked`. API NPCs don't auto-jump; use `pub::SpaceObj::JumpIn`.
- **Saves** are plain text. Unknown keys are dropped on save, so mod state lives in sidecar JSON.
- **Nomad planet:** Planet Gammu (`Ew06_02_Base`) has no market today. Nomad battleship NPC definitions exist only in mission files.
- **Patrol and interdiction data** are extracted in `R3-data/` (6,608-row zone table, CD-capable fractions).

## 2. Architecture

```
Freelancer.exe (Wine, modded HDE profile in prefix-dev*/prefix-carrier)
 ├─ Platform layer  (Track A: FLUF + our FLUF module | Track B: our own dacom DLL)  ← chosen at Gate 0a
 │   hooks (server vtable, frame tick, launch check, launch pos, save/load), overlay UI, native buttons, keys
 ├─ carrier_endgame (our code; one DLL)
 │   src/logic/   engine-free C++ (compiles natively on Linux for unit tests)
 │   src/game/    engine adapters (spawn, AI, UI, persistence I/O, devbridge, IPC client)
 │   src/contracts/  interfaces frozen by ARCH packages
 └─ Server.dll / Common.dll / Content.dll (in-process; pub:: API)
Data pack (generated at deploy from YAML + the local install): INI additions, resource DLL (index detected), world.json, CMP hardpoint copies, global patches (level gating)
Copilot sidecar (Linux Python, 127.0.0.1:29170, NDJSON): STT, TTS, grammar, Claude CLI brain, SQLite memory
Harness (Linux): deploy, lanes, scenarios, playbot, soak, crash triage
```

**Platform abstraction (decided now, so it is independent of the track).** All game-facing code talks to `src/contracts/platform.hpp`:

- events: dock, launch, jump, damage, destroy, purchase, save, load
- tick
- overlay UI surface
- native button factory
- key input
- launch blocking and launch position

Track A implements it over FLUF; Track B implements it with our own hooks. Waves 1–5 never touch FLUF or raw hooks directly, except in `src/game/platform/`.

**Repo layout:**

```
CLAUDE.md README.md LICENSE KICKOFF.md .gitignore CMakeLists.txt
docs/plan/        this plan, DESIGN, AUTONOMY, TESTING, templates, packages/*.md
docs/design/      design docs produced during the build (CARRIERS.md, WINGMEN.md, ESCALATION.md, …)
docs/spec/        contracts in prose (ipc.md, devbridge.md, persistence.md, …) — written by ARCH packages
state/            BUILD_STATE.md (ledger), DECISIONS.md, ENGINE_FACTS.md, DEGRADED.md, gates/*.md
toolchain/        cmake toolchains, xwin setup, import checker
src/contracts/ src/logic/ src/game/ src/module/   C++
spikes/<id>/      Phase-0 spike code (kept for reference, not shipped)
sidecar/          Python copilot
data/             YAML source data (core/, carriers/, yards/, encounters/, pilots/, strings/)
gen/              generators (YAML + local install → overlay)
tools/            fltools (Python), wine guards (tools/bin), env.sh, watchdog, start-build, display-awake, check_public
harness/          deploy/run/lanes, fixtures, scenarios/*.yaml, playbot, soak
tests/            host C++ (doctest) + pytest
local/            gitignored: research, scratch, personal notes, heartbeat, watchdog log
build/ out/ vendor/   gitignored
```

## 3. Install profiles (Wine prefixes)

| Prefix | Purpose | Created by |
|---|---|---|
| `/home/user/freelancer/prefix` | Adam's play install. **Never touched.** Reflink-clone it only while no wine process uses it. | — |
| `prefix-dev-base-A` | Track A baseline: clone + HDE minus FLUF-forbidden DLLs + FLUF + test tweaks | P0-HARNESS |
| `prefix-dev-base-B` | Track B baseline: clone + HDE intact + test tweaks | P0-HARNESS |
| `prefix-lane-N` | Disposable per-run clones of the chosen baseline with the mod deployed (N = lane number) | harness |
| `prefix-carrier` | Final playable modded install for Adam | W5-SHIP |

Clones use `cp -a --reflink=always` (XFS reflink; instant).

**Test tweaks (dev and lane prefixes only):**

- flplusplus `save_in_directory = true`
- 1280×720 window
- keep-running-when-unfocused patch (`Freelancer.exe` @0x1B264C ← `BA 01 00 00 00 90`, after verifying the original bytes)
- `WINEDEBUG=fixme-all,+seh,+loaddll` in lane runs
- **Track B only:** jflp.dll @0x1528 `33→04` (JFLP is removed on Track A)
- **Track A only:** comment out the `callsign.dll` line in `freelancer.ini [Initial SP DLLs]`. Deleting the DLL instead would crash the game, because FLSharp's missing-DLL fix is gone on A.
- **Telling windows apart:** several lane windows are all titled `Freelancer`, so the harness identifies each lane's window by the PID of its wine process (P0-HARNESS)

## 4. Platform bake-off (Phase 0, decided automatically at Gate 0a)

| Item | Track A: FLUF | Track B: own DLL, HDE intact |
|---|---|---|
| Profile | HDE minus jflp/FLSharp/DelayDisplay/MP3codec/storyfactions/callsign, plus FLUF (pinned nightly, debug info stripped or LAA-flagged as needed) and FLUF's replacement modules | HDE untouched, plus our dacom `[Libraries]` DLL |
| Hooks | FLUF events | Own server-vtable patches for the ~15 events we need, frame tick detour (0x5B2890), launch check (0x4422B0), launch position (server+0x8420C), save/load hooks |
| UI | FLUF ImGui + vanilla-control API | Own overlay (D3D8/D3D9 hook via the dxwrapper→ReShade→DXVK chain, ImGui) + own native-control creation using known FL addresses |

**The checklist:** both tracks must run it under Wine, on lanes, fully automated.

1. Boots to the main menu.
2. Loads a fixture save.
3. A dock/undock/jump event hook fires in single player.
4. A frame tick runs in game time.
5. An overlay window renders while docked: screenshot plus vision check.
6. A native button appears in the base NavBar and its click is received.
7. Launch can be blocked and then allowed.
8. The undock position can be overridden.
9. The save hook writes a sidecar JSON, and the load hook reads it.
10. A 60-minute soak (fly, dock, jump, save, load, repeat) has no crash.
11. No new FLSpew ERROR lines versus the profile's baseline.
12. Address-space headroom stays at least 300 MB after loading a busy system (measured).
13. Track A only: list every HDE fix lost, with an assessment.

**Decision rule** (record it in `state/DECISIONS.md` and `state/gates/G0a.md`):

1. If both pass, choose **B**: it keeps HDE whole and drops the moving dependency.
2. If only one passes, choose that one.
3. If neither passes fully, choose the one with more items passing, weighting items 3, 7, 8 and 9 double. Then file the failing items as follow-up tasks in ARCH-0.

**Hard veto:**

1. If both tracks fail item 1 (boot) or item 2 (save load), give each track one fix attempt.
2. If both still fail, the build **halts** (AUTONOMY §4, "the game can't boot with the mod").

The track never changes after Gate 0a unless a later package proves the chosen track cannot deliver a must-have. In that case, log a decision, re-run the bake-off item, and switch only the platform layer.

## 5. How a wave runs (orchestration protocol)

For each wave, the orchestrator:

1. **Prepare.**
   1. Confirm the gate before the wave is `PASSED`.
   2. Run the wave's ARCH package if it has one, to freeze contracts.
   3. For every package now `READY` (all dependencies merged or degraded), fill `AGENT_BRIEF_TEMPLATE.md` from `packages/<ID>.md`, adding a **gate addendum**: chosen track, chosen base plan, relevant `ENGINE_FACTS.md` entries, frozen contract paths, and lane assignment.
   4. Save the brief to `state/briefs/<ID>.md` and commit it.
2. **Spawn.** Use the Agent tool, one agent per package, in parallel. Settings:

   | Setting | Value |
   |---|---|
   | `subagent_type` | `"general-purpose"` |
   | `model` | `"opus"` |
   | `effort` | `"xhigh"` (Adam explicitly asked for xhigh) |
   | `isolation` | `"worktree"` for code packages |
   | prompt | "Your brief: /home/user/freelancer/carrier-mod/state/briefs/<ID>.md. Read it fully and follow it." |

   - At most **6 implementation agents at once**, plus up to 3 reviewers.
   - Record agent name and id, package and start time in the ledger "Agents running" table.
3. **Monitor.**
   - Answer agent questions via SendMessage, using the decision policy.
   - Keep your own context lean: don't read agent transcripts, only their final reports.
4. **Review.** When an agent reports done:
   1. Save the report verbatim to `state/reports/<ID>-a<n>.md` (CONVENTIONS §10). Then spawn a reviewer, same settings, brief from `REVIEWER_BRIEF_TEMPLATE.md`. Save its verdict to `state/reports/<ID>-r<n>.md`.
      - Scenarios the author marked `DEFERRED(<sibling>)` are accepted only if that sibling is genuinely unmerged and in the same wave (CONVENTIONS §8).
   2. The reviewer audits the branch diff against the package spec, `DESIGN.md`, `ENGINE_FACTS.md`, the guardrails and `TESTING.md`, and re-runs the tests itself.
   3. Send its findings back to the original agent (SendMessage) to fix. Repeat until the reviewer passes it, or the attempt budget runs out (`AUTONOMY.md` §4).
5. **Merge.**
   1. Merge the package branch into `main` (no fast-forward; message `merge <ID>: <title>`).
   2. Run `harness/ci.sh` (host tests + build + data validation + public-safety check + the regression scenario subset). It must be green.
   3. Push to GitHub.
   4. Update the ledger to `MERGED` and append facts to `state/ENGINE_FACTS.md`.
6. **Integration pass, then gate.**
   1. After the last merge of a (sub-)wave, run every `DEFERRED` scenario from that wave on main. Failures become `FIX-<n>` packages.
   2. When all of a wave's packages are merged or degraded, run the gate procedure (§7, CONVENTIONS §10) and write `state/gates/<gate>.md`.
   3. On pass: tag, push, send a push notification, and start the next wave.
   - Sub-waves (CONVENTIONS §8) start as soon as their dependencies merge. Don't wait for the whole wave.
7. **Heartbeat.** Run `date -Is > local/heartbeat` at the start and end of every turn, at least every 30 minutes of activity. The watchdog nudges you if it goes stale.

**Waiting:** while agents run, end your turn; completion notifications re-invoke you. To wait on a timer (rate limits, long soaks), run `sleep N` with `run_in_background: true` and end the turn.

## 6. Packages

Specs live in `docs/plan/packages/<ID>.md`. Types:

- **impl:** builds code or data.
- **spike:** in-game experiment that produces facts.
- **arch:** freezes contracts and specs.
- **design:** design doc plus data.
- **test:** bot playtest or soak.

"Owns" is the set of paths the package may modify. Everything else is read-only to it. "Deps" must be `MERGED` or `DEGRADED` before the package starts.

**Ownership conventions** (they apply to every row):

- **Tests and scenarios.** A package also owns:
  - test and scenario subfolders inside its owned source dirs (`<owned dir>/tests/`, `<owned dir>/scenarios/`);
  - `tests/host/<area>/`, `harness/scenarios/<area>/` and `harness/rubrics/<id>_*`, where `<area>` is its lower-case short name.

  The CMake root and the scenario runner discover these recursively, as ARCH-0 sets up and W1-HARNESS's runner does. Milestone packages own `harness/playbot/journeys/<id>/`.
- **Exact owned paths.** The table below lists each package's primary paths. The authoritative per-file map is `docs/plan/OWNERSHIP.md`, written by ARCH-0 and updated only by ARCH-1/2/3 or the orchestrator. ARCH packages may also edit OWNERSHIP.md and the "Gate-time addendum" sections of next-wave specs.
- **Shared generator tree.**
  - `gen/framework/` belongs to P0-DATATOOLS and `gen/models/` to W2-LOADOUT. W1-DATA owns the rest of `gen/`.
  - Later packages add generator **plugins** under `gen/plugins/<area>/` through W1-DATA's plugin interface.
- **Strings.** Per-area strings live in `data/<area>/strings.yaml` (e.g. `data/carriers/strings.yaml`). W1-DATA's pipeline merges every `data/**/strings*.yaml`.
- **Tuning.** Balance values that a later package must tune live in `data/tuning/<area>.yaml`, owned by that package and layered over the design defaults.
- **Harness growth.**
  - P0-HARNESS creates the Phase-0 harness: `lane.sh`, `deploy.sh`, `run.sh`, `config.sh`, `verdict.py`/`triage.py`, `fixtures/`, `spew_allow.txt` and `devbridge/` with its PROTOCOL.md.
  - It tests (does not own) `tools/env.sh`, `tools/bin/` and `tools/display-awake.sh`, which are orchestrator-owned (CONVENTIONS §14).
  - From Wave 1, W1-HARNESS owns `harness/` (except `harness/devbridge/`, which W1-CORE promotes, and the per-package scenario folders above), and may modify the Phase-0 scripts.
- **Phase-0 extras** (from the specs):
  - P0-TOOLCHAIN owns `src/module/hello_*`, `src/module/loadtest`, `src/logic/core/flhash*` and `harness/ci.d/10-*`/`20-*`.
  - P0-DATATOOLS owns `gen/run.py`, `gen/example_strings/` and `harness/ci.d/30-*`.
- **Files that change hands.** `README.md` passes from P0-REPO to W5-SHIP in Wave 5. Gate F owns `docs/BUILD_REPORT.md` and `state/gates/F.md`.

### Phase 0: foundation, bake-off, spikes

| ID | Type | Title | Deps | Owns |
|---|---|---|---|---|
| P0-REPO | impl | Public GitHub repo, AGPL license, public-safety checker + pre-commit hook, CI entry `harness/ci.sh` skeleton | — | `.github/`, `tools/check_public.py`, `.githooks/`, `harness/ci.sh`, `README.md`, `LICENSE` |
| P0-TOOLCHAIN | impl | xwin MSVC SDK/CRT, clang-cl i686 CMake toolchain, vendor fetch (pinned FLUF pkg, FLSDK, reflect-cpp), host-native doctest build, import checker | — | `toolchain/`, `CMakeLists.txt`, `vendor/` (gitignored), `tests/host/` scaffold |
| P0-HARNESS | impl | Dev baselines A and B, deploy/run/lane scripts, fixture-save generator, crash triage, baseline spew, display keep-awake, headless-lane evaluation (gamescope), lane locking, telling apart concurrent "Freelancer" windows per lane, the Phase-0 devbridge core and protocol | — | `harness/` (tests `tools/env.sh`, `tools/bin/`, `tools/display-awake.sh`, which are orchestrator-owned per CONVENTIONS §14) |
| P0-DATATOOLS | impl | `fltools` Python: INI read/write, CreateID and faction hash, PE resource reader/writer, resource-DLL builder, UTF/CMP reader-writer (hardpoint add), cross-ref validator, hash-collision scan, idempotent patch framework, `world.json` export | — | `tools/fltools/`, `gen/framework/`, `tests/py/` |
| P0-SIDECAR | impl | Sidecar skeleton: NDJSON server, protocol v1 (`docs/spec/ipc.md`), fake-game client, venv with CUDA-12 Whisper libs, STT/TTS offline smoke | — | `sidecar/`, `docs/spec/ipc.md` |
| P0-TRACK-A | spike | Run the §4 checklist on FLUF | P0-TOOLCHAIN, P0-HARNESS | `spikes/track_a/` |
| P0-TRACK-B | spike | Run the §4 checklist on our own DLL | P0-TOOLCHAIN, P0-HARNESS | `spikes/track_b/` |
| **G0a** | gate | Choose the track (§4) | P0-TRACK-A, P0-TRACK-B | `state/gates/` |
| S-BASE | spike | Runtime solar visibility (3 spawn paths); dockable runtime solar; undock placement; base re-pointing (Plan A) vs per-system proxy + reload (Plan B); **fleet scale: at least 8 carriers, including 2 of the same look in one system (Plan B)**; save/load mid-docked; purchase transaction from a custom panel | G0a, P0-DATATOOLS | `spikes/s_base/` |
| S-NPC | spike | Capital NPC travel (speed, cruise, avoidance), gate approach + JumpIn visuals, npc_locked links, frozen systems + respawn on return, freeze/thaw of a fight, scripted nanobot/battery use (player + NPC), damage/destroy hooks, loot bundling, Nomad battleship/gunboat spawn | G0a, P0-DATATOOLS | `spikes/s_npc/` |
| S-UI | spike | Base-menu button + panel, base info text override, popups/NN messages/comms/custom sound playback, waypoints, Wine TCP loopback, PTT key polling (VK 110 + XBUTTON, real XTEST input under the input lock) | G0a, P0-DATATOOLS, P0-SIDECAR | `spikes/s_ui/` |
| S-LOADOUT | spike | Runtime loadout composition for solars and ships; CMP hardpoint addition (turret mounts and fires); capital shield generator on NPC/solar; NPC munition consumption tracking and depletion enforcement; capital missile/torpedo launchers on carrier | G0a, P0-DATATOOLS, S-BASE | `spikes/s_loadout/` |
| S-PERF | spike | Scale test: 10/25/50/100/200 friendly fighters + enemies; FPS, AI behavior, crash; `Act_PlayerEnemyClamp` effect; followers across jumps; address-space growth. Measurements run under the exclusive `--perf` lock (CONVENTIONS §7) | G0a, P0-DATATOOLS | `spikes/s_perf/` |
| **G0b** | gate | Every spike question answered with evidence; Plan A/B chosen; `ENGINE_FACTS.md` complete | all S-* | `state/` |
| ARCH-0 | arch | Freeze `src/contracts/*` (platform, clock, events, persistence, spawn, AI, UI kit, world, inventory, carrier model, encounter, reflex, wingmen, yard) + `docs/spec/*` + skeleton module that builds; assign code-ownership map | G0b | `src/contracts/`, `docs/spec/`, `src/module/` skeleton, `docs/plan/OWNERSHIP.md` |

### Wave 1: platform

| ID | Type | Title | Deps | Owns |
|---|---|---|---|---|
| W1-PLATFORM | impl | Production platform layer for the chosen track (from the spike code), implementing `platform.hpp` | ARCH-0 | `src/game/platform/` |
| W1-CORE | impl | Game clock, event bus, next-tick queue, per-save JSON persistence (versioned, migrations), config, logging, **production devbridge** (promotes the Phase-0 core; same wire protocol; adds `time.skip` and the core verbs), campaign-complete detection | W1-PLATFORM, W1-HARNESS (sub-wave 1b) | `src/logic/core/`, `src/game/core/`, `src/game/devbridge/`, `harness/devbridge/` |
| W1-WORLD | impl | World model from `world.json`: system graph (locked/npc-locked), hazards, lanes, zones; route planner (multi-hop, in-system waypoints avoiding hazards and lanes); safe-stop and planet-approach finder; route exposure (C++ port, golden tests vs `R3-data/tools/route_exposure.py`); the 10 sample routes (TESTING §Metrics) | ARCH-0, P0-DATATOOLS | `src/logic/world/`, `tests/host/world/` |
| W1-SPAWN | impl | Validated spawn service (ships, solars, loot), ownership registry, freeze/thaw snapshots, AI helpers (waypoints, follow, attack-by-rep, jump, stop) | W1-PLATFORM, W1-HARNESS (sub-wave 1b) | `src/game/spawn/`, `src/game/ai/` |
| W1-UI | impl | UI kit (FL-styled windows, lists, buttons, progress, text input), NavBar button helper, notifications (NN, popup, toast, chat line), text service (IDS + overrides), waypoint helper | W1-PLATFORM, W1-HARNESS (sub-wave 1b) | `src/game/ui/kit/`, `src/game/text/` |
| W1-DATA | impl | Generator pipeline (YAML + local install → overlay) with a **plugin interface** (`gen/plugins/<area>/`); deploy integration; resource DLL (merges `data/**/strings*.yaml`); `world.json`; **global level-gating removal patch (D-2.1)**; carrier base data per the S-BASE plan; Nomad boss NPC definitions (from the mission-local npcships/loadouts); the `fcm_salvage_pod` lootable good (D-8.4); the optional keymap patch freeing numpad minus (D-11.3); audio-INI registration for generated voice-line WAVs | ARCH-0, P0-DATATOOLS | `gen/` (except `gen/framework/`, `gen/models/`), `data/core/`, `data/strings/` |
| W1-INVENTORY | impl | Inventory/economy model (carrier holds, stocks, transactions, wages ledger, prices) + adapters (credits, cargo transfer) | ARCH-0 | `src/logic/economy/`, `src/game/economy/` |
| W1-CARRIER-DESIGN | design | Carrier classes × tiers × looks, slots, upgrade catalogs per yard, prices, operating costs; host balance simulator; `docs/design/CARRIERS.md` | ARCH-0 | `data/carriers/`, `data/yards/`, `docs/design/CARRIERS.md`, `src/logic/balance/` |
| W1-HARNESS | test | Scenario runner (YAML), assertion library, regression suite, **playbot** framework (agent-driven play with screenshots and vision rubric), soak runner, metrics extraction | ARCH-0 | `harness/scenarios/`, `harness/playbot/`, `harness/soak/` |
| W1-SIDECAR | impl | STT, TTS, playback, grammar fast path, persona config, SQLite memory, latency instrumentation, offline rendering of canned voice lines | P0-SIDECAR, S-UI | `sidecar/` |
| **G1** | gate | Wave 1 merged; CI green; 30-minute soak clean | all W1 | |
| ARCH-1 | arch | Refine contracts for Wave 2 (carrier model, encounter, loadout, yard, reflex) from Wave-1 reality | G1 | `src/contracts/`, `docs/spec/` |

### Wave 2: carrier v1 and copilot reflexes

| ID | Type | Title | Deps | Owns |
|---|---|---|---|---|
| W2-ENCOUNTER | impl | Shared encounter system (definition/trigger/placement/persistence/outcome), freeze/thaw fights, first escalation proof event | ARCH-1 | `src/logic/encounter/`, `src/game/encounter/`, `data/encounters/` |
| W2-CARRIER-LOGIC | impl | 7-state machine × fleet, travel simulation, orders, persistence schema | ARCH-1 | `src/logic/carrier/` |
| W2-CARRIER-GAME | impl | Spawn/despawn of the carrier solar, base binding (Plan A/B), launch block, undock placement, docking rules, load restore, multi-carrier | W2-CARRIER-LOGIC, W2-LOADOUT (sub-wave 2b) | `src/game/carrier/` |
| W2-LOADOUT | impl | Runtime loadouts from installed upgrades, CMP hardpoint generation, munition tracking/depletion, auto-launcher control | ARCH-1 | `src/game/loadout/`, `gen/models/` |
| W2-YARD | impl | Carrier Yard panel: buy (class, configure, name), retrofit within 10 km, per-yard catalogs, fleet cap reporting | W2-CARRIER-GAME (sub-wave 2c) | `src/logic/yard/`, `src/game/ui/yard/` |
| W2-CARRIER-UI | impl | Aboard: travel menu (points, adjacent systems, multi-hop), progress/ETA, Stop, status, hold transfer, quartermaster resupply; in-space carrier command panel + hotkey (escort orders later) | W2-CARRIER-GAME (sub-wave 2c) | `src/game/ui/carrier/` |
| W2-REFLEX | impl | Reflex layer (player + carrier), policy and clamps, pre-rendered voice lines, in-game IPC client (worker thread), PTT, events/snapshots | ARCH-1 | `src/logic/reflex/`, `src/game/reflex/`, `src/game/ipc/` |
| **M1-PLAYTEST** | test | Bot playthrough #1 (TESTING.md §M1) + 60-minute soak | all W2 | `state/gates/M1.md` |

### Wave 3: danger and tiers

| ID | Type | Title | Deps | Owns |
|---|---|---|---|---|
| ARCH-2 | arch | Contracts for ambush, escort, nomad, loss | M1 | `src/contracts/`, `docs/spec/` |
| W3-AMBUSH | impl | Odds model (exposure × interdiction × rep × cargo ≤1.5), rolls, aboard/escort/away outcomes, distress UX, one-per-carrier | W3-ESCORT, W3-LOSS (sub-wave 3b) | `src/logic/ambush/`, `src/game/ambush/` |
| W3-ESCORT | impl | Escort travel with a real NPC capital, gates, Away hand-off and return, Stop→base | ARCH-2 | `src/game/escort/` |
| W3-NOMAD | impl | Nomad boss (roam, seek player on Nomad engagement, respawn 4 days), unlock flag, Gammu yard enablement | ARCH-2 | `src/game/nomad/`, `data/encounters/nomad/` |
| W3-LOSS | impl | Carrier destruction, bundled loot (everything aboard), hangar auto-launch, cleanup, crew loss | ARCH-2 | `src/game/loss/` |
| **M2-PLAYTEST** | test | Bot playthrough #2 + 2-hour soak + ambush-frequency measurement | all W3 | `state/gates/M2.md` |

### Wave 4: crew and endgame

| ID | Type | Title | Deps | Owns |
|---|---|---|---|---|
| ARCH-3 | arch | Contracts for wingmen, hiring, brain, escalation hooks | M2 | `src/contracts/`, `docs/spec/` |
| W4-WINGMEN | impl | Crew and hired wingmen in space: spawn, follow, formations, focus, retreat, guard carrier, bays launch/recover, jumps/docks, away-escort freeze | ARCH-3 | `src/logic/wingmen/`, `src/game/wingmen/` |
| W4-HIRING | impl | Bar hiring panel, candidate generation per bar/faction, fees and wages, roster panel, permadeath, scale warning | W4-WINGMEN (sub-wave 4b) | `src/logic/hiring/`, `src/game/ui/hiring/`, `data/pilots/` |
| W4-BRAIN | impl | Claude CLI brain (Opus 5.5, low effort, no tools), orders→policy/wing commands, banter scheduler, personas, memory | ARCH-3 | `sidecar/brain/` |
| W4-ESCALATION-DESIGN | design | Design the faction-influence escalation system + engine spikes (base takeover feasibility); `docs/design/ESCALATION.md`; split into build packages `W4-ESC-*` with specs | ARCH-3 | `docs/design/ESCALATION.md`, `spikes/s_faction/`, `docs/plan/packages/W4-ESC-*.md` |
| W4-ESC-* | impl | Packages defined by the design agent (the orchestrator adds them to the ledger) | W4-ESCALATION-DESIGN | per spec |
| **M3-PLAYTEST** | test | Bot playthrough #3 + 3-hour soak + army-scale check | all W4 | `state/gates/M3.md` |

### Wave 5: harden and ship

| ID | Type | Title | Deps | Owns |
|---|---|---|---|---|
| W5-SOAK | test | Long soaks (≥ 6 h cumulative, varied journeys), crash triage and fixes via follow-up packages, perf and memory | M3 | `harness/soak/`, `state/gates/` |
| W5-COMPAT | impl | Save compatibility (pre-mod saves, every carrier state × save/load), schema migrations, uninstall/relocate tool, HDE option variants (Open SP) | M3 | `tools/uninstall/`, `tests/` |
| W5-SHIP | impl | `prefix-carrier` install, `play-carrier.sh` (starts sidecar + game), player guide, README, release `v1.0.0` (verify FLSDK import-lib licensing before publishing binaries) | W5-SOAK, W5-COMPAT | `ship/`, `docs/PLAYER_GUIDE.md`, `README.md`, `/home/user/freelancer/play-carrier.sh` |
| **F** | gate | Final gate + `docs/BUILD_REPORT.md` + notification | all | `docs/BUILD_REPORT.md`, `state/gates/F.md` |

Bug-fix packages created during the build are named `FIX-<n>`. They get their own spec in `state/briefs/` and the usual review loop.

## 7. Gates (all automated)

Every gate writes `state/gates/<G>.md` with its evidence: commands run, pass/fail per criterion, and paths to logs and screenshots.

| Gate | Pass criteria |
|---|---|
| G0a | §4 decision recorded with the checklist results for both tracks |
| G0b | Every spike question answered VERIFIED-in-game or explicitly "not possible" with the fallback chosen. Plan A/B chosen. `ENGINE_FACTS.md` updated with evidence paths. |
| G1 | All W1 merged or degraded; `harness/ci.sh` green; the regression suite green on 2 lanes; a 30-minute soak with no crash and no new ERROR spew |
| M1 | TESTING.md §M1 bot playthrough passes every step; 60-minute soak clean; metrics within target ranges or tuned |
| M2 | TESTING.md §M2 passes; 2-hour soak clean; ambush-frequency measurement within targets |
| M3 | TESTING.md §M3 passes; 3-hour soak clean; army-scale report written |
| F | TESTING.md §F (full regression, a 6-hour cumulative soak, save-compat matrix, a fresh install from scratch into `prefix-carrier` that boots and plays); report written; release pushed |

The detailed failure, quarantine and FIX-package procedure is in CONVENTIONS §10.

**Gate F is run by the orchestrator itself.** Agents may only collect evidence. The orchestrator then:

1. verifies `tools/play_prefix_manifest.sh verify`;
2. publishes `v1.0.0` on the exact SHA F tested (CONVENTIONS §11);
3. writes the report;
4. sets `COMPLETE`.

**A failing gate never blocks forever.**

1. Open `FIX-*` packages for the failures and re-run the gate.
2. After 3 failed gate runs on the same criterion, apply the degrade policy (`AUTONOMY.md` §4) to the feature at fault, record it, and pass the gate with a documented exception.

## 8. Risks and fallbacks (pre-decided)

| Risk | Fallback (apply without asking) |
|---|---|
| Neither track passes the bake-off | Pick by weighted score; fill gaps in W1-PLATFORM. If the overlay fails everywhere, use native FL controls plus popups/infocards only for UI (degraded look, full function). |
| Runtime solar invisible in single player | Call the game's own CreateSolar without FLUF's packet patch. Else keep a hidden pre-placed carrier object per system and respawn it in place. |
| Base re-pointing fails (Plan A) | Plan B: per-system proxy bases per look, with an "arrival" reload when the system changes while docked |
| Runtime loadout composition fails | Pre-generate the loadout variants needed (class × tier × installed combos, compressed by slot templates). If combinatorics explode, limit retrofit to discrete packages per slot. |
| Capital AI flies badly | Our own steering: dense waypoints and our own speed. Move the ship directly when no player is within 10 km. Travel time stays simulated. |
| Munition depletion can't be enforced on NPC launchers | Model munitions as an operating-cost stock consumed per engagement minute; disable launchers via loadout swap when empty |
| Army scale crashes the engine | Keep no cap (D-1.6) but warn at the measured threshold. Stagger spawns. Despawn idle followers far away and respawn on approach. |
| Base takeover impossible in the engine | ESCALATION uses proven levers only (patrol presence, encounters, rep, markets via overrides, infocard text). Design within them. |
| Usage limits / API outages | Wait with background sleeps; the watchdog resumes. Never skip testing to "save" quota. |
