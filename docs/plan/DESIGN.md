# Freelancer Carrier & Endgame Mod: Game Design Spec

**This file is the source of truth for what the mod does.** Sources:

- Adam's design doc (PDF, 2026-10-12; not in the repo, but transcribed into this file)
- Adam's decisions of 2026-10-17

**Precedence:** this file > the PDF > agent judgment.

- Where a section grants **latitude**, the named package decides, records the decision in `state/DECISIONS.md`, and writes it into the design doc named there.
- Never ask Adam: the build is autonomous (see `AUTONOMY.md`).

Requirement IDs (`D-x.y`) are cited by package specs and tests.

---

## 1. Principles (apply to every decision)

- **D-1.1 Vanilla-faithful.** The original map, factions, lore and campaign stay intact; this is not a total conversion. Art is reused from vanilla:
  - No new meshes or textures.
  - Adding hardpoint nodes to existing models is allowed. It is a data edit that is generated at deploy time and never committed.
- **D-1.2 Single-player first**, on Freelancer: HD Edition. No server is required.
- **D-1.3 Fix the endgame gap.** Once you own an Eagle or Titan with Nomad guns, there must still be things worth fighting for and against.
- **D-1.4 Earned danger.** Threats come from the game's own patrol data and the player's reputation, not from random dice.
- **D-1.5 Never forced.** The player can always finish what they are doing. Fights wait for the player.
- **D-1.6 No artificial restrictions** (Adam):
  - There is no player-level gating anywhere. Anything affordable is buyable, given the required faction reputation.
  - Anywhere open is reachable.
  - Fleets and wingman armies have no size caps. If the engine degrades at scale, measure it and warn the player, but do not cap.

## 2. Global changes

- **D-2.1 Remove level requirements.** Every `marketgood` level requirement in every market (ships, equipment, commodities) is set to 0.
  - Reputation requirements are unchanged.
  - Done as an idempotent patch applied at deploy time to the modded profile only.
  - Verified in game: a level-1 character with enough reputation and cash can buy an Eagle at Freeport 9.
- **D-2.2 Story locks stay.** Story-locked gates and holes are part of the campaign and remain as vanilla has them.
- **D-2.3** The optional vanilla+ mods (Restored Content, Starblazer, Dockable Pygar, battleship encounters) are **out of scope for v1**.

## 3. Carrier ownership

- **D-3.1 Fleets allowed.** The player may own several carriers at once.
  - The practical cap is set by the base mechanism; it must be at least 8 and as high as the mechanism allows.
  - When the player reaches the cap, the reason is reported in the Yard panel. The cap is never hidden.
- **D-3.2 Per-carrier properties.** Each carrier has:
  - a player-editable name, class, tier and look;
  - installed upgrades and slot usage;
  - a hold inventory, nanobot and munition stocks, and hull;
  - crew wingmen, a hangar (docked wingmen) and a state machine.
- **D-3.3 Purchase rules.** Carriers are bought at Carrier Yards (§5) at full price, any time the yard base is reachable. There are no refunds. A destroyed carrier is gone; the player buys another.
  - "If I have the faction" means the player's reputation with the yard base's owning faction is not hostile (above −0.6). Being able to dock there already implies this.
  - There is no level requirement.

## 4. Classes × tiers

### 4.1 Tiers (D-4.1)

| Tier | Sold at | Base price (balanced class) | Gets |
|---|---|---|---|
| Core | House shipyards (§6) | 3,000,000 cr | Basic hold, fewer usable mounts and slots, small nanobot storage |
| Border/Edge | Frontier yards (§6) | 8,000,000 cr | Bigger hold, more mounts and slots, more nanobot storage, better catalog |
| Nomad | Planet Gammu (Ew06), after the Nomad gate (§12) | 20,000,000 cr | Strongest hull and services, including a bar and an equipment dealer aboard; Nomad tech in the catalog |

Higher tiers unlock more onboard services, up to a full bar and an equipment dealer.

### 4.2 Classes (D-4.2)

