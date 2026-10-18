# W4-HIRING: Hiring wingmen at bars, roster, wages, permadeath

- **Type:** impl
- **Wave:** 4 (sub-wave 4b, CONVENTIONS §8)
- **Depends on:** W4-WINGMEN (merged), ARCH-3
- **Unblocks:** M3-PLAYTEST

## Goal

In any bar in Sirius, the player can open a hiring panel and hire pilots of varied skill, ship and loadout, from a pool that fits that base's faction and region. Pirate bars offer pirates; Rheinland bars offer Rheinland mercenaries and navy veterans.

- Hired pilots cost a fee plus a small daily wage, quit if unpaid for 3 days, and die permanently.
- There is no roster limit. If Adam wants to hire an army, he can.
- A roster panel (in bars and aboard carriers) manages assignments.

W4-WINGMEN flies them; this package recruits, pays and tracks them.

## Requirements

- **REQ-W4-HIRING-1 (D-11.5).** Hiring panel opens from a native NavBar or bar-room button when docked in a room of type `Bar` (W1-UI helper). It is available at every dockable base that has a bar, except story-only bases.
- **REQ-W4-HIRING-2 (D-11.5).** Candidate generation is deterministic per (bar, in-game day, seed).
  - 3–8 candidates per bar, refreshed daily.
  - Each candidate has:
    - a name (from FL name resources by IDS reference, as in FLUF's default name pools; R2 §1.2 step 2);
    - a voice and costume where feasible;
    - a faction affiliation drawn from the base's faction and its region's patrol factions (R3 `system_faction_presence.json`, `bases.json`);
    - a skill tier `easy|med|hard|ace`, mapped to the faction's `pilots_population.ini` personality family (`pilot_military_*`, `pilot_police_*`, `pilot_bh_*`, `pilot_pirate_*`, `pilot_outcast_*`, `pilot_corsair_*`, `pilot_lrogue_*`, `pilot_xenos_*`, `pilot_company_*`; fallback `pilot_military_*`);
    - a ship class (light, heavy, very heavy fighter; gunboat only at the `ace` tier in frontier/edge bars) picked from that faction's `faction_prop.ini` `npc_ship` list → `npcships.ini` arch + loadout at a level band (`d` level ↔ skill tier and region);
    - a fee and a daily wage.
- **REQ-W4-HIRING-3 (D-11.5).** Reputation gate. Hiring requires player rep with the candidate's faction ≥ 0.0. (Friendly-only would be an artificial restriction beyond the faction requirement; neutral is enough.) Hostile factions' pilots don't appear.
- **REQ-W4-HIRING-4.** Pricing in `data/pilots/pricing.yaml`: fee and wage by tier × ship class × region.
  - Balanced so a mid-game endgame player (a few million credits) can field 3–6 good pilots, and a rich player can hire dozens.
  - Values are **tunables for Adam**, listed in BUILD_REPORT.
  - A default sanity rule: daily wage ≈ 2–5% of the hire fee.
- **REQ-W4-HIRING-5 (D-11.5).** Wages.
  - Charged each in-game day on the mod clock (1 day = `universe.ini` [Time] `seconds_per_day`, 1800 s in HDE) via the inventory/credits API.
  - If cash is insufficient, the pilot accrues an unpaid day. After **3 consecutive unpaid days** the pilot quits (`wing.quit`, a toast and a roster entry).
  - Partial payment is applied in roster order: oldest hires first.
  - Paying arrears in the roster panel resets the counter.
- **REQ-W4-HIRING-6.** Permadeath and history.
  - Dead hires stay in a "fallen" list (name, date, system, killer faction) visible in the roster panel. They are never re-offered.
  - The crew-wingman replacement rule is W4-WINGMEN's; this package only shows crew in the roster.
- **REQ-W4-HIRING-7 (D-11.6).** Roster panel (bars, aboard carriers, and in space via W4-WINGMEN's quick panel):
  - list all wingmen: crew and hired, status, assignment, wage, unpaid days;
  - assign `follow_player | guard_carrier(X) | stay_docked(X)` (bay capacity shown);
  - dismiss;
  - pay arrears.
- **REQ-W4-HIRING-8 (D-1.6, D-11.9).** No roster cap. The panel stays usable with 500 entries: virtualized list, filtering, sorting. Show the scale warning text from W4-WINGMEN when relevant. Never block hiring.
- **REQ-W4-HIRING-9.** Persistence: roster, fallen list, candidate seeds, wage ledger and unpaid counters go in the per-save JSON (`docs/spec/persistence.md`).
- **REQ-W4-HIRING-10.** Devbridge (CONVENTIONS §4, the `hire.*` namespace): `hire.candidates [base]`, `hire.hire <idx>`, `hire.dismiss <id>`, `hire.pay`, `hire.roster`.
  - Events: `ev=hire.candidates base= factions=`, `ev=hire.hired id= fee=`, `ev=hire.paid amount=`, plus `ev=wing.quit` (W4-WINGMEN's event, emitted through its API).
- **REQ-W4-HIRING-11** (CONVENTIONS §12): **game-data hygiene.** Candidate pools are derived from `faction_prop`/`npcships`/`pilots_population`/`mbases` at **deploy time** by `gen/plugins/hiring/` (owned here) into `$FLMOD_LOCAL/gen/hiring_pools.json`. Committed `data/pilots/*.yaml` contains only our pricing and rules, and references vanilla content **by nickname only**.

## Context pack (read before writing code)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §4, §8, §12)
- `docs/plan/DESIGN.md` §1 (D-1.6), §11
- `docs/plan/TESTING.md` §M3, §Fixtures (`HARNESS_poor`)
- `state/ENGINE_FACTS.md`
- Contracts: `src/contracts/hiring.hpp`, `wingmen.hpp`, `inventory.hpp`, `ui_kit.hpp`, `persistence.hpp`, `platform.hpp`; `docs/spec/wave4-contracts.md`
- Data (read-only, the lane's install): `DATA/MISSIONS/pilots_population.ini`, `faction_prop.ini`, `npcships.ini`, `mbases.ini`; `DATA/UNIVERSE/universe.ini`
- Extracts, as reference only (the runtime uses the deploy-time tables): `$FLMOD_RESEARCH/R3-data/bases.json`, `factions.json`, `system_faction_presence.json`
- `local/research/R3-game-data.md` §3.2 (NPC selection chain), §8 (factions, reps)
- `local/research/R2-engine-api.md` §1.2 (names via FmtStr, pilot personalities)
- `local/research/R5-sp-architecture.md` §4.1 (base rooms and NavBar), §5 (messaging)

## Ownership

- **Owns:** `src/logic/hiring/`, `src/game/ui/hiring/`, `data/pilots/`, `gen/plugins/hiring/`, `harness/scenarios/hiring/`, `tests/host/hiring/`
- **Reads:** contracts, merged code, game data
- **Must not touch:** `src/*/wingmen/` (W4-WINGMEN), contracts, sidecar

## Contract

- **Consumes:** inventory (credits), wingmen (roster add/remove, assignment API), UI kit, mod clock, persistence, world/data accessors.
- **Provides:** the `hiring.hpp` implementation, roster panel, events `wing.hired`, `wing.quit`, `wing.paid`.

## Tasks

1. Data: pricing and rules YAML in `data/pilots/`. Candidate pools are generated at deploy time by `gen/plugins/hiring/` through W1-DATA's plugin interface (REQ-11). Only nicknames and our numbers are committed; no copied game text or values.
2. Engine-free candidate generator and wage ledger; host tests.
3. Hiring panel and roster panel (W1-UI kit). Vision rubrics `hiring_panel`, `roster_panel`.
4. Integration with the W4-WINGMEN roster API and persistence.
5. Scenarios.

## Acceptance (all automated)

- **Host tests:**
  - `hire_candidates_deterministic`: same seed gives the same pool; a new day gives a new pool.
  - `hire_pool_matches_faction`: pirate bar → pirate factions only, Liberty bar → Liberty-aligned.
  - `hire_rep_gate`
  - `wage_daily_tick`
  - `wage_three_unpaid_quit`
  - `pay_arrears_resets`
  - `roster_500_entries_perf`: panel model ops < 1 ms.
- **In-game scenarios:**
  - `hiring_liberty_vs_pirate_bar` (input lane): open the panel by click in a Liberty bar and in a pirate bar; vision confirms different pools; `hire.candidates` factions match.
  - `hiring_hire_three`: fees deducted exactly; roster shows 3; launch → they spawn (W4-WINGMEN).
  - `hiring_wages_and_quit` (`HARNESS_poor`): `time.skip` 3 days → quit events; cash never goes negative.
  - `hiring_permadeath_fallen_list`
  - `hiring_save_load`
  - `hiring_army_100`: hire 100 via devbridge; panel usable (vision); no cap message.
- **Negative:** hiring with insufficient cash is refused with a message; a candidate whose arch fails validation is never offered (the generator filters it; logged).

## Engine facts to rely on / verify

- **Verify:** bar-room detection and button placement in Bar rooms (S-UI showed NavBar in base rooms; confirm for Bar).
- **Verify:** FmtStr name generation for pilot names displayed in comms and target info.

## Pitfalls

- Faction ids vs rep groups (R3 §10).
- `faction_prop` `npc_ship` lists reference arches by `npc_class`; validate that every chosen arch/loadout exists and has an engine.

## Fallbacks and degrade path

1. If a Bar-room button can't be added natively, use an overlay window opened by a hotkey while docked in a bar.
2. If FL name IDS can't be used for runtime NPC names, use our own name pool in the resource DLL (original names, lore-consistent).

## Report

Standard. Include the pricing table as delivered (Tunables for Adam).

## Gate-time addendum

(orchestrator)
