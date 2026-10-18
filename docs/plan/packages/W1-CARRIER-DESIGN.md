# W1-CARRIER-DESIGN: classes × tiers × looks, slots, upgrade catalogs, prices, operating costs, balance simulator

- **Type:** design (with a host-tested balance simulator)
- **Wave:** 1
- **Depends on:** ARCH-0 (YAML schemas in `docs/spec/data_schemas.md` with placeholder YAML; balance-sim interface `docs/spec/balance_sim.md`); sub-wave 1a, in parallel with W1-DATA, which generates from these files. Coordinate only through the schema. → **Unblocks:** W1-DATA (real values), W2-YARD, W2-LOADOUT, W2-CARRIER-GAME, W2-CARRIER-UI, W3-AMBUSH (tier/class scaling), W3-LOSS, W4-WINGMEN (bays), W4-HIRING

## Goal

Turn DESIGN §4–§6 into concrete, balanced, data-driven numbers. The output:

- `data/carriers/*.yaml`: classes, tiers, looks, slots, base stats, crew;
- `data/yards/*.yaml`: per-yard availability and catalogs;
- `docs/design/CARRIERS.md`: the readable design, with the reasoning, tables, and "tunables for Adam";
- `src/logic/balance/`: a deterministic host simulator with assertions that keep the design honest as values change.

Adam is away, so this agent makes every taste call within the principles, records it, and keeps every number in YAML.

## Requirements

- **REQ-W1-CARRIER-DESIGN-1: Six classes** (D-4.2): Trade Carrier, Dreadnought, Fleet Carrier (balanced), Command Carrier (balanced flagship, crew-focused; bar from Border/Edge), Strike Carrier (wing-centric), Escort Carrier (light/fast/cheap).
  - The relative columns in D-4.2 are **hard constraints**: hold, hull, bays, armament, speed, operating cost.
  - Up to two extra classes may be added (latitude) **only** if each fills a distinct role. Record why in `CARRIERS.md` and `state/DECISIONS.md` (via report).
- **REQ-W1-CARRIER-DESIGN-2: Three tiers** (D-4.1).
  - Base prices for the balanced class: Core 3,000,000, Border/Edge 8,000,000, Nomad 20,000,000 credits.
  - Class price multipliers. Starting proposal: Escort 0.6, Trade 0.9, Fleet 1.0, Strike 1.15, Command 1.3, Dreadnought 1.6.
  - Tier stat multipliers on hull, slots, stocks and services.
  - Nomad tier = strongest hull, plus bar and equipment dealer aboard for every class (D-4.5).
