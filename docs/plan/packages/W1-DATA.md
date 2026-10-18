# W1-DATA: generator pipeline, data pack v1, global level-gating removal, carrier bases, Nomad boss NPCs

- **Type:** impl
- **Wave:** 1
- **Depends on:** ARCH-0 (schemas `docs/spec/data_schemas.md`, `world_json.md`, `text_ids.md`, plus the placeholder YAML), P0-DATATOOLS (`tools/fltools`, `gen/framework`, `gen/run.py`); sub-wave 1a (CONVENTIONS §8) → **Unblocks:** everything that needs mod data in game (W1-CORE scenarios, W1-SPAWN, W1-UI text, all of Wave 2+)

## Goal

A deterministic, idempotent generator turns:

- our committed YAML (`data/`), plus
- the **local** Freelancer HD Edition install (never committed),

into the mod's deployable data overlay. The overlay contains new INI files, marker-block patches to hard-coded INIs, our text resource DLL, `world.json`, and the global "no level requirements" patch.

The output must be byte-identical across runs given the same inputs. It must be reversible (uninstall), and it must validate cleanly: no dangling references, no hash collisions, IDS in range.

## Requirements

- **REQ-W1-DATA-1: Overlay discipline** (D-1.1, BUILD_PLAN §1, R4 §A2.1/§A2.5).
  - New typed content goes in **new files appended** to `freelancer.ini [Data]` keys that accept several files:
    - `equipment = equipment\fcm_equip.ini`
    - `goods = equipment\fcm_goods.ini`
    - `ships = ships\fcm_shiparch.ini`
    - `loadouts = ships\fcm_loadouts.ini`, `solar\fcm_loadouts.ini`
    - `markets = equipment\fcm_market_*.ini`
  - Hard-coded single-path INIs are patched **in place with marker blocks**:
    - `universe.ini`
    - `solar\solararch.ini` (the KB marks multi-file `solar`/`universe` as "yes?" (UNVERIFIED); safest is to append blocks)
    - `MISSIONS\mbases.ini`, `MISSIONS\npcships.ini`, `MISSIONS\faction_prop.ini`
    - `UNIVERSE\missioncreatedsolars.ini`
    - `INTERFACE\infocardmap.ini`
    - `initialworld.ini` (only if a new faction or group is ever needed; avoid it)
    - system INIs (only if Plan B needs proxy objects per system)
  - Marker blocks look like `; >>> carrier-mod <version> <block-id>` … `; <<< carrier-mod <block-id>`.
  - The patcher records SHA-256 before and after and refuses unknown base hashes, unless the file was already patched by us.
  - Every nickname we add starts with `fcm_` (CONVENTIONS §2). The hash-collision scan runs on every build.
- **REQ-W1-DATA-2: Remove level requirements everywhere** (D-2.1).
  - In every `market_*.ini` that `freelancer.ini [Data] markets` lists (HDE: `market_misc.ini`, `market_ships.ini`, `market_commodities.ini`, plus ours), set field 2 of every `MarketGood` line (`marketgood = <nick>, <level_req>, <rep_req>, <min_stock>, <max_stock>, <news-scroll exclude 0/1>, <price_mult>[, extra]`; R3 §5) to `0`.
  - Keep every other field byte-identical, including the reputation requirement and case (HDE writes `MarketGood`).
  - Lines are rewritten through the marker-aware patcher with a full backup.
  - Example: the Eagle at Freeport 9 `gf6_package, 30, -1, 1, 1, 0, 1, 1` becomes `gf6_package, 0, -1, 1, 1, 0, 1, 1`.
  - Report counts: lines changed per file, ships and equipment affected.