This is the minimum set. **Latitude:** W1-CARRIER-DESIGN may add one or two more classes within the principles.

Price = tier base × class multiplier. W1-CARRIER-DESIGN sets the multipliers.

| Class | Role | Hold | Hull | Docking bays | Armament | Speed | Operating cost |
|---|---|---|---|---|---|---|---|
| Trade Carrier | Haulage. Larger and much slower; relies on escorts. | Very large | Heavy | Many | Light | Slowest | Low |
| Dreadnought | Battle | Small | Heavy | Many | Very heavy: maximum turrets, missile and torpedo launchers | Fast for a capital | Very high (missiles, torpedoes and nanobots consumed and resupplied) |
| Fleet Carrier | **Balanced** all-rounder | Medium | Medium-heavy | Many | Medium | Medium | Medium |
| Command Carrier | **Balanced** flagship, crew-focused | Medium | Heavy | Medium | Medium-heavy | Medium | Medium-high |
| Strike Carrier | Wing-centric | Small-medium | Medium | Very many | Light-medium | Fast | Medium |
| Escort Carrier | Light and cheap | Small | Light | Few | Light-medium | Fastest | Low |

- **Command Carrier:** has a bar from Border/Edge tier, and bonuses to its wing (faster crew replacement, faster launch and recovery).
- **D-4.3 Looks.**
  - Every carrier uses a vanilla capital model plus a vanilla interior: house battleships, the Osiris, liners or large transports.
  - A **Core yard sells its own house's look.**
  - **The Nomad tier uses the Osiris look and Osiris interior** (the `li_06` bar).
  - **The Trade Carrier uses a liner or large-transport model** with its interior, if one with docking points exists; otherwise a house battleship look with a cargo-themed loadout.
  - **Latitude:** W1-CARRIER-DESIGN maps the remaining looks.
- **D-4.4 Turret count.** Armament is bounded by model hardpoints.
  - To reach a class's turret, missile and torpedo counts, the generator may **add hardpoint nodes** to copies of vanilla `.cmp` files, positioned on the hull surface.
  - These copies are generated from the local install and never committed.
- **D-4.5 Services by tier and class.**

  | Tier | Services |
  |---|---|
  | Core | Repair, hold access, quartermaster (resupply) |
  | Border/Edge | Core services, plus commodity trading in the hold; Command Carrier adds a bar |
  | Nomad | Border/Edge services, plus a bar and an equipment dealer for every class |

## 5. Carrier Yard (custom panel)