- **REQ-W1-CARRIER-DESIGN-3: Looks and models** (D-4.3, D-4.4). Map each yard and class to a vanilla model plus interior. Constraints:
  - A Core yard sells its own house's look: Norfolk → Liberty dreadnought `li_dreadnought.cmp`; Southampton → `br_battleship`; Yokohama → `ku_battleship`; Oder → `rh_battleship`.
  - The Nomad tier uses the Osiris model `or_osiris.cmp` plus the Osiris interior (`li_06_bar` + `li_05` deck).
  - The Trade Carrier uses the **liner** model (`ships\utility\luxury_liner\luxury_liner.cmp`, ship `ge_liner`; station solar `luxury_liner` docked by Shetland `Br06_01` and Hawaii `Bw07_01`, with liner interiors) if its docking points and interior work. S-BASE/S-LOADOUT facts decide. The fallback is a house battleship look with a cargo loadout.
  - Interiors: `li_05_*` Liberty battleship, `br_04_*` Bretonia (Hood's unique `br_05_bar` is **not** reused), `ku_04_*` Kusari, `rh_04_*` Rheinland, `li_06_bar` Osiris (R3 §4.4).
  - Each look needs a solar with docking spheres. Vanilla: `l_dreadnought` (berth `HpDockMountA` + moor_medium B + moor_large C), `b_battleship`, `k_battleship`, `r_battleship`, `o_osiris` (berth A + moor_large B–E + moor_medium F) (R3 §4.3).
- **REQ-W1-CARRIER-DESIGN-4: Slot model** (D-5.3).
  - Per class × tier counts of: turret mounts (one per hardpoint, available or generated), missile launchers, torpedo launchers, utility slots (shield generator, interdiction dampener, sensors), engine slot, service slots (bar, equipment dealer, commodity hold, repair bay), docking-bay capacity (D-11.6), hold volume, nanobot and battery stock capacity, and munition magazines.
  - Vanilla turret hardpoints by model (R3 §4.2):
    - Liberty dreadnought **10** (HpTurret_L1..L4)
    - Bretonia battleship **12** (B1/B2/B4)
    - Kusari battleship **18** (K1/K3)
    - Rheinland battleship **21** (R1..R4)
    - Osiris **8** (O1..O4)
    - the liner has none
  - The Dreadnought class needs more mounts than most models have. Specify **added hardpoints** (count and placement rule) per look for W2-LOADOUT's CMP generator (D-4.4: allowed, generated, never committed).
- **REQ-W1-CARRIER-DESIGN-5: Upgrade catalog and per-yard catalogs** (D-5.3, D-5.4, D-6).
  - Upgrade items are `fcm_upg_*` goods (CONVENTIONS §2), each with: category, Mk level I–III, slot type, effect (hull +x, hold +y, bays +z, speed ×k, shield capacity, dampener %, sensor range), price, and compatible classes/tiers.
  - Capital turrets use vanilla capital guns by house family (e.g. `li_battleship_turret01..04`, `rh_*`, `ku_*`, `br_*`, flak turrets, `nomad_turret01_mark01` at Gammu; stats in `R3-data/capital_ships.json → capital_turret_guns`).
  - Missile and torpedo launchers: capital missile turrets from the cruiser loadouts; torpedo launchers from the vanilla torpedo equipment. Confirm with S-LOADOUT.
  - Per-yard catalogs follow the DESIGN §5.4 spread:

    | Yard | Strength |
    |---|---|
    | Rheinland | Best turrets |
    | Kusari | Engines and sensors |
    | Bretonia | Hull and bays |
    | Liberty | Bays and missiles |
    | Border/Edge | Interdiction gear and shields |
    | Gammu | Nomad tech (Nomad turrets; Nomad cloak only if S-LOADOUT proves a capital cloak works) |

  - Each yard sells ≥ 3 classes. Trade Carriers are sold at ≥ 1 Core and ≥ 1 Border/Edge yard (D-6).
- **REQ-W1-CARRIER-DESIGN-6: Operating costs** (D-8.6).
  - Consumption rates: nanobots per hull point repaired; missiles and torpedoes per salvo.
  - Resupply prices: the market price where sold, otherwise a quartermaster price.
  - The expected cost per standard ambush fight, per class. Target: Dreadnought ≥ 4× Fleet; Trade ≤ 0.5× Fleet.
- **REQ-W1-CARRIER-DESIGN-7: Travel speeds** (D-7.13). Targets come **only** from TESTING §Metrics / `harness/metrics_targets.yaml`, measured on the 10 sample routes:
  - the balanced classes (Fleet, Command) cross a system in **2–4 real minutes** of docked travel;
  - **every** class stays within 1–8 minutes.

  Class time multipliers are your design choice inside those bounds. Starting point: Escort ≈ 0.6–0.7×, Strike ≈ 0.8×, Dreadnought ≈ 0.85×, Fleet/Command 1.0×, Trade ≈ 1.5–2.0×.

  Escort-mode (live NPC) speed must meet D-7.13's "at most 2× docked-travel time": tune engine force and cruise from the S-NPC facts (capital impulse ≈ 30 m/s for battleship engines, R3 §4.1; cruise use UNVERIFIED).
- **REQ-W1-CARRIER-DESIGN-8: Crew.** Crew wingmen per tier: 2, or 3 at Nomad (D-11.4). Replacement time: 1 in-game day, faster for Command. Each class has a launch and recover rate per bay.
- **REQ-W1-CARRIER-DESIGN-9: Balance simulator** (`src/logic/balance/`): engine-free C++ (plus an optional Python mirror for quick exploration under `src/logic/balance/py/`). It models:
  - effective DPS from turret stats (damage, refire, accuracy assumption);
  - effective HP (hull + shield + nanobot healing over time);
  - Lanchester-style group fights against the standard ambush lineups per tier (from the attacker-lineup rules W3-AMBUSH will use; use placeholder lineups derived from R3 patrol data: fighters d6–d19 plus gunboats/cruisers);
  - travel time from route lengths;
  - operating cost per fight;
  - value per credit.

  Assertions (host tests):
  - Dreadnought DPS ≥ 3× Trade Carrier DPS (same tier).
  - Trade hold ≥ 3× Fleet hold.
  - Trade speed ≤ 0.7× Fleet speed.
  - A Fleet carrier with full nanobots survives a tier-matched standard ambush ≥ 70% of the simulated time alone (TESTING §Metrics), and wins ≤ 30% against an ambush two tiers above.
  - A Trade Carrier alone loses to a tier-matched ambush (it needs escorts), but survives with 2 crew wingmen ≥ 50% of the time.
  - Nomad tier > Border/Edge > Core on every stat axis.
  - Price per effective-HP·DPS stays within a 2× band across classes of the same tier (no strictly dominated class).
  - Every class reaches the D-7.13 travel-time target.

  Results go to `docs/design/CARRIERS.md` tables (generated by `balance_report`).
- **REQ-W1-CARRIER-DESIGN-10: Schema conformance.** All YAML validates against the ARCH-0 schema. Every referenced vanilla nickname (models, guns, engines, goods, bases) is checked against the local install by the validator from P0-DATATOOLS / W1-DATA.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§2 names, §3 schemas, §12 game-data hygiene)
- `docs/plan/DESIGN.md` §1, §3–§6, §7.13, §8, §9.8, §11.4–11.6
- `docs/plan/TESTING.md` §Metrics (balance and travel targets)
- `state/ENGINE_FACTS.md`: S-LOADOUT (runtime loadouts, hardpoint addition, munition tracking, capital shields, torpedo/missile on capitals), S-BASE (looks usable as dockable runtime solars; liner viability), S-NPC (capital speeds, cruise)
- `src/contracts/{yard,carrier,inventory}.hpp`, the schemas in `docs/spec/data_schemas.md`, and `docs/spec/balance_sim.md`
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R3-game-data.md` §4 (capitals: hit_pts 69,300, hold sizes; `li_dreadnought` hold 10,730.2 vs 1,000,000 for the others; masses, steering; loadouts and turret counts; solar archetypes and docking spheres; interiors; the Osiris mechanism), §5 (Eagle/Sabre/Titan prices; nanobots and batteries price 200, volume 0; best purchasable gear ≈ 1.5M for a maxed Eagle), §6 (shipyards and lore yards; suggested tier homes), §8 (factions and interdiction)
  - `/home/user/freelancer/carrier-mod/local/research/R3-data/capital_ships.json` (shiparch capitals, loadouts, the 63 capital turret guns with stats), `ship_packages.json`, `shipyards_market_ships.json`, `bases.json`
  - `/home/user/freelancer/carrier-mod/local/research/R2-engine-api.md` §4.2 (personality RepairUse for NPC nanobot use)
- Live data (read-only) for exact gun, engine and equipment stats: `<dev-base>/drive_c/Games/Freelancer HD Edition/DATA/EQUIPMENT/{weapon_equip.ini, misc_equip.ini, engine_equip.ini, st_equip.ini}`, `SHIPS/shiparch.ini`, `SOLAR/solararch.ini`

## Ownership

- **Owns:** `data/carriers/`, `data/yards/`, `docs/design/CARRIERS.md`, `src/logic/balance/` (with `tests/`).
- **Reads:** contracts, research, live data, `tools/fltools/`.
- **Must not touch:** `gen/` (W1-DATA turns YAML into INIs), `data/core/`, `data/strings/`. Strings needed (class names, upgrade names, descriptions) go into `data/carriers/strings.yaml` under keys that W1-DATA's text build includes. Agree the key namespace `carrier.*` / `upgrade.*` / `yard.*` through the ARCH-0 schema.

## Contract

- **Provides:** YAML datasets per the schema; `balance.hpp` (simulator API used by W3-AMBUSH tuning and W5); `CARRIERS.md`.
- **Consumes:** schemas, the ENGINE_FACTS numbers, the W1-WORLD route lengths (sample routes from TESTING §Metrics).

## Tasks

1. Extract the stats you need from the live data into `$FLMOD_LOCAL/cache/carrier-design/` via fltools: capital guns, engines, shiparch capitals, solars, goods prices. This cache is gitignored and game-derived.
   - The simulator and tests read the cache at test time, and regenerate it if missing.
   - **Never copy vanilla stat values into committed YAML or code** (CONVENTIONS §12). Committed YAML holds our design values plus vanilla nicknames as references.
   - `CARRIERS.md` may show our design values and derived aggregates (DPS, effective HP, cost per fight), not raw vanilla stat tables.
2. Draft the classes × tiers table, looks, slots and crew. Run the simulator, iterate until every assertion passes, and record the iterations briefly.
3. Upgrade catalog plus per-yard catalogs (≥ 3 classes per yard; quality spread).
4. Operating costs and resupply prices.
5. Travel speeds against the W1-WORLD sample routes. If W1-WORLD hasn't merged yet, use straight-line gate-to-gate lengths from `R3-data/system_graph.json` positions × 1.25 and mark them provisional.
6. `CARRIERS.md`: overview; one table per class (tier columns); looks; catalogs per yard; operating costs; travel times; balance results; "Tunables for Adam" (every number he might tweak, and where it lives).
7. Schema validation plus the nickname cross-check.

## Acceptance

- **Host tests** (`src/logic/balance/tests/`): every REQ-9 assertion, by name (`dreadnought_dps_3x_trade`, `trade_hold_3x_fleet`, `trade_speed_le_0p7_fleet`, `fleet_survives_matched_ambush_70pct`, `loses_to_two_tiers_above`, `trade_needs_escorts`, `tier_monotonic`, `no_dominated_class`, `travel_time_targets`), plus `yaml_schema_valid` and `vanilla_refs_exist` (the latter skips with a clear message if the local install is missing).
- **Data checks:** each yard ≥ 3 classes; the Trade Carrier at ≥ 1 Core and ≥ 1 Border/Edge yard; the Gammu yard requires the flag `nomad_gate_unlocked` (CONVENTIONS §2); prices = tier base × class multiplier exactly.
- **Document:** `CARRIERS.md` renders the generated tables, and every number in it matches the YAML (a test regenerates and diffs).
- **In-game sanity:** none. W2 packages consume the data in game. But `vanilla_refs_exist` must pass against the dev-base install.

## Engine facts to rely on / verify

- Capital ships have no `nanobot_limit`/`shield_battery_limit`/`hp_type` in vanilla (R3 §4.1). The generated ship archetypes add them (W1-DATA).
- Capital battleship engines: max force 3,000,000 / linear drag 100,000 (≈ 30 m/s impulse); `cruise_charge_time` 5. Whether NPC capitals cruise is UNVERIFIED (S-NPC).
- Turret counts per model as listed (R3 §4.2, VERIFIED from loadouts). Added hardpoints depend on S-LOADOUT.

## Pitfalls

- Don't make one class strictly better per credit (REQ-9 `no_dominated_class`).
- Keep vanilla flavour: house turret families stay with their houses; Nomad tech only at Gammu.
- Prices must fit FL's int32 cash (Nomad Dreadnought 32M is fine).

## Fallbacks and degrade path

1. If the liner can't be a dockable runtime solar, the Trade Carrier uses the Liberty dreadnought hull (the biggest hold in vanilla data) with a "freighter" loadout and an interior variant. Record the decision.
2. If S-LOADOUT says added hardpoints don't work, cap the Dreadnought at the model's vanilla turret count (pick the Rheinland look, 21) and add firepower through better turret Mk levels. Record it.
3. If capital shields don't work on solars or ships, replace the shield upgrade with an "armor plating Mk IV" (+hull) and record it.

## Report

Use the standard report. Include the class×tier summary table, the per-yard catalog matrix, and the balance assertion results.

## Gate-time addendum

The orchestrator fills:

- the S-LOADOUT, S-BASE and S-NPC ENGINE_FACTS IDs (liner viability, hardpoint addition, shields, torpedoes, capital speed);
- the schema versions;
- whether the W1-WORLD sample-route lengths are available;
- attempt notes;
- the commit trailer.
