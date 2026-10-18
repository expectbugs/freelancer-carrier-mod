# W4-ESCALATION-DESIGN: Design the player-alterable endgame escalation system

- **Type:** design (with engine spikes)
- **Wave:** 4 (sub-wave 4a, CONVENTIONS §8)
- **Depends on:** ARCH-3
- **Unblocks:** the W4-ESC-* build packages this agent defines (sub-wave 4b), then M3-PLAYTEST

## Goal

After the campaign, Sirius should come alive in a way the player can change.

Adam's brief, as he said it: build *"a compelling system, one that is alterable by the player with in-game actions (like for example I could choose to fight for the Liberty Rogues and expand their power and influence myself, which is persistent and lets them take over some rogue bases in other systems expanded outward from Liberty if I've been helping them in those systems, etc). Have the agent make a good, intricate, awesome system for all that with some fresh ideas and some maybe inspired by other games or media and everything, and write up a document about it so I can make changes or suggestions if something isn't working well."*

This package:

- proves which engine levers actually work (spikes);
- designs an intricate, persistent faction-influence system within those levers that includes the design doc's three escalation pillars;
- writes `docs/design/ESCALATION.md` for Adam;
- splits implementation into W4-ESC-* packages the orchestrator can run in parallel.

The build does **not** wait for Adam's review. He reviews afterwards and asks for changes.

## Requirements

- **REQ-W4-ESC-D-1 (D-13.1).** Escalation activates only after campaign completion: our persistent `campaign_complete` flag (set on `Mission_13` succeeded or MissionNum 42, or detected HDE Open-SP state). Before that, influence may accumulate silently (design choice; decide and justify) but nothing escalates.
- **REQ-W4-ESC-D-2 (D-13.2).** The system must be **player-alterable and persistent**. Player actions change faction influence per system, and influence changes the world:
  - who patrols;
  - who holds which bases or controls access;
  - what's for sale and at what price;
  - what news and rumors say;
  - who attacks whom.

  It must support Adam's example end to end. Helping the Liberty Rogues in systems adjacent to Liberty (killing their enemies, running their errands, protecting their convoys) raises Rogue influence there. Past a threshold, and after a contested **takeover event** the player can join or oppose, rogue-friendly bases in those systems become Rogue-held. The expansion continues **outward from Liberty** along the jump network where the player keeps helping.
- **REQ-W4-ESC-D-3 (D-13.2).** It must include all three pillars from the design doc:
  1. **Nomad resurgence:** Nomad activity spreads beyond Ew05/Ew06 in stages (e.g. Edge → Hispania → Border → house frontiers), driven by a clock plus player action (fighting Nomads slows it; ignoring it accelerates it).
  2. **House wars:** e.g. Liberty vs Rheinland open war, with **real capital fleets** (the unused navy NPCs `li_n_dreadnought_d25`, `rh_n_battleship_d25`, `*_cruiser_d22`, `*_destroyer_d22`; R3 §8) fighting in the original systems. Fronts move with outcomes; the player can tip battles.
  3. **Scaling bounties:** targets scale with the player's gear value and reputation, issued by factions the player is friendly with, against their enemies.