- **D-5.1 Panel.** A custom **Carrier Yard** panel opens from a base-menu button at yard bases. It is not a vanilla dealer.
  - **Buy:** pick a class (from this yard's list), configure upgrades at purchase, pay, name the carrier.
  - The new carrier spawns **Stopped** at a safe point near the yard base.
- **D-5.2 Retrofit.** At any yard, for a carrier that is **Stopped within 10 km of that yard base**, the player can buy, install and remove upgrades.
  - Removed upgrades go into that carrier's hold as items and can be reinstalled later. There are no refunds.
  - A carrier's loadout changes take effect immediately (respawn with the new loadout).
- **D-5.3 Upgrade categories.**
  - hull plating (hit points);
  - cargo hold expansion;
  - docking bays;
  - capital turrets (house turret families);
  - missile launchers and torpedo launchers;
  - nanobot storage and munition magazines;
  - engines (speed);
  - a capital **shield generator** (carriers have no shields by default);
  - an **interdiction dampener** (lowers ambush odds);
  - long-range sensors (earlier distress and ambush warning, longer intercept notice);
  - service modules (bar, equipment dealer, commodity hold).

  Every upgrade occupies class×tier slots: turret mounts (one per hardpoint) and utility, service and engine slots.
- **D-5.4 Per-yard catalogs differ** in what they offer and in quality (Mk I–III). Different planets offer different or improved upgrades.
  - **Latitude:** W1-CARRIER-DESIGN assigns the catalogs, guided by this spread:

    | Yard type | Strength |
    |---|---|
    | Rheinland | Best turrets |
    | Kusari | Engines and sensors |
    | Bretonia | Hull and bays |
    | Liberty | Bays and missiles |
    | Border / Edge | Interdiction gear and shields |
    | Gammu | Nomad tech (Nomad turrets, cloak if feasible) |

## 6. Where carriers are sold (D-6)

| Tier | Yard base (nickname) | Look |
|---|---|---|
| Core | Norfolk Shipyard (`Li01_07_Base`) | Liberty dreadnought |
| Core | Southampton Shipyard (`Br01_02_Base`) | Bretonia battleship |
| Core | Yokohama Shipyard (`Ku01_03_Base`) | Kusari battleship |
| Core | Oder Shipyard (`Rh01_02_Base`) | Rheinland battleship |
| Border/Edge | Freistadt (`Bw03_01_Base`) | Rheinland (latitude) |
| Border/Edge | Kurile (`Bw06_01_Base`) | Kusari (latitude) |
| Border/Edge | Cadiz (`Bw02_01_Base`) | Bretonia (latitude) |
| Border/Edge | Freeport 9 (`Ew04_01_Base`) | Liberty (latitude) |
| Nomad | Planet Gammu (`Ew06_02_Base`) | Osiris; requires the Nomad unlock flag |

Each yard offers at least 3 classes. Trade Carriers are offered at at least one Core yard and one Border/Edge yard. **Latitude:** W1-CARRIER-DESIGN assigns the rest.

## 7. Mobile carrier base (behavior, from the design doc)

The carrier is a dockable base the player orders between destinations from its docked menu. The player never pilots it; in the lore, its own captain flies it.

- **D-7.1 Orders.** "Travel to" from the docked menu, beside the shops.
  - Destinations: points within the current system (planets, bases and stations, gates and holes), adjoining systems, and **any reachable system** as a multi-hop course. The design doc's "two systems out, arriving in 4 minutes" implies multi-hop.
- **D-7.2 Docked travel.** While the player is aboard, the carrier is not in space at all.
  - Its position is computed from the route and elapsed game time.
  - The menu shows progress, e.g. "two systems out, arriving in 4 minutes".
- **D-7.3 Stop to undock.** Undocking is blocked while the carrier is "in warp".
  - Ordering Stop computes its position along the route, snaps it to a safe point and places it there.
  - Then the player can undock.
- **D-7.4 Escort travel.** Ordered from the player's own ship when nearby (within 10 km, via the in-space carrier command panel or hotkey).
  - The carrier flies as a real NPC capital ship using normal AI movement, and the player escorts it.
- **D-7.5 Out of range.** Once the player leaves, the carrier switches to simulation and keeps travelling on paper.
  - It reappears at the computed spot when the player returns, like any other base or ship.
- **D-7.6 Docking only while Stopped.** Stop also turns a moving real ship back into a dockable base.
- **D-7.7 Jump gates.** The carrier flies near the gate, plays the activation, then teleports to the far side.
  - When escorting, it appears as the player comes through.
- **D-7.8 Safe stops.** The carrier keeps a buffer from planets, stations, asteroid fields, nebulae, death and exclusion zones, and other hazards.
  - Sent to a planet, it stops close enough to be seen from it, not in orbit.
- **D-7.9 Routes.** Computed from vanilla system data (gates and jump holes).
  - Routes avoid trade lanes, since a capital ship knows better.
  - They never use links locked for the player.
- **D-7.10 Art.** Reuses vanilla capital models and interiors (§4.3).
- **D-7.11 States (7).** Every mode returns to Stopped, the only dockable state. The complete canonical edge table, including the re-route, attacked-while-stopped and destruction-outside-a-fight edges, is in `CONVENTIONS.md` §9; the list below is the design-doc summary.
  - Stopped ↔ Docked travel (travel order / arrive or Stop)
  - Stopped ↔ Escort travel (travel order / arrive or Stop)
  - Escort travel → Away (player leaves); Away → Escort travel (player returns)
  - Away → Ambush waiting (ambush roll); Ambush waiting → Under attack (player arrives)
  - Escort travel → Under attack (ambush)
  - Docked travel → Under attack (ambush, forced stop)
  - Under attack → Stopped (win); Under attack → Destroyed (lose; gone for good)
  - Edges the design implies, added for completeness:
    - **Away → Stopped** when it arrives while the player is elsewhere.
    - **Under attack → Ambush waiting** if the player leaves a live fight; it freezes again, because "fights wait for you".
- **D-7.12 Fleets.** Each carrier runs its own state machine.
  - Only the carrier the player is aboard or escorting is "live"; the rest are simulated.
- **D-7.13 Travel times.**
  - The design target for a balanced class is about **2–4 real minutes per system crossed** in docked travel.
  - Class speed multipliers come from W1-CARRIER-DESIGN.
  - Time is game time: it runs while docked and stops in the F1/Esc pause.
  - **Escort travel** (a live NPC capital) must not be painfully slow. Target: crossing a system while escorting takes at most 2× the docked-travel time for that class. W1-CARRIER-DESIGN tunes carrier engine force (and cruise, if S-NPC shows capitals can use it) to hit this.
- **D-7.14 Day length.** One in-game day is 30 minutes of unpaused play (`universe.ini [Time] seconds_per_day = 1800`). Wages, crew replacement and the boss respawn are expressed in in-game days and balanced with that in mind.

## 8. Survival and loss

- **D-8.1 Auto nanobots.** A very large but finite stock, carried as cargo and used automatically in combat by the **same reflex code** as the player copilot (§11.1). Keeping it stocked is part of the game.
- **D-8.2 No shields by default.** Vanilla capital ships have none; a shield generator is an upgrade.
- **D-8.3 Permanent loss.** Rebuy at full price.
- **D-8.4 Everything aboard drops** when the carrier dies:
  - hold contents, stored items and stocks;
  - bundled into large-count loot crates within the engine's crate cap (about 6 per death), to avoid lag.
  - A vanilla crate holds one good type, so mixed contents go into **salvage pods**: a new lootable good, `fcm_salvage_pod`, carrying a manifest. Tractoring a pod in gives its contents, with whatever doesn't fit going back out as more pods.
- **D-8.5** Hired wingmen docked in its hangar **auto-launch when an ambush starts**, so they are never aboard when it dies. Crew wingmen die with their carrier.
- **D-8.6 Operating costs.** Missiles, torpedoes and nanobots are consumed in use and must be resupplied (quartermaster aboard, or Yards).
  - Munition use by the carrier's own launchers is tracked; empty launchers stop firing.

## 9. Ambushes (rare and earned)

- **D-9.1 When they can happen.** Only where the route crosses areas an enemy patrols in real strength, **and** only if that enemy has interdiction strong enough to pull a capital ship out of cruise:
  - cruise-disruptor-capable NPCs at the zone's level;
  - or gunboat/capital presence.
- **D-9.2 Odds come from vanilla data.** Patrol zones in each system file (faction, density, encounter chance, level, patrol paths) define who flies where and how densely.
  - Reputation weights the odds: friendly space (reputation ≥ +0.6) is safe passage.
  - Hostility uses the game's ±0.6 thresholds.
- **D-9.3 Cargo value raises the odds**, with a multiplier capped at **×1.5**.
- **D-9.4 No trade lanes.** The carrier avoids lanes, so lane hacking is rarely a factor.
- **D-9.5 Outcome depends on where the player is:**

  | Player is | What happens |
  |---|---|
  | Docked aboard | Alert, forced stop, the carrier appears with attackers nearby; the player launches and fights. To honor "never forced", the fight holds until the player launches: attackers keep their distance and the carrier takes no damage. |
  | Escorting | A real fight on the spot |
  | Away | A distress call. The carrier and the fight pause indefinitely, even for days |

- **D-9.6 Paused fights.** The attacker lineup, carrier condition and location are saved.
  - The fight spawns when the player drops out of cruise within a set distance (default 8 km), giving a few seconds of "there it is, under fire".
  - Distress UX: Neural Net message, waypoint, log entry.
- **D-9.7 One at a time per carrier.** No new ambush rolls for a carrier while one is waiting.
- **D-9.8 Attacker lineups.** Built from the attacking faction's own patrol encounter templates and level.
  - Scaled to threaten a capital by carrier tier and class.
  - Includes gunboats, cruisers or battleships where that faction plausibly has them (house navies use the unused d22/d25 capital NPCs).
- **D-9.9 Frequency targets** are in `TESTING.md` §Metrics. Liberty core is essentially safe; the frontier is dangerous.

## 10. Shared encounter system

Ambushes, the Nomad boss and endgame escalation all reduce to one thing: **spawn this group of enemies here, under these conditions.** Build it once; all three use it.

- **D-10.1 Definition:** faction, ship list, loadouts, levels and size of the group.
- **D-10.2 Trigger:** the condition that starts it, e.g. an ambush roll, entering a zone, an escalation stage, or engaging Nomads in Ew06.
- **D-10.3 Placement:** where the group appears relative to the player, the carrier or a point.
- **D-10.4 Persistence:** a saved, frozen state, so a fight can wait (as with paused distress calls). Includes partial-fight freeze and thaw.
- **D-10.5 Outcome hooks:** what happens on a win or a loss, e.g. set the Nomad unlock flag, destroy the carrier, change faction influence.

## 11. Copilot and wingmen

Fast code handles split-second actions; the LLM sets strategy and gives the crew personality. **The LLM never sits in the reflex loop.**

- **D-11.1 Reflex layer (code).** Fires nanobots and shield batteries on thresholds, under a policy the brain may adjust within clamps.
  - A hard floor: below critical hull, the reflex always fires.
  - The same code runs the carrier's auto-nanobots.
- **D-11.2 Brain (LLM).** Runs through Claude Code CLI on Adam's subscription.
  - Model `claude-opus-5-5`, effort `low`.
  - No tools, no MCP or connectors; it runs in an empty working directory.
  - It turns spoken orders into policy ("save bots for the cruiser"), handles conversation, and keeps memory across sessions.
  - A deterministic grammar handles common orders without the LLM.
- **D-11.3 Voice.**
  - Speech-to-text: faster-whisper `large-v3-turbo` on the GPU.
  - Text-to-speech: Kokoro, a distinct voice per crew member.
  - Playback: on the host through PipeWire.
  - **Mic: Adam's headset mic.** The PipeWire source is matched by the substring `mic_match` in `local/sidecar.local.yaml`. That file is gitignored, already holds Adam's value, and overrides the public default config. Never put the device name in a committed file.
  - **Push-to-talk: numpad period (VK_DECIMAL, 110)** by default.
    - Numpad minus (109) is bound in vanilla `keymap.ini` to the hidden `USER_ZOOM_IN`.
    - A config option `ptt_key = numpad_minus` removes that binding and uses it instead.
  - With the sidecar absent, the game works fine and only voice is missing.
  - Test safety (fake LLM, null audio, offline models, brain sandbox) follows `CONVENTIONS.md` §13.
- **D-11.4 Crew wingmen.** Each carrier comes with 2 (3 at Nomad tier).
  - A destroyed crew wingman is replaced at its carrier after 1 in-game day (faster on a Command Carrier).
- **D-11.5 Hired wingmen.** Hired from **bars** across Sirius.
  - The candidate pool depends on the base's faction and region, so pirate bars offer pirates; hiring may need reputation with that faction.
  - Candidates vary by pilot skill (easy, medium, hard, ace), ship class (light to very heavy fighters; gunboats at high tiers) and loadout quality.
  - Costs: a **hire fee plus a small daily wage** (in-game days). Unpaid wages for 3 days means the pilot quits.
  - **Permanent death.**
  - **No roster cap** (D-1.6).
- **D-11.6 Docking bays** cap how many ships launch from and recover to a carrier. Ships following the player are not capped.
  - Roster assignments: follow the player, guard carrier X, or stay docked aboard carrier X.
- **D-11.7 Orders:** formation, focus target, retreat, guard carrier, regroup. Given by voice, hotkeys or the roster panel. The game's own AI flies and fights.
- **D-11.8 Escort duty.** Wingmen can guard a carrier while it travels:
  - Live: they fly with it.
  - Away: they travel on paper with it, freeze with its ambush, and spawn to fight when the player arrives.
- **D-11.9 Army scale.** No cap. The S-PERF spike measures performance. Above a measured threshold the mod warns the player once per session, but does not cap.

## 12. Nomad gate and boss

- **D-12.1 The gate.** The robot planet (**Planet Gammu, `Ew06_02_Base`, in the "Unknown" system Ew06**) won't build carriers until the player defeats a Nomad battleship with heavy support.
  - Winning sets a persistent character flag that unlocks the Gammu yard.
- **D-12.2 Group:** a Nomad battleship, 2 Nomad gunboats and 8 Nomad fighters.
  - They need new global NPC definitions; the vanilla ones exist only in mission files.
- **D-12.3 Location and behavior.**
  - When the player is in Ew06 and the boss is "up", the group spawns at a random safe point anywhere in Ew06 and roams.
  - **If the player engages Nomads in Ew06** (damage exchanged with `fc_n_grp`), the boss group **seeks out the player** and moves to intercept.
- **D-12.4 Respawn.** After defeat it returns after 4 in-game days, so the fight is repeatable. The unlock happens once.
- **D-12.5** Built on the shared encounter system (§10).

## 13. Endgame escalation (designed during the build)

- **D-13.1 When it starts:** after campaign completion (save at `Mission_13` succeeded, MissionNum 42, or HDE open single player), tracked by our own persistent flag.
- **D-13.2 Who designs it.** At Wave 4 a dedicated design agent (**W4-ESCALATION-DESIGN**) builds an intricate, compelling, **persistent, player-alterable faction-influence system**.
  - Adam's example: fight for the Liberty Rogues and expand their power and influence yourself. That persists, and lets them take over rogue-friendly bases in systems expanding outward from Liberty where you've been helping them.
  - It must include:
    - Nomad resurgence spreading in stages;
    - house wars (e.g. Liberty vs Rheinland open war with real capital fleets in the original systems);
    - scaling bounties that grow with gear and reputation.
  - Fresh ideas and inspirations from other games and media are welcome, within the principles (§1).
- **D-13.3 Design doc.** The agent writes `docs/design/ESCALATION.md` so Adam can review and suggest changes after the build. Implementation proceeds without waiting for him.
- **D-13.4 Engine experiments first.** Base takeovers touch static data: base affiliation, base NPCs and markets. The design agent runs engine spikes and designs within what is proven to work.

## 14. Persistence

- **D-14.1 Mod state lives in a versioned JSON file beside each save:** `<save>.carrier.json` holds carriers, encounters, wingmen, flags and the influence model.
  - It is written on every save and read on every load.
  - Critical flags (Nomad unlock, campaign-complete) are also mirrored inside the `.fl`.
- **D-14.2 Every save names a base that exists.** Never leave a save pointing at a base whose solar may be missing.
- **D-14.3 Schema.** Versioned, with migrations. Loading a save with no JSON (a pre-mod save) initializes cleanly.
- **D-14.4 Uninstalling.** A tool moves the player out of carrier bases in saves before the mod is uninstalled.

## 15. Text and UI

- **D-15.1 Text.** Static text goes in our resource DLL. HDE puts it at index 8 (IDS 524288+); the index is detected at deploy time.
  - Dynamic text uses runtime infocard overrides or our own UI.
- **D-15.2 Look.** UI looks like Freelancer (fonts, colors, layout).
  - Native base-menu buttons where proven; otherwise styled overlay windows.
  - The UI must be readable at 1280×720 and up to 4K.
- **D-15.3 Every panel is keyboard and mouse usable.** Hotkeys are rebindable where the platform allows.