- **REQ-W1-DATA-3: Text resource DLL** (D-15.1, R4 §A2.2–A2.4).
  - `data/**/strings*.yaml` → per-entry UTF-16LE files (HTML infocards: `FF FE` BOM + `<RDL><PUSH/><TEXT>…</TEXT><PARA/><POP/></RDL>`; names: STRINGTABLE, lang 1033) → `.rc` → `llvm-rc /l 0x409` → `lld-link /dll /noentry /machine:x86 /out:CarrierText.dll`.
  - Append `DLL = CarrierText.dll` to `freelancer.ini [Resources]` **after the last existing entry**.
  - **Detect the index at deploy time** by counting `[Resources]` entries (HDE 0.7.1.1 → index 8 → IDS `524288 + local_id`; local id 0 is reserved).
  - Write `text_ids.json` (key → IDS), allocated per `docs/spec/text_ids.md`: the generated copy goes to `$FLMOD_LOCAL/gen/text_ids.json`, and a deployed copy goes into the install for the module.
  - **Inputs:** every `data/**/strings*.yaml`, e.g. `data/strings/`, `data/carriers/strings.yaml`, later `data/pilots/strings.yaml`. Key namespaces per CONVENTIONS §2; duplicate keys across files are a build error.
  - Validate with `llvm-readobj --coff-resources`. Never touch HDE's own resource DLLs (the installer swaps `*_vanilla.dll` variants).
- **REQ-W1-DATA-4: `world.json`.** Run the P0-DATATOOLS exporter against the deployed install (after patches) and write `world.json` per `docs/spec/world_json.md` to `$FLMOD_LOCAL/gen/world.json` (plus a deployed copy for the module). It includes the IDS of the text DLL index and `locked_gate`/`npc_locked_gate` lists from `initialworld.ini [locked_gates]`. W1-WORLD consumes it.
- **REQ-W1-DATA-5: Carrier archetypes from `data/carriers/*.yaml`** (schema by ARCH-0; real values from W1-CARRIER-DESIGN, placeholder values until it merges). For each look, class and tier, generate:
  - **A solar archetype** (`fcm_carrier_<look>_<class>_<tier>_solar`) cloned from the vanilla solar of the same model:
    - `l_dreadnought`, `b_battleship`, `k_battleship`, `r_battleship`, `o_osiris`, or a liner station archetype (e.g. `luxury_liner`) for Trade Carriers;
    - type STATION;
    - **finite** `hit_pts` per class×tier (vanilla dockable battleships use 1e36, i.e. invulnerable; the Osiris solar uses 100,000);
    - docking spheres kept from the source: berth `HpDockMountA`, moors B/C;
    - `ids_name`/`ids_info` from our text DLL;
    - a destructible flag and explosion and fuse appropriate for capital death. Never use a `destroy_root` fuse on a dockable base (R4 §A1.4 item 4).
  - **Game data copied from the install.** All vanilla values this step needs (model paths, docking spheres, base hit points, engine stats) are read from the **local install at deploy time**. Committed YAML holds only our design values plus vanilla nicknames as references (CONVENTIONS §12).
  - **A ship archetype** (`fcm_carrier_<look>_<class>_<tier>`), cloned from `shiparch.ini` (`li_dreadnought`, `br_battleship`, `ku_battleship`, `rh_battleship`, `or_osiris`, `ge_liner`), for escort mode and for under-attack-as-ship. Adds:
    - `nanobot_limit` / `shield_battery_limit` (capitals have none in vanilla; R3 §4.1);
    - `hold_size`;
    - `hit_pts`;
    - engine and steering per class speed.
  - **Base loadouts** per tier and class (turrets on vanilla hardpoints only, with extended hardpoints left to W2-LOADOUT) and capital engines (`ge_lbd/bb/kb/rb_engine_01`).