- **REQ-W4-ESC-D-4.** **Fresh ideas, explicitly inspired by other games and media.** Consider (at least) and cite what is borrowed:
  - X4 (sector ownership, faction economies and wars);
  - Elite Dangerous BGS (per-system influence %, states such as boom, war, civil war, expansion, retreat, lockdown);
  - Mount & Blade (fiefs changing hands, lords' relations);
  - Starsector (faction hostilities events, colony crises);
  - Stellaris (endgame crisis escalation, which fits the Nomads);
  - EVE Online sovereignty;
  - Freespace and Battlestar Galactica (fleet battles, the desperate defense);
  - The Expanse (factional politics, blockades);
  - Sid Meier's Pirates! (letters of marque, reputation ripples);
  - XCOM (a threat meter).

  Pick what fits Freelancer's tone (vanilla-faithful, D-1.1). Novelty that doesn't fit the lore is cut.
- **REQ-W4-ESC-D-5 (D-1.4, D-1.5, D-1.6).** Principles:
  - **Earned danger:** escalation responds to the world's data and the player's choices, not dice alone.
  - **Never forced:** fights wait or are optional. A base takeover the player cares about gives warning and a window.
  - **No artificial restrictions:** no level gates.
  - It uses the **shared encounter system** (D-10) and the original map and factions.
- **REQ-W4-ESC-D-6 (D-13.4).** **Engine spikes first** (in `spikes/s_faction/`, on lanes, with evidence), before the design is final. Answer each with VERIFIED-in-game evidence or "not possible":
  1. Can a dockable base's controlling faction change at runtime? Test the base solar's rep affiliation via `pub::Reputation::SetAffiliation` on its object rep: what changes for docking permission, IFF colors, the scanner name, and bribe/rep requirements? Does it persist across system re-entry and save/load if we re-apply on load?
  2. Can the base's bar and room NPCs (`mbases.ini`, content.dll BasePop) be changed at runtime? If not, which presentation levers exist: infocard and name overrides; base info text; NavBar features; a news/rumor override via our UI?
  3. Can the market change at runtime: prices, availability, a different faction's goods? Track A: FLUF MarketManager. Track B: our hook, or generated alternate markets switched by …? What is proven?
  4. Can we **suppress or alter vanilla zone encounters** at runtime (e.g. reduce Liberty Navy patrols where Rogues took over)? Options: content.dll hooks, zone density patches, spawn-time filtering via `OnContentPilotCreate`-style hooks. Otherwise, add our own patrols via the encounter system to overlay control.
  5. **Group-vs-group reputation** (`pub::Reputation::SetReputation(groupA, groupB, v)`): do NPC factions then fight each other in the world? Does it persist (saves store `[Group]` tables, R5 §3.2) and survive reload? Side effects on the campaign factions?
  6. **NPC-vs-NPC capital battles:** spawn opposing capital fleets (d22/d25 navy capitals plus escorts) in a system and measure behavior, performance (§Metrics FPS) and crash risk (capital death fuses, R4 §A1.4.4). Find a safe destruction path.
  7. **News delivery:** vanilla `news.ini` is static and hard-coded in Content.dll (R3 §1.1). Prove our alternative: NN messages, toasts, a "Sirius Situation Report" panel, base info override.
- **REQ-W4-ESC-D-7 (D-13.3).** Write `docs/design/ESCALATION.md` **for Adam**: readable, concrete, no hand-waving. It must contain:
  - **A vision paragraph** and a one-page "how it plays" walkthrough of the Rogues example.
  - **The influence model:** per faction per system; the math with numbers; decay; spread along jump links; caps; how player actions map to influence deltas (kills, escorting convoys, trade deliveries, bounties, donations/supply drops if implemented, destroying faction capital ships, defending or raiding bases).
  - **Faction AI states:** e.g. Stable / Expansion / War / Civil unrest / Retreat / Lockdown, inspired by the BGS. Transitions with numbers; what each state spawns (via encounter definitions) and changes.
  - **Takeovers:** which bases are eligible (by faction alignment, e.g. "rogue-friendly"), preconditions, the warning/window, the assault/defense encounter, outcome effects using only proven levers, and the retake rules.
  - **Nomad resurgence stages:** triggers, spread map, stage effects, and how the player pushes back.
  - **House wars:** war declaration triggers (influence friction, player actions, scripted escalation clock), fronts, fleet compositions, battle resolution (live when the player is present, simulated when away, reusing the paper-simulation approach of carriers), peace conditions.
  - **Scaling bounties:** issuers, target generation, scaling formula from gear value and reputation, rewards.
  - **UI:** the situation report panel, map overlays if feasible (influence by system), news feed, notifications.
  - **Persistence:** the JSON section schema (escalation blob from ARCH-3).
  - **Balance targets:** the pace of change per hour of play; how long a takeover campaign takes (target: 1–3 hours of focused play per system); a maximum simultaneous active wars/events cap for **performance only**, documented.
  - **Tunables:** a YAML file list with defaults and what they do, "for Adam".
  - **Inspirations:** what was taken from where.
  - **Engine levers:** the spike results table (VERIFIED or not possible, with evidence paths) and the design limits that follow from it.
  - **Testing plan:** the scenarios each W4-ESC-* package must provide (TESTING §M3 step 8).
  - **Future ideas:** cut for scope, for Adam to pick up later.
- **REQ-W4-ESC-D-8.** Split implementation into **as many W4-ESC-* packages as the design needs** (no cap; typically `W4-ESC-INFLUENCE`, `W4-ESC-TAKEOVER`, `W4-ESC-NOMAD`, `W4-ESC-WARS`, `W4-ESC-BOUNTIES`).
  - Use the template `docs/plan/packages/_ESC_TEMPLATE.md`. Its name deliberately does **not** match the `W4-ESC-*` glob, so it is never mistaken for a package.
  - Write one file per package, `docs/plan/packages/W4-ESC-<AREA>.md`. Never use the reserved ID `W4-ESC-FALLBACK`.
  - Each package may run up to 6 at a time in parallel, per the usual concurrency limits.
  - Ownership must be disjoint: `src/logic/escalation/<area>/`, `src/game/escalation/<area>/`, `data/escalation/<area>/`, `harness/scenarios/escalation/<area>/`.
  - Dependencies minimized. Shared pieces go in the first package.
  - The final report gives the orchestrator a ledger-ready table: ID, deps, owns, one-line goal.
- **REQ-W4-ESC-D-9.** Reuse, don't duplicate: the encounter system (W2-ENCOUNTER), the paper-simulation pattern (W2-CARRIER-LOGIC), UI kit, notifications, persistence and the mod clock.

## Context pack (read before designing)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §4 `esc.*` verbs, §8 sub-waves, §10, §12 game-data hygiene)
- `docs/plan/DESIGN.md` (all, especially §1, §9, §10, §13)
- `docs/plan/TESTING.md` §M3, §Metrics, §Scenarios
- `state/ENGINE_FACTS.md` (all), `state/DECISIONS.md`
- Contracts and specs: `src/contracts/escalation.hpp`, `encounter.hpp`; `docs/spec/wave4-contracts.md`, `docs/spec/persistence.md`
- Merged design docs: `docs/design/CARRIERS.md` and any others
- Game data extracts:
  - `local/research/R3-game-data.md` (§2 universe, §3 zones/encounters, §6 shipyards/bases, §8 factions and capital NPCs)
  - `$FLMOD_RESEARCH/R3-data/` (`factions.json`, `bases.json`, `system_graph.json`, `system_faction_presence.json`, `system_combat_presence.json`, `zones_encounters.json`): reference only. Shipped code derives its tables at deploy time (CONVENTIONS §12), and committed escalation YAML references bases, factions and systems **by nickname only**.
- Engine API:
  - `local/research/R2-engine-api.md` §8 (reputation), §5 (off-screen simulation), §7 (loot)
  - `local/research/R5-sp-architecture.md` §5 (messaging), §6 (mission scripting vs C++)
  - `local/research/R4-lore-and-testloop.md` §A1.4 (crash causes, especially capital death), §A4.2 (Project Reforge: capital patrols and endgame lessons)
- Decompilation for faction, base and market internals (read-only reference): `/home/user/freelancer/refs/Freelancer-Decomp/docs/` and `src/Content/`, `src/Server/`

## Ownership

- **Owns:** `docs/design/ESCALATION.md`, `spikes/s_faction/`, `docs/plan/packages/W4-ESC-*.md` (new files only), `data/escalation/README.md` (tunable index)
- **Reads:** everything
- **Must not touch:** production code under `src/` (except throwaway code in `spikes/s_faction/`), contracts. Contract gaps go into the report as blocking questions with proposed additive patches for the orchestrator.

## Contract

- **Consumes:** `escalation.hpp` as frozen by ARCH-3 (VERIFIED and PROPOSED capabilities).
- **Provides:** the design doc, W4-ESC-* specs, spike facts, and any proposed additive contract changes.

## Tasks

1. Read everything in the context pack. Write a 1-page "current world" analysis in the doc draft: who controls what, which bases are rogue-, pirate- or house-aligned, the adjacency fronts.
2. Spikes 1–7 (REQ-6) on lanes, with scenarios and evidence. Append VERIFIED facts to the report for `ENGINE_FACTS.md`.
3. Design draft; then a self-review pass as Adam would read it: is it fun, clear, lore-faithful? Is every mechanic built on a VERIFIED lever?
4. Write `docs/design/ESCALATION.md` (final).
5. Write the W4-ESC-* specs (template), with acceptance scenarios that demonstrate every lever and stage.
6. Report with the ledger table.

## Acceptance (automated where it can be)

- Spike scenarios run with evidence (HARNESS logs, screenshots and vision verdicts) for every lever claimed VERIFIED. No mechanic in the design relies on an UNVERIFIED lever unless it has a stated fallback.
- `docs/design/ESCALATION.md` contains every section listed in REQ-7. A reviewer checks each section against the list.
- Each W4-ESC-* spec follows `_ESC_TEMPLATE.md`, has disjoint ownership, and has ≥ 2 in-game scenarios plus host tests for its model. Devbridge verbs stay in the `esc.*` namespace (CONVENTIONS §4). In-game scenarios that need a sibling W4-ESC-* package are marked `DEFERRED(<ID>)` per CONVENTIONS §8.
- The Rogues example is traceable through the specs: a scenario chain exists from "player kills Liberty Navy patrols in a Rogue-adjacent system" to "base X becomes Rogue-held, and stays so after save/load".

## Engine facts to rely on / verify

- All REQ-6 items. Also: whether `[Group]` faction-faction tables in saves are rewritten from memory on save, and therefore persist our group-rep changes (R5 §3.2 says unknown keys are dropped; group tables are vanilla keys).

## Pitfalls

- Never destroy a dockable base's root (`destroy_root`) and don't rely on base destruction (R4 §A1.4.4).
- Capital death fuses are a crash hotspot. Autosave before scripted capital battles is allowed only if it respects "never forced" (no surprise saves overwriting the player's slot; use a dedicated autosave if any).
- Changing campaign-critical faction relations can break story missions. Escalation is post-campaign only.

## Fallbacks and degrade path

If base ownership can't change at runtime in a convincing way, design takeovers as **control, not ownership**. The base stays physically the same, but:

- its patrols, the docking access the player gets (via rep effects), market overrides (if proven), infocard/name text, the news feed and encounter presence all flip;
- this is shown clearly in the situation report.

Record this in the design doc and the report.

**If this package itself DEGRADES** (its attempt budget is exhausted without a usable design or specs), the orchestrator runs the reserved package **W4-ESC-FALLBACK** instead, using the spec below. That keeps the D-13.2 pillars present in v1. Copy the spec into `docs/plan/packages/W4-ESC-FALLBACK.md` and add a ledger row.

### Reserved spec: W4-ESC-FALLBACK (minimal escalation on proven levers)

- **Type:** impl
- **Wave:** 4b
- **Depends on:** ARCH-3, W2-ENCOUNTER, W3-NOMAD
- **Owns:** `src/logic/escalation/fallback/`, `src/game/escalation/fallback/`, `data/escalation/fallback/`, `harness/scenarios/escalation/fallback/`
- **Gating:** active only after `campaign_complete`.
- **Requirements:** built entirely on the shared encounter system and VERIFIED levers. No base takeovers, no market changes.
  1. **Nomad resurgence:** a 4-stage clock (Edge → Hispania → Border → house frontiers) advanced by game time and slowed by Nomad kills. Each stage adds `area_nomads`-style encounter definitions in that region's systems.
  2. **House war:** one Liberty vs Rheinland war front. Periodic capital-fleet battle encounters (d22/d25 navy capitals plus escorts) at frontier systems, joinable by the player, with simulated results when the player is away. Fronts shift with outcomes. Situation messages go through notifications.
  3. **Scaling bounties:** factions the player is friendly with issue bounty targets against their enemies. Target strength scales with the player's gear value and reputation, delivered as encounter definitions plus a reward hook.
  4. **Persistence:** the escalation section in the per-save JSON.
  5. **Devbridge:** `esc.state`, `esc.stage <n>`, `esc.war`, `esc.bounty`.
- **Acceptance:** host tests for the clocks, scaling and front logic; ≥ 1 in-game scenario per pillar with evidence; save/load persistence; a 30-minute soak with no crash; the M3 escalation step runs against these scenarios.

## Report

Standard, plus the ledger-ready table of W4-ESC-* packages and the spike facts list.

## Gate-time addendum

(orchestrator)