- **REQ-W1-DATA-6: Carrier bases, both plans.** The orchestrator's addendum says which plan G0b chose. Implement both behind a generator switch.
  - **Plan A (re-point):** one `[Base]` per **interior variant**:
    - look × service package (e.g. `fcm_cbase_li_core`, `fcm_cbase_li_command`, `fcm_cbase_osiris_nomad`), each with `system = <a home system>` (rewritten at runtime);
    - `file = Universe\Systems\FCM\Bases\<base>.ini` (BaseInfo + rooms copied from the vanilla interior: `li_05_*` Liberty, `br_04_*` Bretonia, `ku_04_*` Kusari, `rh_04_*` Rheinland, `li_06_bar` + `li_05` deck for the Osiris, liner rooms for Trade Carriers);
    - `[MBase]` entries with bartender, trader and equipment NPCs where services exist;
    - market entries for services;
    - `infocardmap` pairs;
    - `missioncreatedsolars.ini` entries if FLSharp's dynamic solar infocards are in use (Track B; R3 §1.3).
  - **Plan B (proxy per system):** the same set **per reachable system**: `fcm_cbase_<sys>_<variant>`, with `system = <sys>`, for all systems reachable in free play (exclude St*, FP7). Optionally a hidden proxy `[Object]` per system ('88 Flak pattern) if S-BASE proved it necessary for launch.
    - Count and report the total bases. If more than 400, collapse service variants into fewer interiors and report the decision.
  - A dockable base needs a `universe.ini [Base]`, a BaseInfo file, rooms, an `mbases [MBase]`, market lines, `infocardmap`, and `strid_name` consistent with the solar's `ids_name` (R4 §A2.3; a missing universe entry gives a black screen).
- **REQ-W1-DATA-7: Nomad boss NPC definitions** (D-12.2). Vanilla Nomad capitals exist only in mission-local npcships (`MISSIONS/M10|M12|M13/npcships.ini`). Their loadouts and pilots, however, are **global** (VERIFIED: `SHIPS/loadouts_special.ini` defines `MSN10_Nomad_Gunboat` (l.799), `MSN12_Nomad_Gunboat` (l.813), `MSN10_Nomad_Battleship` (l.827) and `MSN13_Nomad_Battleship` (l.873); `pilots_story.ini` defines the MSN pilots; global `npcships.ini` `fc_n_no_fighter_d19` already uses pilot `MSN13_Nomad_Fighter`).
  - Add global `[NPCShipArch]` blocks to `MISSIONS/npcships.ini` (marker block):
    - `fcm_nomad_battleship_boss`: `ship_archetype = no_battleship`, `loadout = MSN13_Nomad_Battleship` (15× `nomad_turret01_mark01` + cloak), `pilot = MSN13_Nomad_Battleship`, `state_graph = CRUISER`, `level = d25`, `npc_class = unlawful, CRUISER, d25`.
    - `fcm_nomad_gunboat_escort`: `no_gunboat`, `MSN12_Nomad_Gunboat`, `pilot = MSN10_Nomad_Gunboat`, `state_graph = GUNBOAT`, `d22`.
    - Fighters reuse `fc_n_no_fighter_d19`.
  - Exact pilot names must be verified to exist (validator). The battleship's hull may be raised with an `armor_scale` equipment in a `fcm_` loadout copy if W3-NOMAD needs it (leave a hook).
- **REQ-W1-DATA-8: Gammu market hook.** Generate an empty-but-valid `fcm_market_gammu` section placeholder. W3-NOMAD fills it. Planet Gammu (`Ew06_02_Base`) has **no** `[BaseGood]` today (R3 §2.4).
- **REQ-W1-DATA-9: Deploy integration.** The entry point is **`gen/run.py`**. P0-DATATOOLS created it; this package owns it from Wave 1. Subcommands:
  - `gen/run.py build --install <HDE dir> --plan A|B --track A|B [--out <dir>]` writes the overlay plus `manifest.json` (inputs and outputs hashed) to `$FLMOD_LOCAL/gen/out/<input-hash>/` by default;
  - `gen/run.py deploy --prefix <lane prefix>` = build against that lane's pristine HDE dir, then install the overlay and run the patchers into the lane. `harness/deploy.sh` calls this (W1-HARNESS wires it in the same sub-wave; until then, test it by calling it directly);
  - `gen/run.py validate`;
  - `gen/run.py uninstall --prefix <prefix>`, which reverses every patch from the recorded backups and hashes.

  `gen/build.py` stays as a thin alias of `gen/run.py build`, because TESTING §CI names it.
- **REQ-W1-DATA-12: Generator plugin interface** (BUILD_PLAN §6 conventions). Later packages add generators under `gen/plugins/<area>/`, which they own.
  - Each plugin is a Python module with `register(pipeline)`, hooking named stages: `inputs`, `ini_append`, `ini_patch`, `strings`, `audio`, `models`, `validate`.
  - Users: W2-REFLEX (voice lines), W2-LOADOUT (`gen/models/` plugs in here), W3-NOMAD, W4-*.
  - Document the interface in `gen/plugins/README.md`, with one example plugin and a test.
- **REQ-W1-DATA-13: Salvage pod good** (D-8.4). Generate `fcm_salvage_pod`:
  - a lootable cargo good with a crate appearance cloned from a vanilla loot crate;
  - an IDS name and infocard;
  - no market listing.

  W3-LOSS fills pods with manifests at runtime. Validate that it can be spawned as loot (`DEFERRED(W1-SPAWN)` for the in-game check).
- **REQ-W1-DATA-14: Push-to-talk keymap option** (D-11.3). The default push-to-talk key, numpad period (VK 110), needs no patch.
  - When the local copilot config sets `ptt_key: numpad_minus`, patch `DATA/INTERFACE/keymap.ini` in a marker block to unbind VK 109 (and its SHIFT variant) from the hidden `USER_ZOOM_IN`.
  - Off by default. Reversible by uninstall.
- **REQ-W1-DATA-15: Voice-line audio registration.**
  - Inputs: `data/audio/*.yaml`, owned by W2-REFLEX, listing sound nicknames `fcm_vo_<speaker>_<line>` with text and voice; and WAVs rendered offline by the sidecar (`W1-SIDECAR`'s renderer) into `$FLMOD_LOCAL/gen/voice/`.
  - Generate `DATA/AUDIO/fcm_voice.ini` `[Sound]` entries, appended through a new `sounds = audio\fcm_voice.ini` line in `freelancer.ini [Data]`, and copy the WAVs into the deployed install. Never commit them.
  - A missing WAV skips that entry with a warning.
- **REQ-W1-DATA-16: `prices.json`** for W1-INVENTORY. At deploy time, compute per base and good the effective price (`goods.ini` price × market multiplier) from the local install, and write `$FLMOD_LOCAL/gen/prices.json` plus a deployed copy for the module. It is game-derived, so never committed.
- **REQ-W1-DATA-10: Validation in CI.**
  - Cross-references: every archetype, loadout, equipment, good, base, room, IDS, pilot, faction and NPCShipArch referenced exists.
  - CreateID and faction-hash collision scans (24,877 vanilla nicknames, 0 collisions; faction hash is 16-bit, so ~1/1200 per new faction, R4 §A1.3).
  - Systems keep ≤ 10 jump objects.
  - Market lines are well-formed.
  - `tools/check_public.py` passes: generated output never lands in committed paths.
  - Owns CI stage `harness/ci.d/40-data-validate.sh` (CONVENTIONS §5); `harness/ci.sh --only data-validate` runs it.
- **REQ-W1-DATA-11: Public safety.** `data/` contains only our own authored YAML. Anything copied from game files is produced at deploy time into the overlay dir (gitignored). Never copy vanilla text into `data/strings/`.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§1 paths, §2 `fcm_` prefix, §3 specs, §5 CI, §12 game-data hygiene)
- `docs/plan/DESIGN.md` §2, §4, §6, §8.4, §11.3, §12, §14, §15
- `docs/plan/TESTING.md` §CI, §Fixtures, §Scenarios
- `state/ENGINE_FACTS.md`: S-BASE (plan, base mechanics), S-LOADOUT
- `src/contracts/` and `docs/spec/data_schemas.md`, `docs/spec/world_json.md` (ARCH-0)
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R3-game-data.md` §1 (freelancer.ini [Data], [Resources], hard-coded paths in Content.dll), §2.4 (Gammu), §4 (capital ships, solar archetypes and docking spheres, loadouts, interiors, the Osiris `[MsnSolar] base=` mechanism), §5 (market field semantics and prices), §6 (shipyards), §9 (HDE vs vanilla diffs), §10 (CreateID algorithm)
  - `/home/user/freelancer/carrier-mod/local/research/R4-lore-and-testloop.md` §A1.3–A1.4 (limits and crash causes), §A2 (INI best practices, HDE compatibility, infocards, building the resource DLL on Linux, overlay recommendations), §A4.6 (HDE installer options rewrite files)
  - `/home/user/freelancer/carrier-mod/local/research/R2-engine-api.md` §2.1–2.6 (proxy bases: Discovery `<sys>_proxy_base`; '88 Flak `<Sys>_Mobile_Proxy_Base` object + base; solar_control `dockWith`)
- Tools:
  - `tools/fltools/` (P0-DATATOOLS)
  - `/home/user/freelancer/carrier-mod/local/research/R3-data/tools/{flini.py,flres.py,flhash.py}` as references
  - `/home/user/freelancer/carrier-mod/local/research/scratch/tools-r4a/resdll-test/` (a working resource-DLL build)
  - `/home/user/freelancer/refs/freelancer-hd-edition-installer/mod_options.iss` (what HDE options rewrite)

## Ownership

- **Owns:** `gen/` (except `gen/framework/` (P0-DATATOOLS), `gen/models/` (W2-LOADOUT) and other packages' `gen/plugins/<area>/`), `data/core/`, `data/strings/`, `harness/ci.d/40-*`, and scenarios in `harness/scenarios/data/`.
- **Reads:** `data/carriers/`, `data/yards/` (W1-CARRIER-DESIGN), `tools/fltools/`, live install (read-only).
- **Must not touch:** HDE files in any prefix except through the deploy pipeline on lane/dev prefixes; `data/carriers|yards` content.

## Contract

- **Provides:** the overlay layout, `manifest.json`, `world.json`, `text_ids.json`, `prices.json`, the `gen/run.py` CLI (plus the `gen/build.py` alias), the plugin interface, and the generated nickname catalog (`catalog.json` in the overlay dir: every `fcm_` nickname with its kind) for code packages.
- **Consumes:** the YAML schemas (ARCH-0), fltools APIs.

## Tasks

1. Pipeline skeleton: inputs, staging, outputs, manifest, determinism check (run twice, diff).
2. Marker-block patcher integration, with hash guards and uninstall.
3. Level-gating patch plus counts report.
4. Text DLL build plus index detection plus `text_ids.json`.
5. `world.json` export hook.
6. Carrier solar, ship and loadout generation from YAML (placeholder YAML until W1-CARRIER-DESIGN lands; coordinate through the schema).
7. Carrier bases: Plan A and Plan B generators.
8. Nomad boss NPCShipArch blocks plus the Gammu market placeholder.
9. Validators and CI wiring (`harness/ci.d/40-data-validate.sh`).
9b. Plugin interface, salvage pod, keymap option, voice-line registration, `prices.json` (REQ-12 to REQ-16).
10. In-game verification scenarios.

## Acceptance

- **Host tests (pytest):**
  - `test_determinism` (two runs → identical hashes)
  - `test_marker_idempotent` (applying twice = once)
  - `test_uninstall_restores` (hashes equal the originals)
  - `test_level_patch_fields` (only field 2 changes; counts > 0 for ships and equipment)
  - `test_resource_dll_shape` (i386, entry 0, RT_STRING + RT_HTML, BOM intact)
  - `test_text_index_detection` (fake freelancer.ini variants: 7 entries → 8; 8 entries → 9)
  - `test_validator_catches_dangling` (deliberately broken YAML → errors)
  - `test_hash_scan_clean`
  - `test_plan_a_base_count`
  - `test_plan_b_base_count`
- **In-game scenarios:**
  1. `data_boot`: deploy to a lane → the game boots to the main menu and loads a fixture. FLSpew has no new ERROR lines versus the baseline (allow-list from P0-HARNESS).
  2. `level_gating_removed`: fixture `HARNESS_lvl1_rich_fp9` (rank 1, docked at Freeport 9 `Ew04_01_Base`, rich, friendly with Freeport 9's owner; CONVENTIONS §6). `lane: input`, with real XTEST clicks. Open the ship dealer (input lock) → screenshot.
     - **Vision rubric:** "the Eagle is listed and its buy action is enabled, not greyed out or marked with a level requirement".
     - Buy it → devbridge `state` shows ship `ge_fighter6`.
     - Repeat at Leon (`Ew03_01_Base`) for the Titan (`coe2_package`, level 32).
     - Equipment: buy a class-9 gun at a base selling one, as a level-1 character.
  3. `carrier_base_docks` (`DEFERRED(W1-SPAWN)`): spawn a placeholder carrier solar with `dockWith = fcm_cbase_<…>` (W1-SPAWN devbridge `spawn`) → dock → room loads (screenshot: deck interior, vision "a battleship deck interior, not a black screen") → the bar and the services that exist work → launch.
  4. `nomad_boss_defs` (`DEFERRED(W1-SPAWN)`): from `HARNESS_ew06_space`, `spawn fcm_nomad_battleship_boss 1 near=player` and `spawn fcm_nomad_gunboat_escort 2 near=player` → both spawn (screenshot, vision "a Nomad capital ship (organic purple-blue hull) is visible") → no FLSpew errors.
  5. `text_dll_strings` (`DEFERRED(W1-UI)` for the text-service half): the text service resolves 5 sample keys; an infocard renders in the base info panel (screenshot). The DLL-shape half runs now (host test).
- **Report counts:** bases generated (plan A and B), archetypes, market lines changed, IDS range used.

## Engine facts to rely on / verify

- `[Resources]` order in HDE: index 7 = `Controls.dll`, so ours is 8 (R4 §A2.2, VERIFIED). Still detect it at deploy time.
- A base is bound to one system. Plan A re-pointing is UNVERIFIED until S-BASE.
- Loadouts and pilots for Nomad capitals are global (VERIFIED, file:line above). Whether spawning them outside missions works is per S-NPC.

## Pitfalls

- The HDE installer may rewrite files on reinstall or option change (R4 §A4.6). The patcher must detect "already patched by us" versus "unknown base".
- `solar` must load before `universe` (comment in freelancer.ini). Keep the ordering.
- Never delete or rename a shipped `fcm_` nickname after the first playable release; add new ones and migrate.
- A system with no solar objects crashes (Freelancer.exe 0xd1744). Never generate empty systems.

## Fallbacks and degrade path

1. If marker-block patching of `universe.ini` is rejected by any loader quirk, generate a full patched copy into the overlay at deploy time. It must still never be committed.
2. If the Plan B base count is too large for the engine (S-BASE measures it), share interiors across tiers and report it.
3. If `llvm-rc` output misbehaves in game, use the mingw `windres` path (R4 §A2.4) or Librelancer `lleditscript` `compile-frc`.

## Report

Use the standard report. Include the overlay tree, the counts, and the validator output summary.

## Gate-time addendum

The orchestrator fills:

- the base plan (A/B) chosen at G0b;
- the track (A: FLUF files present; B: FLSharp `missioncreatedsolars` path);
- ENGINE_FACTS IDs for docking and launch requirements;
- the schema versions;
- lanes;
- attempt notes;
- the commit trailer.
